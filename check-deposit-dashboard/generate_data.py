#!/usr/bin/env python3
"""Generate the synthetic data behind the mobile check deposit flow dashboard.

Every check, person, bank and figure here is invented. Northwind Bank does not
exist, reviewer and analyst names come from Faker, and every rate is drawn from
the made-up ranges in HANDOFF.md section 4.

Raw files (one row per check / per return):
    checks.csv, returns.csv
Aggregated files (what the page reads; it only filters and sums them):
    node_counts.csv, timing_rows.csv, reviewer_rejections.csv

Usage:
    python generate_data.py --seed 42 --out data/

The same seed always gives byte-identical files.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from faker import Faker

# --------------------------------------------------------------------------- catalogues
SEGMENTS = ["direct_deposit", "no_direct_deposit", "unknown"]
QUEUES = ["fast_track", "standard", "high_risk"]
QUEUE_LABEL = {"fast_track": "Fast-track queue", "standard": "Standard review", "high_risk": "High-risk review"}

AUTO_DENY = {  # vendor screening reason -> sub-reasons
    "Duplicate item detected": ["Same image submitted twice", "Item already deposited here",
                                "Item deposited at another institution"],
    "Image quality failure": ["Image too dark", "Image cropped", "Image blurry", "Routing line unreadable"],
    "Daily item limit exceeded": ["Daily dollar limit", "Daily item count limit"],
    "Account not eligible": ["Account opened under 30 days", "Account restricted", "Negative balance"],
    "Check type not accepted": ["Third-party check", "Foreign check", "Money order", "Savings bond"],
    "Risk score too high": ["Several deposits in a short window", "New device", "High amount for account history"],
}
AUTO_DENY_WEIGHTS = [0.27, 0.24, 0.16, 0.13, 0.11, 0.09]

REJECT_REASONS = [
    "Endorsement missing", "Image unreadable", "Amount mismatch", "Restrictive endorsement missing",
    "Payee name mismatch", "Post-dated", "Stale-dated", "Signature missing", "Duplicate of earlier deposit",
    "Endorsement does not match payee", "Altered item", "Suspected counterfeit",
]
REJECT_WEIGHTS = {  # per queue; high-risk leans to altered / counterfeit items
    "fast_track": [.46, .30, .12, .06, .03, .02, .01, .0, .0, .0, .0, .0],
    "standard": [.40, .24, .14, .09, .05, .04, .02, .01, .01, .0, .0, .0],
    "high_risk": [.05, .04, .08, .02, .05, .02, .02, .03, .05, .08, .34, .22],
}

RETURN_REASONS = ["NSF", "Stop payment", "Closed account", "Uncollected funds hold", "Refer to maker",
                  "Unable to locate account", "Duplicate presentment", "Altered/fictitious item", "Forgery",
                  "Signature missing"]
RETURN_WEIGHTS = [.38, .14, .12, .08, .07, .06, .05, .04, .04, .02]
NO_REASON = "No reason recorded"
NOT_ENTERED = "Not entered"

BANK_PREFIXES = ["Harbor", "Pinecrest", "Larkspur", "Quillstone", "Fernwick", "Ambergate", "Thistlewood",
                 "Brackenridge", "Copper Hollow", "Silverbrook", "Wrenfield", "Marlow Ridge", "Ashgrove",
                 "Kestrel Point", "Bramblewood", "Stonemere", "Glenhaven", "Juniper Flats", "Oakhurst Valley",
                 "Saltmarsh", "Heron Bay", "Willowmere", "Cobble Creek", "Redfern", "Lanternhill"]
BANK_SUFFIXES = ["State Bank", "Credit Union", "Savings Bank", "Community Bank", "Trust Company"]

# Business days to funds available = review delay + hold. Shares per queue.
REVIEW_DELAY = {"fast_track": ([0, 1], [.8, .2]), "standard": ([0, 1, 2], [.55, .35, .10]),
                "high_risk": ([0, 1, 2], [.3, .4, .3])}
HOLD = {"fast_track": ([0, 2, 4, 5], [.55, .37, .05, .03]), "standard": ([0, 2, 4, 5], [.08, .17, .45, .30]),
        "high_risk": ([0, 2, 4, 5, 8], [.05, .25, .25, .25, .20])}
REJECT_DELAY = {"fast_track": ([0, 1, 2], [.7, .25, .05]), "standard": ([0, 1, 2], [.35, .45, .2]),
                "high_risk": ([0, 1, 2], [.15, .45, .4])}
RETURN_MULT = {"fast_track": .85, "standard": 1.25, "high_risk": 2.0}


# --------------------------------------------------------------------------- calendar
def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """n-th weekday (Mon=0) of a month; n = -1 for the last one."""
    if n > 0:
        d = dt.date(year, month, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def us_federal_holidays(year: int) -> list[dt.date]:
    """US federal holidays, moved to the observed weekday when they fall on a weekend."""
    def observed(d: dt.date) -> dt.date:
        return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d
    fixed = [dt.date(year, 1, 1), dt.date(year, 6, 19), dt.date(year, 7, 4), dt.date(year, 11, 11),
             dt.date(year, 12, 25)]
    floating = [nth_weekday(year, 1, 0, 3), nth_weekday(year, 2, 0, 3), nth_weekday(year, 5, 0, -1),
                nth_weekday(year, 9, 0, 1), nth_weekday(year, 10, 0, 2), nth_weekday(year, 11, 3, 4)]
    return sorted([observed(d) for d in fixed] + floating)


# --------------------------------------------------------------------------- generation
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="data/")
    p.add_argument("--start", default="2026-01-01", help="first day checks are received")
    p.add_argument("--end", default="2026-11-24", help="data cut-off: last day checks are received")
    return p.parse_args()


def pick(rng: np.random.Generator, choices, weights):
    w = np.asarray(weights, float)
    return choices[rng.choice(len(choices), p=w / w.sum())]


def generate(seed: int, start: dt.date, end: dt.date):
    rng = np.random.default_rng(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    holidays = np.array([np.datetime64(d) for y in range(start.year, end.year + 2) for d in us_federal_holidays(y)])
    end64 = np.datetime64(end)

    def bday(d: np.datetime64, n: int) -> np.datetime64:
        return np.busday_offset(d, n, roll="forward", holidays=holidays)

    def bdays_between(a: np.datetime64, b: np.datetime64) -> int:
        return int(np.busday_count(bday(a, 0), b, holidays=holidays))

    names = []
    while len(names) < 15:  # 10 reviewers + 5 analysts, all distinct
        n = fake.name()
        if n not in names and "." not in n:
            names.append(n)
    reviewers, analysts = names[:10], names[10:]
    banks = [f"{p} {BANK_SUFFIXES[i % len(BANK_SUFFIXES)]}" for i, p in enumerate(BANK_PREFIXES)]
    banks += [f"{p} {BANK_SUFFIXES[(i + 2) % len(BANK_SUFFIXES)]}" for i, p in enumerate(BANK_PREFIXES[:20])]
    bank_w = 1 / np.arange(1, len(banks) + 1) ** 0.9
    analyst_entry_w = [.34, .26, .2, .12, .08]
    analyst_case_w = [.24, .22, .2, .18, .16]

    # ---- receipts: monthly volume, spread over days (weekends about half of a weekday)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    hol = set(holidays.astype("datetime64[D]").astype(object))
    recv_days: list[dt.date] = []
    month_params: dict[str, dict] = {}
    for ym in sorted({d.strftime("%Y-%m") for d in days}):
        mdays = [d for d in days if d.strftime("%Y-%m") == ym]
        full = (dt.date(mdays[0].year + mdays[0].month // 12, mdays[0].month % 12 + 1, 1) - mdays[0].replace(day=1)).days
        volume = int(rng.uniform(2800, 3800) * len(mdays) / full)
        w = np.array([(0.5 if d.weekday() >= 5 else 0.62 if d in hol else 1.0) for d in mdays])
        w *= rng.lognormal(0, 0.12, len(mdays))
        counts = rng.multinomial(volume, w / w.sum())
        for d, k in zip(mdays, counts):
            recv_days += [d] * int(k)
        fast, high = rng.uniform(.58, .64), rng.uniform(.035, .055)
        dd, nodd = rng.uniform(.80, .90), rng.uniform(.03, .06)
        month_params[ym] = {
            "auto_deny": rng.uniform(.18, .25),
            "queue": [fast, 1 - fast - high, high],
            "segment": [dd, nodd, 1 - dd - nodd],
            "deposit": {"fast_track": rng.uniform(.92, .96), "standard": rng.uniform(.78, .85),
                        "high_risk": rng.uniform(.80, .88)},
            "return": rng.uniform(.022, .036),
        }

    # Weekly reviewer teams: each week, 2-3 reviewers work fast-track and a different 2-3 work
    # standard review, with one or two of them carrying most of it (Pareto-like). High-risk
    # items always go to the two senior reviewers.
    week_w: dict[tuple, np.ndarray] = {}

    def reviewer_for(day: dt.date, queue: str) -> str:
        if queue == "high_risk":
            return reviewers[int(rng.random() < .35)]
        wk = day - dt.timedelta(days=day.weekday())
        if (wk, queue) not in week_w:
            sizes = rng.integers(2, 4, size=2)
            pool = rng.permutation(np.arange(2, len(reviewers)))
            for q, team in zip(["fast_track", "standard"], [pool[:sizes[0]], pool[sizes[0]:sizes.sum()]]):
                w = np.zeros(len(reviewers))
                w[team] = (1 / np.arange(1, len(team) + 1) ** 2.0) * rng.lognormal(0, 0.2, len(team))
                week_w[(wk, q)] = w / w.sum()
        return reviewers[rng.choice(len(reviewers), p=week_w[(wk, queue)])]

    in_queue_p = {end - dt.timedelta(days=2): .006, end - dt.timedelta(days=1): .012, end: .02}
    checks, returns = [], []
    for i, rd in enumerate(recv_days, start=1):
        ym = rd.strftime("%Y-%m")
        mp = month_params[ym]
        amount = int(min(round(rng.lognormal(np.log(350), 0.95), 2), 10_000) * 100)  # cents
        row = {"check_id": f"R-{i:06d}", "received_date": rd.isoformat(), "segment": "unknown",
               "amount_cents": amount, "auto_denied": 0, "auto_deny_reason": "", "auto_deny_sub_reason": "",
               "queue": "", "outcome": "", "reject_reason": "", "reviewer": "", "funds_available_date": "",
               "decision_date": "", "days_to_decision": None, "days_to_return": None}
        checks.append(row)
        r64 = np.datetime64(rd)
        if rng.random() < mp["auto_deny"]:
            reason = pick(rng, list(AUTO_DENY), AUTO_DENY_WEIGHTS)
            subs = AUTO_DENY[reason]
            row.update(auto_denied=1, auto_deny_reason=reason,
                       auto_deny_sub_reason=pick(rng, subs, 1 / np.arange(1, len(subs) + 1) ** 0.7),
                       decision_date=rd.isoformat())
            continue
        row["segment"] = pick(rng, SEGMENTS, mp["segment"])
        if rng.random() < in_queue_p.get(rd, 0):
            row.update(queue="in_queue", outcome="in_queue")
            continue
        q = pick(rng, QUEUES, mp["queue"])
        row["queue"] = q
        if rng.random() < mp["deposit"][q]:
            delay = int(pick(rng, *REVIEW_DELAY[q]))
            hold = int(pick(rng, *HOLD[q]))
            if hold == 8:  # extended exception hold
                hold = int(rng.integers(6, 12))
            decided = min(bday(r64, delay), end64)
            funds = bday(r64, delay + hold)
            row.update(outcome="deposited", decision_date=str(decided), reviewer=reviewer_for(decided.astype(object), q))
            if funds <= end64:
                row["funds_available_date"] = str(funds)
                row["days_to_decision"] = bdays_between(r64, funds)
                p_ret = mp["return"] * RETURN_MULT[q]
                if rng.random() < p_ret:
                    ret = bday(funds, int(rng.integers(2, 16)))
                    if ret <= end64:
                        no_reason = rng.random() < .03
                        returns.append({
                            "check_id": row["check_id"], "deposit_date": str(funds), "return_date": str(ret),
                            "return_amount_cents": amount,
                            "return_reason": "" if no_reason else pick(rng, RETURN_REASONS, RETURN_WEIGHTS),
                            "returning_bank": pick(rng, banks, bank_w),
                            "reason_entered_by": "" if no_reason else pick(rng, analysts, analyst_entry_w),
                            "case_assigned_to": pick(rng, analysts, analyst_case_w),
                        })
                        row["days_to_return"] = bdays_between(funds, ret)
        else:
            delay = int(pick(rng, *REJECT_DELAY[q]))
            decided = min(bday(r64, delay), end64)
            row.update(outcome="rejected", decision_date=str(decided),
                       reject_reason=pick(rng, REJECT_REASONS, REJECT_WEIGHTS[q]),
                       reviewer=reviewer_for(decided.astype(object), q),
                       days_to_decision=bdays_between(r64, decided))
    return checks, returns


# --------------------------------------------------------------------------- aggregation
def node_rows(c: dict, returned: dict | None) -> list[tuple]:
    """(node_id, label, parent, kind, key) for every node and breakdown a check counts in."""
    out = [("received", "Checks received", "", "flow", "")]
    if c["auto_denied"]:
        r, s = c["auto_deny_reason"], c["auto_deny_sub_reason"]
        return out + [("auto_denied", "Auto-denied by vendor screening", "received", "flow", ""),
                      ("auto_denied", r, "", "auto_deny_reason", r),
                      ("auto_denied", s, r, "auto_deny_sub", f"{r}||{s}")]
    out.append(("approved", "Approved for review", "received", "flow", ""))
    q = c["queue"]
    if q == "in_queue":
        return out + [("in_queue", "Still in queue", "approved", "flow", "")]
    out.append((q, QUEUE_LABEL[q], "approved", "flow", ""))
    if c["outcome"] == "rejected":
        return out + [(f"{q}_rejected", "Rejected", q, "queue_outcome", ""),
                      ("rejected", "Rejected (total)", "approved", "flow", ""),
                      (f"{q}_rejected", c["reject_reason"], f"{q}_rejected", "reject_reason", c["reject_reason"])]
    out += [(f"{q}_deposited", "Deposited", q, "queue_outcome", ""),
            ("deposited", "Deposited (total)", "approved", "flow", "")]
    if returned is None:
        return out + [("not_returned", "Deposited, not returned", "deposited", "flow", "")]
    key = "||".join([returned["return_reason"] or NO_REASON, returned["returning_bank"],
                     returned["reason_entered_by"] or NOT_ENTERED, returned["case_assigned_to"]])
    return out + [("returned", "Returned after deposit", "deposited", "flow", ""),
                  ("returned", returned["return_reason"] or NO_REASON, "returned", "return_combo", key)]


def aggregate(checks: list[dict], returns: list[dict]):
    by_check = {r["check_id"]: r for r in returns}
    nodes: dict[tuple, list] = {}
    for c in checks:
        for node_id, label, parent, kind, key in node_rows(c, by_check.get(c["check_id"])):
            for seg in (c["segment"], "all"):
                k = (c["received_date"], seg, node_id, kind, key)
                if k not in nodes:
                    nodes[k] = [label, parent, 0, 0]
                nodes[k][2] += 1
                nodes[k][3] += c["amount_cents"]

    timing = [(c["received_date"][:7], c["received_date"], c["segment"], c["queue"], c["outcome"],
               c["days_to_decision"], c["days_to_return"])
              for c in checks if c["days_to_decision"] is not None]

    rej = Counter()
    for c in checks:
        if c["outcome"] == "rejected":
            d = dt.date.fromisoformat(c["decision_date"])
            wk = d - dt.timedelta(days=d.weekday())
            rej[(wk.isoformat(), (wk + dt.timedelta(days=6)).isoformat(), c["reviewer"], c["reject_reason"],
                 c["queue"])] += 1
    return nodes, timing, rej


# --------------------------------------------------------------------------- invariants
def check_invariants(checks, returns, nodes, rej) -> None:
    tot: dict[tuple, list] = defaultdict(lambda: [0, 0])  # (month, segment, node_id, kind) -> [count, cents]
    for (date, seg, node_id, kind, _), (_, _, n, cents) in nodes.items():
        t = tot[(date[:7], seg, node_id, kind)]
        t[0] += n
        t[1] += cents
    months = sorted({k[0] for k in tot})

    def v(m, s, node, kind="flow", i=0):
        return tot.get((m, s, node, kind), [0, 0])[i]

    for m in months:
        for s in ["all"] + SEGMENTS:
            for i in (0, 1):  # counts and amounts
                where = f"{m} {s} {'count' if i == 0 else 'amount'}"
                rec, ad, ap = v(m, s, "received", i=i), v(m, s, "auto_denied", i=i), v(m, s, "approved", i=i)
                iq, dep, rj = v(m, s, "in_queue", i=i), v(m, s, "deposited", i=i), v(m, s, "rejected", i=i)
                assert rec == ad + ap, f"received = auto-denied + approved ({where})"
                assert ap == sum(v(m, s, q, i=i) for q in QUEUES) + iq, f"approved = queues + in queue ({where})"
                assert ap == dep + rj + iq, f"approved = deposited + rejected + in queue ({where})"
                assert dep == sum(v(m, s, f"{q}_deposited", "queue_outcome", i) for q in QUEUES), \
                    f"deposited total = queue deposited boxes ({where})"
                assert rj == sum(v(m, s, f"{q}_rejected", "queue_outcome", i) for q in QUEUES), \
                    f"rejected total = queue rejected boxes ({where})"
                ret = v(m, s, "returned", i=i)
                assert ret <= dep, f"returned <= deposited ({where})"
                assert ret == v(m, s, "returned", "return_combo", i), f"return_combo rows sum to returned ({where})"
                assert dep == ret + v(m, s, "not_returned", i=i), f"deposited = returned + not returned ({where})"
    all_rows: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for (date, seg, node_id, kind, key), (_, _, n, cents) in nodes.items():
        if seg != "all":
            all_rows[(date, node_id, kind, key)][0] += n
            all_rows[(date, node_id, kind, key)][1] += cents
    for (date, seg, node_id, kind, key), (_, _, n, cents) in nodes.items():
        if seg == "all":
            assert all_rows[(date, node_id, kind, key)] == [n, cents], "segment = all equals the sum of segments"
    assert len(all_rows) == sum(1 for k in nodes if k[1] == "all"), "every segment row has an all row"
    rejected = Counter((c["queue"], c["reviewer"], c["reject_reason"]) for c in checks if c["outcome"] == "rejected")
    rr = Counter()
    for (_, _, reviewer, reason, q), n in rej.items():
        rr[(q, reviewer, reason)] += n
    assert rr == rejected, "reviewer_rejections contains exactly the rejected checks"
    assert len({r["check_id"] for r in returns}) == len(returns), "one return per check"


# --------------------------------------------------------------------------- output
def money(cents: int) -> str:
    return f"{cents / 100:.2f}"


def write_csv(path: Path, header: list[str], rows) -> int:
    n = 0
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(r)
            n += 1
    return n


def main() -> None:
    a = parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    checks, returns = generate(a.seed, dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end))
    nodes, timing, rej = aggregate(checks, returns)
    check_invariants(checks, returns, nodes, rej)

    counts = {}
    counts["checks.csv"] = write_csv(out / "checks.csv", [
        "check_id", "received_date", "segment", "amount", "auto_denied", "auto_deny_reason", "auto_deny_sub_reason",
        "queue", "outcome", "reject_reason", "reviewer", "funds_available_date", "decision_date"],
        ([c["check_id"], c["received_date"], c["segment"], money(c["amount_cents"]), c["auto_denied"],
          c["auto_deny_reason"], c["auto_deny_sub_reason"], c["queue"], c["outcome"], c["reject_reason"],
          c["reviewer"], c["funds_available_date"], c["decision_date"]] for c in checks))
    counts["returns.csv"] = write_csv(out / "returns.csv", [
        "check_id", "deposit_date", "return_date", "return_amount", "return_reason", "returning_bank",
        "reason_entered_by", "case_assigned_to"],
        ([r["check_id"], r["deposit_date"], r["return_date"], money(r["return_amount_cents"]), r["return_reason"],
          r["returning_bank"], r["reason_entered_by"], r["case_assigned_to"]] for r in returns))
    counts["node_counts.csv"] = write_csv(out / "node_counts.csv", [
        "date", "month", "segment", "node_id", "label", "parent", "kind", "key", "count", "amount"],
        ([date, date[:7], seg, node_id, label, parent, kind, key, n, money(cents)]
         for (date, seg, node_id, kind, key), (label, parent, n, cents) in sorted(nodes.items())))
    counts["timing_rows.csv"] = write_csv(out / "timing_rows.csv", [
        "month", "date", "segment", "queue", "decision", "days_to_decision", "days_to_return"],
        ([m, d, s, q, o, days, "" if ret is None else ret] for m, d, s, q, o, days, ret in timing))
    counts["reviewer_rejections.csv"] = write_csv(out / "reviewer_rejections.csv", [
        "week_start", "week_end", "reviewer", "reason", "queue", "count"],
        (list(k) + [n] for k, n in sorted(rej.items())))

    print("Rows per file")
    for name, n in counts.items():
        print(f"  {name:<26}{n:>8,}")
    print("\nMonthly totals (all segments, by month received)")
    cols = ["received", "auto_denied", "approved", "deposited", "rejected", "in_queue", "returned"]
    print("  month    " + "".join(f"{c:>13}" for c in cols))
    tot = Counter()
    for (date, seg, node_id, kind, _), (_, _, n, _) in nodes.items():
        if seg == "all" and kind == "flow":
            tot[(date[:7], node_id)] += n
    for m in sorted({k[0] for k in tot}):
        print(f"  {m}  " + "".join(f"{tot[(m, c)]:>13,}" for c in cols))
    print("\nAll invariants hold.")


if __name__ == "__main__":
    main()
