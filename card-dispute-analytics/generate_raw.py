#!/usr/bin/env python3
"""Generate the synthetic row-level dataset for the card dispute dashboard.

Everything here is fictional: the issuer ("Northwind Bank"), the accounts, the
merchants ("Merchant 0412") and every amount. No card numbers are generated.
Timelines follow the public Reg E error-resolution rule (12 CFR 1005.11),
simplified for a demo.

Output: one Parquet file per table in data/raw/, plus _meta.json with the run
settings. The same flags (including --seed and --end) always reproduce
identical files.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ISSUER = "Northwind Bank"

CATEGORIES = np.array(["Grocery", "Dining", "Travel", "Online retail", "Fuel",
                       "Entertainment", "Utilities", "Other"])
CAT_VOLUME_SHARE = np.array([.22, .16, .07, .20, .10, .07, .06, .12])
CAT_TICKET = np.array([48, 32, 310, 72, 45, 58, 120, 65])  # average $ per card transaction

REASONS = np.array(["Unauthorized", "Merchant dispute", "Processing error"])
REASON_P = np.array([.55, .35, .10])
REASON_DETAIL = [
    (["Card lost/stolen", "Card-not-present fraud", "Account takeover"], [.35, .50, .15]),
    (["Not received", "Not as described", "Canceled service"], [.45, .35, .20]),
    (["Duplicate charge", "Incorrect amount", "Credit not processed"], [.40, .35, .25]),
]
# Merchant-category mix of disputed transactions, per reason (columns = CATEGORIES).
# Unauthorized claims skew to Online retail and Travel.
REASON_CAT_P = np.array([
    [.08, .06, .20, .40, .05, .08, .03, .10],
    [.06, .08, .14, .36, .02, .14, .08, .12],
    [.18, .14, .06, .18, .10, .06, .18, .10],
])
# Final outcome per reason: customer favor, no error found, withdrawn (~68 / 25 / 7 overall).
OUTCOME_P = np.array([
    [.74, .20, .06],
    [.60, .31, .09],
    [.66, .28, .06],
])
OUTCOMES = np.array(["Resolved - customer favor", "Resolved - no error found", "Withdrawn"])

# Transactions per claim: 72% have one, the rest 2-5.
MULTI_TXN_K = np.array([2, 3, 4, 5])
MULTI_TXN_P = np.array([.45, .28, .17, .10])
P_SINGLE_TXN = .72
MEAN_TXNS = P_SINGLE_TXN + (1 - P_SINGLE_TXN) * float(MULTI_TXN_K @ MULTI_TXN_P)

DAY = np.timedelta64(86_400, "s")


def parse_args() -> argparse.Namespace:
    today = date.today()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--accounts", type=int, default=150_000, help="card accounts (default 150,000)")
    p.add_argument("--claims", type=int, default=80_000, help="dispute claims (default 80,000)")
    p.add_argument("--start", default=f"{today.year - 1}-01-01", help="first day of data (default: Jan 1 of last year)")
    p.add_argument("--end", default=today.isoformat(),
                   help="as-of date: data runs through the day before it (default: today)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="data/raw", help="output folder (default data/raw)")
    return p.parse_args()


def secs(x) -> np.ndarray:
    """Whole seconds as timedelta64."""
    return np.asarray(x).astype("int64").astype("timedelta64[s]")


def days_td(x) -> np.ndarray:
    """Fractional days as timedelta64[s]."""
    return secs(np.round(np.asarray(x) * 86_400))


def pick(rng, n: int, cum: np.ndarray) -> np.ndarray:
    """Vectorised categorical draw; cum is a (n, k) or (k,) cumulative-probability array."""
    u = rng.random(n)
    return np.minimum((u[:, None] > np.atleast_2d(cum)).sum(axis=1), np.atleast_2d(cum).shape[1] - 1)


def main() -> None:
    a = parse_args()
    rng = np.random.default_rng(a.seed)
    start = np.datetime64(a.start, "D")
    as_of_d = np.datetime64(a.end, "D")
    as_of = as_of_d.astype("datetime64[s]")
    days = np.arange(start, as_of_d, dtype="datetime64[D]")
    n_days = len(days)
    if n_days < 60:
        raise SystemExit("need at least 60 days between --start and --end")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ card volume
    dt = pd.DatetimeIndex(days)
    weekday = np.array([.97, .98, 1.0, 1.02, 1.12, 1.10, .86])[dt.dayofweek]
    season = np.select([dt.month.isin([11, 12]), dt.month == 2], [1.35, .90], 1.0)
    growth = 1.06 ** ((days - start).astype(int) / 365.25)
    shape = weekday * season * growth * rng.uniform(.94, 1.06, n_days)
    # Disputed transactions per 10,000 card transactions: higher Nov-Jan (holiday fraud, returns).
    rate10k = np.clip(42 * np.where(dt.month.isin([11, 12, 1]), 1.22, 1.0) * rng.uniform(.93, 1.07, n_days), 35, 60)
    weight = shape * rate10k
    p_day = weight / weight.sum()
    claims_per_day = rng.multinomial(a.claims, p_day)
    card_txn_day = a.claims * p_day * MEAN_TXNS / (rate10k / 1e4)

    share = CAT_VOLUME_SHARE * rng.uniform(.95, 1.05, (n_days, len(CATEGORIES)))
    share /= share.sum(axis=1, keepdims=True)
    vol_txns = np.round(card_txn_day[:, None] * share).astype("int64")
    vol_dollars = np.round(vol_txns * CAT_TICKET * rng.uniform(.97, 1.03, vol_txns.shape), 2)
    card_volume = pd.DataFrame({
        "date": np.repeat(days, len(CATEGORIES)),
        "merchant_category": np.tile(CATEGORIES, n_days),
        "card_transactions": vol_txns.ravel(),
        "card_dollars": vol_dollars.ravel(),
    })

    # ------------------------------------------------------------------ accounts
    n_pre = int(a.accounts * .82)
    open_d = np.sort(np.concatenate([
        start - rng.integers(30, 365 * 12, n_pre).astype("timedelta64[D]"),
        start + rng.integers(0, n_days, a.accounts - n_pre).astype("timedelta64[D]"),
    ]))
    accounts = pd.DataFrame({
        "account_id": np.char.mod("A%07d", np.arange(1, a.accounts + 1)),
        "open_date": open_d,
        "product": np.where(rng.random(a.accounts) < .58, "Debit", "Credit"),
        "region": np.array(["North", "South", "East", "West", "Central"])[
            pick(rng, a.accounts, np.cumsum([.18, .22, .20, .17, .23]))],
    })

    # ------------------------------------------------------------------ claims
    day_idx = np.repeat(np.arange(n_days), claims_per_day)
    n = len(day_idx)
    recv = np.sort(days[day_idx].astype("datetime64[s]") + secs(rng.integers(6 * 3600, 23 * 3600, n)))
    recv_d = recv.astype("datetime64[D]")
    n_open_before = np.searchsorted(open_d, recv_d, side="right")
    acct = (rng.random(n) * n_open_before).astype("int64")

    reason = pick(rng, n, np.cumsum(REASON_P))
    detail = np.empty(n, dtype=object)
    for r, (labels, probs) in enumerate(REASON_DETAIL):
        m = reason == r
        detail[m] = np.array(labels)[pick(rng, int(m.sum()), np.cumsum(probs))]
    channel = np.array(["App", "Web", "Phone"])[pick(rng, n, np.cumsum([.52, .23, .25]))]

    # Extended 90-day deadline: new account (opened <= 30 days before notice), or a
    # foreign / point-of-sale transaction (simulated as a flat 10%).
    new_account = (recv_d - open_d[acct]).astype(int) <= 30
    deadline = np.where(new_account | (rng.random(n) < .10), 90, 45)

    outcome = pick(rng, n, np.cumsum(OUTCOME_P, axis=1)[reason])

    # Days from notice to resolution: most 5-40, a tail toward 90, ~1.5% past deadline.
    dur = rng.lognormal(np.log(14.5), .70, n)
    dur = np.where(deadline == 90, dur * 1.45, dur)
    dur = np.where(outcome == 2, dur * .45, dur)  # withdrawals happen early
    dur = np.clip(dur, .6, 150)
    over = (outcome != 2) & (dur > deadline) & (rng.random(n) > .36)
    dur = np.where(over, deadline * rng.uniform(.55, .97, n), dur)

    # ------------------------------------------------------------------ disputed transactions
    k = np.where(rng.random(n) < P_SINGLE_TXN, 1, MULTI_TXN_K[pick(rng, n, np.cumsum(MULTI_TXN_P))])
    t_claim = np.repeat(np.arange(n), k)
    n_t = len(t_claim)
    t_cat = pick(rng, n_t, np.cumsum(REASON_CAT_P, axis=1)[reason[t_claim]])
    t_cents = np.maximum(100, np.round(
        CAT_TICKET[t_cat] * 100 * np.exp(rng.normal(-.15, .7, n_t))
        * np.where(reason[t_claim] == 0, 1.15, 1.0))).astype("int64")
    t_date = recv_d[t_claim] - rng.integers(1, 76, n_t).astype("timedelta64[D]")
    claimed_cents = np.bincount(t_claim, weights=t_cents, minlength=n).astype("int64")

    claim_ids = np.char.mod("D%08d", np.arange(1, n + 1))
    claim_txns = pd.DataFrame({
        "claim_txn_id": np.char.mod("T%09d", np.arange(1, n_t + 1)),
        "claim_id": claim_ids[t_claim],
        "txn_date": t_date,
        "merchant_category": CATEGORIES[t_cat],
        "merchant_label": np.char.mod("Merchant %04d", rng.integers(1, 2401, n_t)),
        "amount": t_cents / 100,
    })

    end_ts = recv + days_td(dur)  # latent resolution time (may be after as-of)
    end_d = end_ts.astype("datetime64[D]")
    is_open = end_ts >= as_of
    resolved = ~is_open & (outcome < 2)
    withdrawn = ~is_open & (outcome == 2)
    status = np.where(is_open, "Open", OUTCOMES[outcome])
    nat = np.datetime64("NaT", "s")

    claims = pd.DataFrame({
        "claim_id": claim_ids,
        "account_id": accounts["account_id"].to_numpy()[acct],
        "received_ts": recv,
        "reason_category": REASONS[reason],
        "reason_detail": detail.astype(str),
        "channel": channel,
        "deadline_days": deadline,
        "claimed_amount": claimed_cents / 100,
        "status": status,
        "resolved_ts": np.where(is_open, nat, end_ts),
    })

    # ------------------------------------------------------------------ provisional credit
    # Required when the claim is still open at the end of business day 10 after notice.
    bd10_due = (np.busday_offset(recv_d, 10, roll="forward") + 1).astype("datetime64[s]")
    required = (end_ts > bd10_due) & (bd10_due <= as_of)
    bd_offset = np.where(rng.random(n) < .97, rng.integers(8, 11, n), rng.integers(11, 14, n))
    issue_ts = (np.busday_offset(recv_d, bd_offset, roll="forward").astype("datetime64[s]")
                + secs(rng.integers(9 * 3600, 18 * 3600, n)))
    on_time_fallback = (np.busday_offset(recv_d, 10, roll="forward").astype("datetime64[s]")
                        + secs(rng.integers(9 * 3600, 18 * 3600, n)))
    issue_ts = np.where(issue_ts >= end_ts, on_time_fallback, issue_ts)  # credit always precedes resolution
    has_pc = required & (issue_ts < as_of)
    pc_final = np.where(is_open, "Pending", np.where(outcome == 0, "Made permanent", "Reversed"))
    provisional_credits = pd.DataFrame({
        "claim_id": claim_ids[has_pc],
        "issued_ts": issue_ts[has_pc],
        "amount": claimed_cents[has_pc] / 100,
        "final_status": pc_final[has_pc],
        "final_ts": np.where(is_open, nat, end_ts)[has_pc],
    })

    # ------------------------------------------------------------------ status events
    ev_claim, ev_ts, ev_name = [], [], []

    def add(mask, ts, name):
        idx = np.flatnonzero(mask)
        ev_claim.append(idx)
        ev_ts.append(np.asarray(ts)[idx] if np.ndim(ts) else np.full(len(idx), ts))
        ev_name.append(np.full(len(idx), name, dtype=object))

    ack_ts = recv + days_td(np.minimum(rng.uniform(.05, 1.5, n), dur * .3))
    inv_ts = end_ts - days_td(np.minimum(rng.uniform(.1, 1.5, n), dur * .25))
    notify_ts = (np.busday_offset(end_d, rng.integers(1, 4, n), roll="forward").astype("datetime64[s]")
                 + secs(rng.integers(9 * 3600, 17 * 3600, n)))

    # ~3% of longer resolved claims were resolved once, reopened, then resolved again.
    reopened = resolved & (dur > 25) & (rng.random(n) < .03)
    r1_ts = recv + days_td(dur * .4)
    inv1_ts = r1_ts - days_td(.5)
    notify1_ts = (np.busday_offset(r1_ts.astype("datetime64[D]"), 1, roll="forward").astype("datetime64[s]")
                  + secs(np.full(n, 10 * 3600)))
    reopen_ts = notify1_ts + days_td(rng.uniform(.5, 2, n))

    add(np.ones(n, bool), recv, "Received")
    add(ack_ts < as_of, ack_ts, "Acknowledged")
    add(has_pc, issue_ts, "Provisional credit issued")
    add(reopened, inv1_ts, "Investigation complete")
    add(reopened, r1_ts, "Resolved")
    add(reopened, notify1_ts, "Customer notified")
    add(reopened, reopen_ts, "Reopened")
    add(resolved, inv_ts, "Investigation complete")
    add(resolved, end_ts, "Resolved")
    add(withdrawn, end_ts, "Withdrawn")
    add(resolved & (notify_ts < as_of), notify_ts, "Customer notified")

    ev_claim = np.concatenate(ev_claim)
    ev_ts = np.concatenate(ev_ts)
    order = np.lexsort((ev_ts, ev_claim))
    claim_events = pd.DataFrame({
        "claim_id": claim_ids[ev_claim[order]],
        "event_ts": ev_ts[order],
        "event": np.concatenate(ev_name)[order].astype(str),
    })

    # ------------------------------------------------------------------ chargebacks
    # Filed with the card network on ~40% of customer-favor unauthorized / merchant
    # claims, one row per disputed transaction, inside the 120-day filing window.
    filed_ts = recv + days_td(rng.uniform(2, 12, n))
    cb = (outcome == 0) & (reason < 2) & (rng.random(n) < .40) & (filed_ts < as_of)
    decided_ts = filed_ts + days_td(rng.uniform(30, 75, n))
    decided = decided_ts < as_of
    won = rng.random(n) < .60
    cb_outcome = np.where(~decided, "Pending", np.where(won, "Won", "Lost"))
    rows = cb[t_claim]
    tc = t_claim[rows]
    chargebacks = pd.DataFrame({
        "claim_id": claim_ids[tc],
        "filed_ts": filed_ts[tc],
        "amount": t_cents[rows] / 100,
        "network_outcome": cb_outcome[tc],
        "outcome_ts": np.where(decided, decided_ts, nat)[tc],
        "recovered_amount": np.where(cb_outcome[tc] == "Won", t_cents[rows], 0) / 100,
    })

    # ------------------------------------------------------------------ write
    tables = {
        "accounts": accounts,
        "card_volume_daily": card_volume,
        "claims": claims,
        "claim_transactions": claim_txns,
        "claim_events": claim_events,
        "provisional_credits": provisional_credits,
        "chargebacks": chargebacks,
    }
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False, compression="zstd")
    meta = {
        "issuer": ISSUER,
        "seed": a.seed,
        "start": str(start),
        "as_of": str(as_of_d),
        "accounts": a.accounts,
        "claims": a.claims,
        "rows": {k: int(len(v)) for k, v in tables.items()},
    }
    (out / "_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    total = 0
    for name, df in tables.items():
        size = (out / f"{name}.parquet").stat().st_size
        total += size
        print(f"{name:<22} {len(df):>9,} rows  {size / 1e6:6.2f} MB")
    print(f"{'total':<22} {'':>14} {total / 1e6:6.2f} MB  ->  {out}/")


if __name__ == "__main__":
    main()
