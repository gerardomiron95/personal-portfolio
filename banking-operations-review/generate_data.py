#!/usr/bin/env python3
"""
Generate synthetic Banking Operations data for the Northwind Bank portfolio deck.

Three sources, one per workflow, written as CSV to ./data/:

  check_deposits.csv    one row per check          (funnel, capture device, queue timing)
  ach_deposits.csv      one row per settled day    (early-pay rate and days-early mix)
  card_reissues.csv     one row per reissued card  (reason mix, repeat members)

Every figure is invented. No real customer, employee, vendor or company data,
and no parameter below is taken from any real organisation's reporting.

Determinism: SEED fixes the output, so the deck's numbers are stable across
runs and a reviewer regenerating the data sees the same slides. Change SEED to
get a different but equally plausible world.

Usage:
    python3 generate_data.py            # writes ./data/*.csv
    python3 generate_data.py --summary  # also prints the headline figures
"""

import argparse
import csv
import datetime as dt
import random
from pathlib import Path

SEED = 9174402
OUT = Path(__file__).parent / "data"

# The deck's "today". The current month is deliberately partial, so the deck
# has to compare like-for-like windows: that is part of what it demonstrates.
AS_OF = dt.date(2026, 10, 14)
CURRENT_MONTH_START = dt.date(2026, 10, 1)
HISTORY_START = dt.date(2026, 4, 1)

VENDOR = "Clearwave"          # invented image-capture vendor
COMPANY = "Northwind Bank"    # invented bank


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def is_weekend(d):
    return d.weekday() >= 5


def month_key(d):
    return d.replace(day=1)


def write(name, rows, header):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name}: {len(rows):,} rows")
    return path


# --------------------------------------------------------------------------
# 1. check deposits: the funnel, by capture device
# --------------------------------------------------------------------------
# Story the data tells: the deposited-and-kept rate runs around 77% from April
# to September, then jumps in October. The jump is real (significant against
# the same days of September), and it comes almost entirely from Android
# captures: Android auto-denials for image quality fall from October 1. The
# headline alone cannot show that; the device split can. Separately, the
# Enhanced Review queue slows in October while the other two queues hold.

DEVICES = {"iOS app": 0.54, "Android app": 0.38, "Web upload": 0.08}
AUTO_DENY = {"iOS app": 0.108, "Android app": 0.192, "Web upload": 0.151}
ANDROID_FIX_DATE = dt.date(2026, 10, 1)
ANDROID_AUTO_DENY_AFTER = 0.118
MONTH_DRIFT = {4: 0.006, 5: -0.004, 6: 0.009, 7: -0.011, 8: 0.003, 9: -0.002, 10: 0.0}
AGENT_REJECT = 0.049
PENDING = 0.026
RETURN_RATE = 0.012

REASONS = ["Image quality", "Duplicate suspected", "Endorsement missing", "Amount mismatch", "Payee mismatch"]
REASON_W = {"default": [24, 28, 21, 17, 10],
            "android_before": [52, 17, 14, 10, 7],
            "android_after": [27, 25, 20, 17, 11]}

QUEUES = ("Instant", "Standard Review", "Enhanced Review")
QUEUE_W = [0.61, 0.29, 0.10]
DAYS = {  # business days from receipt to decision, day 0 to day 7
    "Instant": [45, 35, 15, 5, 0, 0, 0, 0],
    "Standard Review": [5, 20, 35, 25, 10, 5, 0, 0],
    "Enhanced Review": [0, 5, 15, 30, 25, 15, 7, 3],
    "Enhanced Review, October": [0, 2, 8, 20, 30, 22, 12, 6],
}


def gen_checks(rng):
    rows = []
    rid = 300000
    devices, dev_w = list(DEVICES), list(DEVICES.values())
    for d in daterange(HISTORY_START, AS_OF):
        if is_weekend(d):
            continue
        base = rng.randint(430, 540)
        # the last two days are deliberately immature: the deck must exclude them
        if (AS_OF - d).days <= 1:
            base = int(base * 0.25)
        drift = MONTH_DRIFT[d.month]
        for _ in range(base):
            rid += 1
            device = rng.choices(devices, weights=dev_w)[0]
            auto_p = AUTO_DENY[device]
            if device == "Android app" and d >= ANDROID_FIX_DATE:
                auto_p = ANDROID_AUTO_DENY_AFTER
            auto_p = max(auto_p + drift, 0.01)
            roll = rng.random()
            if roll < auto_p:
                outcome = "Auto-denied"
            elif roll < auto_p + AGENT_REJECT:
                outcome = "Agent rejected"
            elif roll < auto_p + AGENT_REJECT + PENDING:
                outcome = "Pending"
            else:
                outcome = "Deposited"

            queue, days = "", ""
            if outcome in ("Deposited", "Agent rejected"):
                queue = rng.choices(QUEUES, weights=QUEUE_W)[0]
                key = "Enhanced Review, October" if queue == "Enhanced Review" and d >= CURRENT_MONTH_START else queue
                days = rng.choices(range(8), weights=DAYS[key])[0]

            returned = ""
            if outcome == "Deposited":
                returned = "Y" if rng.random() < RETURN_RATE else "N"

            auto_reason = ""
            if outcome == "Auto-denied":
                key = ("android_after" if d >= ANDROID_FIX_DATE else "android_before") \
                    if device == "Android app" else "default"
                auto_reason = rng.choices(REASONS, weights=REASON_W[key])[0]

            amount = round(min(max(rng.lognormvariate(5.6, 0.9), 5), 9500), 2)
            rows.append([
                f"CHK{rid}", d.isoformat(), device, amount, outcome, queue, days,
                returned, auto_reason, f"M{rng.randint(100000, 999999)}",
            ])
    return write("check_deposits.csv", rows,
                 ["check_id", "received_date", "capture_device", "amount_usd", "outcome",
                  "review_queue", "days_to_decision", "returned_after_deposit",
                  "auto_deny_reason", "member_id"])


# --------------------------------------------------------------------------
# 2. ACH direct deposits: early pay
# --------------------------------------------------------------------------
# Story: the early-pay rate holds a band in the high 60s, then the latest
# complete week rises above it, and the days-early mix tilts toward two days
# early. The mix is a share of EARLY deposits; the rate is a share of ALL
# deposits. A mix shift alone cannot move the rate, so the deck has to keep
# the two denominators apart.

LATEST_WEEK = (dt.date(2026, 10, 5), dt.date(2026, 10, 11))


def gen_ach(rng):
    rows = []
    for d in daterange(HISTORY_START, AS_OF):
        if is_weekend(d):
            continue
        deposits = rng.randint(9000, 12500)
        latest = LATEST_WEEK[0] <= d <= LATEST_WEEK[1]
        early_rate = rng.uniform(0.728, 0.742) if latest else rng.uniform(0.662, 0.688)
        early = int(deposits * early_rate)
        if latest:
            one = int(early * rng.uniform(0.45, 0.50))
        else:
            one = int(early * rng.uniform(0.58, 0.64))
        three = int(early * rng.uniform(0.05, 0.07))
        two = early - one - three
        rows.append([d.isoformat(), deposits, early, one, two, three,
                     round(deposits * rng.uniform(1150, 1480), 2)])
    return write("ach_deposits.csv", rows,
                 ["settled_date", "deposits", "early_deposits", "one_day_early",
                  "two_days_early", "three_days_early", "deposit_usd"])


# --------------------------------------------------------------------------
# 3. card reissues: reason mix and repeat members
# --------------------------------------------------------------------------
# Story: one reason moves this month. System-detected fraud reissues rise
# against the same days of last month while every other reason holds, so the
# deck has to test each reason rather than eyeball the mix. Separately, a
# minority of members with a loss-driven reissue this month have had others in
# the past year; that only shows over a 12-month lookback.

REISSUE_REASONS = {
    "Renewal (scheduled)": 0.27,
    "Lost": 0.22,
    "Fraud (member reported)": 0.14,
    "Damaged": 0.12,
    "Fraud (system detected)": 0.09,
    "Not received, re-sent": 0.09,
    "Stolen": 0.04,
    "Name change": 0.03,
}
LOSS_DRIVEN = ("Lost", "Stolen", "Fraud (member reported)", "Fraud (system detected)")
SYSTEM_FRAUD_LIFT = 1.7   # current month only


def gen_reissues(rng):
    rows = []
    cid = 600000
    start = AS_OF - dt.timedelta(days=400)
    repeaters = [f"M{rng.randint(100000, 999999)}" for _ in range(1400)]
    names = list(REISSUE_REASONS)
    for d in daterange(start, AS_OF):
        if is_weekend(d):
            continue
        weights = [REISSUE_REASONS[k] for k in names]
        if month_key(d) == CURRENT_MONTH_START:
            weights[names.index("Fraud (system detected)")] *= SYSTEM_FRAUD_LIFT
        for _ in range(rng.randint(58, 92)):
            cid += 1
            reason = rng.choices(names, weights=weights)[0]
            if reason in LOSS_DRIVEN and rng.random() < 0.15:
                member = rng.choice(repeaters)
            else:
                member = f"M{rng.randint(100000, 999999)}"
            rows.append([f"CRD{cid}", d.isoformat(), reason, member,
                         "Y" if reason in LOSS_DRIVEN else "N"])
    return write("card_reissues.csv", rows,
                 ["card_id", "issued_date", "reissue_reason", "member_id", "loss_driven"])


# --------------------------------------------------------------------------

def summarize():
    import collections
    print("\nHeadline figures (the deck computes its own; these are a quick look):\n")
    rows = list(csv.DictReader((OUT / "check_deposits.csv").open()))
    end = (AS_OF - dt.timedelta(days=2)).isoformat()
    cur = [r for r in rows if CURRENT_MONTH_START.isoformat() <= r["received_date"] <= end]
    kept = sum(1 for r in cur if r["outcome"] == "Deposited" and r["returned_after_deposit"] == "N")
    print(f"  Checks, Oct 1-12            {len(cur):,}")
    print(f"  Deposited and kept          {kept / len(cur) * 100:.1f}%")
    by = collections.defaultdict(lambda: [0, 0])
    for r in cur:
        by[r["capture_device"]][0] += 1
        by[r["capture_device"]][1] += r["outcome"] == "Auto-denied"
    for k, (n, a) in sorted(by.items()):
        print(f"  Auto-denied, {k:<14} {a / n * 100:.1f}%")
    ach = list(csv.DictReader((OUT / "ach_deposits.csv").open()))
    wk = [r for r in ach if LATEST_WEEK[0].isoformat() <= r["settled_date"] <= LATEST_WEEK[1].isoformat()]
    print(f"\n  Early pay, Oct 5-11         "
          f"{sum(int(r['early_deposits']) for r in wk) / sum(int(r['deposits']) for r in wk) * 100:.1f}%")
    cr = [r for r in csv.DictReader((OUT / "card_reissues.csv").open())
          if r["issued_date"] >= CURRENT_MONTH_START.isoformat()]
    print(f"  Reissues this month         {len(cr):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="print the headline figures after generating")
    args = ap.parse_args()

    rng = random.Random(SEED)
    print(f"Generating synthetic {COMPANY} Banking Operations data (seed {SEED}, as-of {AS_OF}):")
    for old in ("card_issuance.csv",):
        (OUT / old).unlink(missing_ok=True)
    gen_checks(rng)
    gen_ach(rng)
    gen_reissues(rng)
    print(f"\nWritten to {OUT}")
    if args.summary:
        summarize()


if __name__ == "__main__":
    main()
