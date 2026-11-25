#!/usr/bin/env python3
"""Compute every figure the deck shows, straight from data/*.csv.

Nothing here is typed in: windows, averages, bands and tests are all derived
from the CSVs, so regenerating the data (or moving the as-of date) moves the
deck with it. The only constants are the targets, which are policy inputs, not
measurements.

    python3 figures.py        # print the figures and the reconciliation checks
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import math
import statistics
from pathlib import Path

DATA = Path(__file__).parent / "data"

# Policy targets set by Banking Operations (inputs, not measurements).
TARGET_KEPT = 0.82                 # checks deposited and kept, share of received
TARGET_AUTO_DENY = (0.08, 0.10)    # auto-denied by Clearwave, share of received
TARGET_AGENT_REJECT = (0.03, 0.04) # rejected by an agent, share of received

LOSS_DRIVEN = ("Lost", "Stolen", "Fraud (member reported)", "Fraud (system detected)")
QUEUES = ("Instant", "Standard Review", "Enhanced Review")
SMALL_SAMPLE = 100
BUCKETS = ("one_day_early", "two_days_early", "three_days_early")


def load(name: str) -> list[dict]:
    with (DATA / name).open() as f:
        return list(csv.DictReader(f))


def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def add_months(d: dt.date, k: int) -> dt.date:
    m = d.month - 1 + k
    return dt.date(d.year + m // 12, m % 12 + 1, 1)


def month_end(d: dt.date) -> dt.date:
    return add_months(d, 1) - dt.timedelta(days=1)


def norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def two_prop(x1: int, n1: int, x2: int, n2: int) -> dict:
    """Two-proportion z-test (pooled SE) with a 95% CI on p2 - p1 (unpooled SE)."""
    p1, p2 = x1 / n1, x2 / n2
    pool = (x1 + x2) / (n1 + n2)
    se_pool = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se_pool if se_pool else 0.0
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    diff = p2 - p1
    return {"p1": p1, "p2": p2, "diff": diff, "lo": diff - 1.96 * se, "hi": diff + 1.96 * se,
            "z": z, "p": 2 * (1 - norm_cdf(abs(z))), "significant": abs(z) >= 1.96}


def chi2_sf(x: float, df: int) -> float:
    """Survival function of the chi-square distribution for an integer df."""
    if x <= 0:
        return 1.0
    if df % 2 == 0:
        term = total = math.exp(-x / 2)
        for i in range(1, df // 2):
            term *= (x / 2) / i
            total += term
        return total
    total = math.erfc(math.sqrt(x / 2))
    term = math.sqrt(2 * x / math.pi) * math.exp(-x / 2)
    for i in range(1, (df - 1) // 2 + 1):
        total += term
        term *= x / (2 * i + 1)
    return total


def shape_test(a: list[int], b: list[int]) -> dict:
    """Chi-square test that two day-count distributions share one shape (empty days dropped)."""
    cols = [(x, y) for x, y in zip(a, b) if x + y > 0]
    na, nb = sum(x for x, _ in cols), sum(y for _, y in cols)
    n = na + nb
    stat = 0.0
    for x, y in cols:
        tot = x + y
        for obs, rown in ((x, na), (y, nb)):
            exp = rown * tot / n
            stat += (obs - exp) ** 2 / exp
    df = len(cols) - 1
    p = chi2_sf(stat, df)
    return {"chi2": stat, "df": df, "p": p, "significant": p < 0.05}


# ----------------------------------------------------------------------------- checks
def check_figures(rows: list[dict]) -> dict:
    for r in rows:
        r["d"] = day(r["received_date"])
    as_of = max(r["d"] for r in rows)

    # Immature days: volume under half the median weekday volume.
    vol = collections.Counter(r["d"] for r in rows)
    med = statistics.median(vol.values())
    immature = sorted(d for d, n in vol.items() if n < 0.5 * med)
    cur_start = month_start(as_of)
    cur_end = (immature[0] - dt.timedelta(days=1)) if immature else as_of
    prev_start = add_months(cur_start, -1)
    prev_like_end = prev_start + (cur_end - cur_start)       # same elapsed days last month

    def window(a: dt.date, b: dt.date) -> list[dict]:
        return [r for r in rows if a <= r["d"] <= b]

    def funnel(ws: list[dict]) -> dict:
        c = collections.Counter()
        for r in ws:
            o = r["outcome"]
            if o == "Deposited":
                c["kept" if r["returned_after_deposit"] == "N" else "returned"] += 1
            else:
                c[{"Auto-denied": "auto", "Agent rejected": "reject", "Pending": "pending"}[o]] += 1
        c["n"] = len(ws)
        c["deposited"] = c["kept"] + c["returned"]
        return dict(c)

    first = month_start(min(r["d"] for r in rows))
    months = []
    m = first
    while m < cur_start:
        f = funnel(window(m, month_end(m)))
        months.append({"month": m.isoformat(), **f, "rate": f["kept"] / f["n"]})
        m = add_months(m, 1)
    cur = funnel(window(cur_start, cur_end))
    prev_like = funnel(window(prev_start, prev_like_end))
    avg_kept, avg_n = sum(x["kept"] for x in months), sum(x["n"] for x in months)
    pooled = avg_kept / avg_n

    tests = {}
    for key in ("kept", "returned", "auto", "reject", "pending"):
        tests[key] = two_prop(prev_like[key], prev_like["n"], cur[key], cur["n"])
    tests["return_rate"] = two_prop(prev_like["returned"], prev_like["deposited"],
                                    cur["returned"], cur["deposited"])

    # Rejected technique: p-chart, 3-sigma limits around the pooled complete-month rate.
    pchart = []
    for x in months:
        s = math.sqrt(pooled * (1 - pooled) / x["n"])
        pchart.append({"month": x["month"], "rate": x["rate"], "lcl": pooled - 3 * s,
                       "ucl": pooled + 3 * s, "outside": abs(x["rate"] - pooled) > 3 * s})

    reasons = collections.Counter(r["auto_deny_reason"] for r in window(cur_start, cur_end)
                                  if r["outcome"] == "Auto-denied")

    devices = []
    cur_w, prev_w = window(cur_start, cur_end), window(prev_start, prev_like_end)
    for dev in sorted({r["capture_device"] for r in rows}, key=lambda k: -sum(1 for r in cur_w
                                                                              if r["capture_device"] == k)):
        a = funnel([r for r in prev_w if r["capture_device"] == dev])
        b = funnel([r for r in cur_w if r["capture_device"] == dev])
        why = {}
        for label, ws in (("prev", prev_w), ("cur", cur_w)):
            denied = [r for r in ws if r["capture_device"] == dev and r["outcome"] == "Auto-denied"]
            iq = sum(1 for r in denied if r["auto_deny_reason"] == "Image quality")
            why[label] = {"image_quality": iq, "auto": len(denied)}
        devices.append({
            "device": dev, "prev": a, "cur": b,
            "kept": two_prop(a["kept"], a["n"], b["kept"], b["n"]),
            "auto": two_prop(a.get("auto", 0), a["n"], b.get("auto", 0), b["n"]),
            "image_quality": two_prop(why["prev"]["image_quality"], a["n"], why["cur"]["image_quality"], b["n"]),
            "why": why,
        })
    # How much of the headline change each device explains (its share of checks x its rate change).
    total_change = cur["kept"] / cur["n"] - prev_like["kept"] / prev_like["n"]
    for x in devices:
        x["contribution"] = x["cur"]["n"] / cur["n"] * (x["cur"]["kept"] / x["cur"]["n"] - x["prev"]["kept"] / x["prev"]["n"])
    mix_effect = total_change - sum(x["contribution"] for x in devices)

    # Days to decision, last three months (the current one to the same mature end date).
    queue_months = [add_months(cur_start, -2), add_months(cur_start, -1), cur_start]
    max_day = max(int(r["days_to_decision"]) for r in rows if r["days_to_decision"])
    queues = {}
    for q in QUEUES:
        queues[q] = []
        for qm in queue_months:
            end = cur_end if qm == cur_start else month_end(qm)
            ds = [int(r["days_to_decision"]) for r in window(qm, end) if r["review_queue"] == q]
            dist = collections.Counter(ds)
            queues[q].append({"month": qm.isoformat(), "end": end.isoformat(), "n": len(ds),
                              "dist": [dist.get(i, 0) for i in range(max_day + 1)],
                              "median": statistics.median(ds) if ds else None})
    # Did the shape move between the last complete month and the current window?
    shape = {q: shape_test(ms[-2]["dist"], ms[-1]["dist"]) for q, ms in queues.items()}

    return {
        "queue_shape_tests": shape,
        "as_of": as_of.isoformat(), "immature_days": [d.isoformat() for d in immature],
        "immature_volume": [vol[d] for d in immature], "median_day_volume": med,
        "cur_start": cur_start.isoformat(), "cur_end": cur_end.isoformat(),
        "prev_start": prev_start.isoformat(), "prev_like_end": prev_like_end.isoformat(),
        "months": months, "pooled": pooled, "pooled_span": [months[0]["month"], months[-1]["month"]],
        "cur": cur, "prev_like": prev_like, "tests": tests, "pchart": pchart,
        "auto_reasons": reasons.most_common(), "queues": queues,
        "devices": devices, "total_change": total_change, "mix_effect": mix_effect,
        "targets": {"kept": TARGET_KEPT, "auto": TARGET_AUTO_DENY, "reject": TARGET_AGENT_REJECT},
    }


# ----------------------------------------------------------------------------- ACH
def ach_figures(rows: list[dict], as_of: dt.date) -> dict:
    weeks = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        d = day(r["settled_date"])
        wk = d - dt.timedelta(days=d.weekday())               # Monday
        c = weeks[wk]
        for k in ("deposits", "early_deposits") + BUCKETS:
            c[k] += int(r[k])
    complete = sorted(w for w in weeks if w + dt.timedelta(days=6) < as_of)
    latest, base = complete[-1], complete[-9:-1]
    series = []
    for w in complete[-9:]:
        c = weeks[w]
        series.append({"week": w.isoformat(), "rate": c["early_deposits"] / c["deposits"],
                       "early": c["early_deposits"], "deposits": c["deposits"]})
    base_rates = [s["rate"] for s in series[:-1]]
    lo, hi = min(base_rates), max(base_rates)
    cur_rate = series[-1]["rate"]
    buckets = BUCKETS

    def mix(ws):
        early = sum(weeks[w]["early_deposits"] for w in ws)
        return {"early": early, "counts": [sum(weeks[w][b] for w in ws) for b in buckets],
                "shares": [sum(weeks[w][b] for w in ws) / early for b in buckets]}

    return {
        "latest_week": latest.isoformat(), "base_weeks": [base[0].isoformat(), base[-1].isoformat()],
        "series": series, "band": [lo, hi], "median": statistics.median(base_rates),
        "outside": not (lo <= cur_rate <= hi), "rate": cur_rate,
        "latest": {"early": weeks[latest]["early_deposits"], "deposits": weeks[latest]["deposits"]},
        "mix_latest": mix([latest]), "mix_base": mix(base),
    }


# ----------------------------------------------------------------------------- card reissues
def reissue_figures(rows: list[dict], as_of: dt.date) -> dict:
    for r in rows:
        r["d"] = day(r["issued_date"])
    cur_start = month_start(as_of)
    prev_start = add_months(cur_start, -1)
    prev_end = prev_start + (as_of - cur_start)
    cur = [r for r in rows if cur_start <= r["d"] <= as_of]
    prev = [r for r in rows if prev_start <= r["d"] <= prev_end]
    cc, pc = collections.Counter(r["reissue_reason"] for r in cur), collections.Counter(
        r["reissue_reason"] for r in prev)
    reasons = sorted(set(cc) | set(pc), key=lambda k: -cc.get(k, 0))
    mix = [{"reason": k, "prev": pc.get(k, 0), "cur": cc.get(k, 0),
            "prev_share": pc.get(k, 0) / len(prev), "cur_share": cc.get(k, 0) / len(cur),
            "loss_driven": k in LOSS_DRIVEN} for k in reasons]
    for x in mix:
        x["pp"] = (x["cur_share"] - x["prev_share"]) * 100
        x["test"] = two_prop(x["prev"], len(prev), x["cur"], len(cur))

    # Repeat members: this month's loss-driven cohort, counted over a trailing 12 months.
    look_start = as_of - dt.timedelta(days=364)
    ld_year = collections.Counter(r["member_id"] for r in rows
                                  if look_start <= r["d"] <= as_of and r["loss_driven"] == "Y")
    cohort = {r["member_id"] for r in cur if r["loss_driven"] == "Y"}
    buckets = collections.OrderedDict((k, 0) for k in ("1", "2", "3", "4–5", "6+"))
    for m in cohort:
        n = ld_year[m]
        buckets["1" if n == 1 else "2" if n == 2 else "3" if n == 3 else "4–5" if n <= 5 else "6+"] += 1
    repeat = sum(v for k, v in buckets.items() if k != "1")
    cards_all = sum(ld_year[m] for m in cohort)
    cards_repeat = sum(ld_year[m] for m in cohort if ld_year[m] > 1)
    # A month-to-date-only view: how many of the cohort repeat inside this month alone.
    ld_month = collections.Counter(r["member_id"] for r in cur if r["loss_driven"] == "Y")
    return {
        "cur_span": [cur_start.isoformat(), as_of.isoformat()],
        "prev_span": [prev_start.isoformat(), prev_end.isoformat()],
        "n_cur": len(cur), "n_prev": len(prev), "mix": mix,
        "ld_counts": {k: cc.get(k, 0) for k in LOSS_DRIVEN},
        "ld_total": sum(cc.get(k, 0) for k in LOSS_DRIVEN),
        "look_span": [look_start.isoformat(), as_of.isoformat()],
        "cohort": len(cohort), "buckets": dict(buckets), "repeat": repeat,
        "repeat_share": repeat / len(cohort), "month_only_repeat": sum(1 for v in ld_month.values() if v > 1),
        "cohort_cards": cards_all, "repeat_cards": cards_repeat,
    }


def compute() -> dict:
    checks = check_figures(load("check_deposits.csv"))
    as_of = day(checks["as_of"])
    return {
        "checks": checks,
        "ach": ach_figures(load("ach_deposits.csv"), as_of),
        "reissues": reissue_figures(load("card_reissues.csv"), as_of),
    }


def reconcile(F: dict) -> list[tuple[bool, str]]:
    c = F["checks"]
    out = []
    for name in ("cur", "prev_like"):
        f = c[name]
        out.append((f["kept"] + f["returned"] + f["auto"] + f["reject"] + f["pending"] == f["n"],
                    f"checks {name}: outcomes sum to volume ({f['n']:,})"))
    for m in c["months"]:
        out.append((m["kept"] + m["returned"] + m["auto"] + m["reject"] + m["pending"] == m["n"],
                    f"checks {m['month'][:7]}: outcomes sum to volume"))
    for q, ms in c["queues"].items():
        out.append((all(sum(x["dist"]) == x["n"] for x in ms), f"queue {q}: day buckets sum to n"))
    a = F["ach"]
    for k in ("mix_latest", "mix_base"):
        out.append((sum(a[k]["counts"]) == a[k]["early"], f"ACH {k}: buckets sum to early deposits"))
    r = F["reissues"]
    out.append((sum(x["cur"] for x in r["mix"]) == r["n_cur"], "reissues: current mix sums to total"))
    out.append((sum(x["prev"] for x in r["mix"]) == r["n_prev"], "reissues: prior mix sums to total"))
    out.append((sum(r["buckets"].values()) == r["cohort"], "repeat: distribution sums to cohort"))
    for name in ("cur", "prev_like"):
        out.append((sum(x[name if name == "cur" else "prev"]["n"] for x in c["devices"]) == c[name]["n"],
                    f"devices: {name} device volumes sum to the window"))
    return out


if __name__ == "__main__":
    F = compute()
    print(json.dumps(F, indent=1, default=str))
    print()
    for ok, label in reconcile(F):
        print(("PASS  " if ok else "FAIL  ") + label)
