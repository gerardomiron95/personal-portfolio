#!/usr/bin/env python3
"""Build the dashboard's aggregate tables from the raw Parquet files.

data/raw/*.parquet  ->  data/agg/*.csv  +  data/data.json

Every table is at its final grain; the web page never touches raw rows.
Rates are stored as ratios next to their numerator and denominator columns, and
each rate carries Northwind's fixed monthly target.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

MATURITY_THRESHOLD = 0.98
REASONS = ["Unauthorized", "Merchant dispute", "Processing error"]
OUTCOME_LABEL = {
    "Resolved - customer win": "Customer wins",
    "Resolved - no error found": "No error found",
    "Withdrawn": "Claims withdrawn",
}

# --------------------------------------------------------------------------- metric catalogue
# Count metrics: each gets a claim count (<name>), a transaction count (<txns>) and
# a dollar twin (<amount>). Definitions feed dictionary.csv and the page tooltips.
COUNT_METRICS = [
    # name, section, txns column, amount column, label, methodology, plain English
    ("claims", "Intake", "claim_transactions", "claimed_amount", "Claims received",
     "COUNT(claims) by received date; transactions = COUNT(claim_transactions); $ = SUM(claimed_amount)",
     "Dispute claims customers opened in the period."),
    ("open_claims", "Intake", "open_claims_txns", "open_claims_amount", "Open claims",
     "Claims with current status Open",
     "Claims from this period that are not resolved yet."),
    ("claims_withdrawn", "Intake", "claims_withdrawn_txns", "claims_withdrawn_amount", "Claims withdrawn",
     "Claims with current status Withdrawn",
     "Claims the customer withdrew before a decision."),
    ("pc_due", "Provisional credit", "pc_due_txns", "pc_due_amount", "Provisional credit due",
     "Claims still open at the end of business day 10 after notice (weekends skipped), counted once day 10 has passed",
     "Claims that ran past 10 business days, so Reg E requires a temporary credit."),
    ("pc_issued", "Provisional credit", "pc_issued_txns", "pc_issued_amount", "Provisional credits issued",
     "Claims with a row in provisional_credits; $ = SUM(provisional credit amount)",
     "Claims where the customer received a temporary credit."),
    ("pc_within_10bd", "Provisional credit", "pc_within_10bd_txns", "pc_within_10bd_amount", "Credited by day 10",
     "Claims due a provisional credit whose credit was issued by the end of business day 10",
     "Temporary credits that went out on time."),
    ("pc_kept_by_customer", "Provisional credit", "pc_kept_by_customer_txns", "pc_kept_by_customer_amount",
     "Provisional credits kept by customer", "Provisional credits with final_status = Kept by customer",
     "Temporary credits the customer keeps because the claim went their way."),
    ("pc_reversed", "Provisional credit", "pc_reversed_txns", "pc_reversed_amount", "Reversed",
     "Provisional credits with final_status = Reversed",
     "Temporary credits taken back because no error was found or the claim was withdrawn."),
    ("pc_finalized", "Provisional credit", "pc_finalized_txns", "pc_finalized_amount", "Credit finalized",
     "pc_kept_by_customer + pc_reversed",
     "Temporary credits with a final decision."),
    ("resolved_claims", "Resolution", "resolved_claims_txns", "resolved_claims_amount", "Resolved",
     "Claims with status Resolved - customer win or Resolved - no error found (withdrawals excluded)",
     "Claims that reached a decision."),
    ("customer_wins", "Resolution", "customer_wins_txns", "customer_wins_amount",
     "Customer wins", "Claims with status Resolved - customer win",
     "Claims decided in the customer's favor."),
    ("resolved_no_error", "Resolution", "resolved_no_error_txns", "resolved_no_error_amount", "No error found",
     "Claims with status Resolved - no error found",
     "Claims where the investigation found no error."),
    ("resolved_within_deadline", "Resolution", "resolved_within_deadline_txns", "resolved_within_deadline_amount",
     "Resolved on time", "Resolved claims where resolved_ts - received_ts <= deadline_days (45 or 90 calendar days)",
     "Decisions reached inside the Reg E deadline."),
    ("chargebacks_filed", "Chargebacks", "chargebacks_filed_txns", "chargebacks_filed_amount", "Chargebacks filed",
     "Claims with at least one chargeback; transactions = chargeback rows; $ = SUM(chargeback amount)",
     "Claims the bank sent back to the merchant's bank through the card network."),
    ("chargebacks_decided", "Chargebacks", "chargebacks_decided_txns", "chargebacks_decided_amount",
     "Chargebacks decided", "Chargebacks with network_outcome Won or Lost",
     "Chargebacks the network has ruled on."),
    ("chargebacks_won", "Chargebacks", "chargebacks_won_txns", "chargebacks_won_amount", "Chargebacks won",
     "Chargebacks with network_outcome Won",
     "Chargebacks where the money came back from the merchant's bank."),
    ("written_off_claims", "Losses", "written_off_claims_txns", "written_off_claims_amount", "Claims with a loss",
     "Customer-win claims with no pending chargeback and recovered < claimed",
     "Claims where the bank absorbed at least part of the credit."),
]

EXTRA_COLUMNS = [
    ("card_transactions", "Intake", "SUM(card_volume_daily.card_transactions) for days in the period",
     "Every card transaction in the period: the denominator for the claim rate."),
    ("card_dollars", "Intake", "SUM(card_volume_daily.card_dollars) for days in the period",
     "Total card spending in the period."),
    ("credited_amount", "Losses", "SUM(claimed_amount) for customer-win claims",
     "Money permanently credited back to customers."),
    ("recovered_amount", "Losses", "SUM(chargebacks.recovered_amount)",
     "Money won back from merchants' banks through chargebacks."),
    ("written_off_amount", "Losses",
     "SUM(claimed_amount - recovered_amount) for customer-win claims with no pending chargeback",
     "Money the bank absorbed as a loss."),
]

# Rates: (id, label, numerator, denominator, direction, format, table, description, target)
# Targets are Northwind's fixed monthly goals. direction says which side of the target is good:
# "higher" = meet or beat it from above, "lower" = stay at or under it.
RATES = [
    ("claim_rate", "Claim rate", "claim_transactions", "card_transactions", "lower", "per10k", "counts",
     "Disputed transactions per 10,000 card transactions.", 0.0045),
    ("on_time_resolution_rate", "On-time resolution", "resolved_within_deadline", "resolved_claims", "higher", "pct",
     "counts", "Share of decisions reached inside the 45- or 90-day deadline.", 0.98),
    ("pc_timeliness_rate", "Provisional-credit timeliness", "pc_within_10bd", "pc_due", "higher", "pct",
     "counts", "Share of required temporary credits issued by business day 10.", 0.975),
    ("pc_rate", "Provisional-credit rate", "pc_issued", "claims", "lower", "pct", "counts",
     "Share of claims that received a temporary credit; lower means more claims resolved inside 10 business days.",
     0.49),
    ("pc_reversal_rate", "Provisional-credit reversal rate", "pc_reversed", "pc_finalized", "lower", "pct",
     "counts", "Share of finalized temporary credits that were taken back.", 0.28),
    ("customer_win_rate", "Customer win rate", "customer_wins", "resolved_claims", "lower", "pct",
     "counts", "Share of decisions that went the customer's way; a rise can signal fraud or merchant problems.",
     0.735),
    ("chargeback_rate", "Chargeback rate", "chargebacks_filed", "customer_wins", "higher", "pct",
     "counts", "Chargebacks filed per customer win.", 0.365),
    ("chargeback_win_rate", "Chargeback win rate", "chargebacks_won", "chargebacks_decided", "higher", "pct",
     "counts", "Share of decided chargebacks the bank won.", 0.60),
    ("withdrawal_rate", "Withdrawal rate", "claims_withdrawn", "claims", "lower", "pct", "counts",
     "Share of claims the customer withdrew.", 0.07),
    ("recovery_rate", "Recovery rate", "recovered_amount", "credited_amount", "higher", "pct", "dollars",
     "Share of money credited to customers that came back through chargebacks.", 0.22),
    ("loss_rate", "Loss rate", "written_off_claims", "customer_wins", "lower", "pct", "counts",
     "Share of customer wins where the bank absorbed at least part of the credit.", 0.78),
    ("write_off_rate", "Write-off rate", "written_off_amount", "claimed_amount", "lower", "pct", "dollars",
     "Share of disputed dollars the bank absorbed as a loss.", 0.53),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", default="data/raw")
    p.add_argument("--agg", default="data/agg")
    p.add_argument("--json", default="data/data.json")
    p.add_argument("--maturity-threshold", type=float, default=MATURITY_THRESHOLD)
    return p.parse_args()


def claim_frame(raw: Path, as_of: pd.Timestamp) -> pd.DataFrame:
    """One row per claim with every flag and amount the aggregates need."""
    c = pd.read_parquet(raw / "claims.parquet")
    ct = pd.read_parquet(raw / "claim_transactions.parquet")
    pc = pd.read_parquet(raw / "provisional_credits.parquet").set_index("claim_id")
    cb = pd.read_parquet(raw / "chargebacks.parquet")

    c["n_txns"] = c["claim_id"].map(ct.groupby("claim_id").size()).fillna(0).astype(int)
    c = c.join(pc[["issued_ts", "amount", "final_status"]].rename(columns={"amount": "pc_amount"}), on="claim_id")

    recv_d = c["received_ts"].to_numpy().astype("datetime64[D]")
    bd10_due = pd.to_datetime(np.busday_offset(recv_d, 10, roll="forward")) + pd.Timedelta(days=1)
    res = c["resolved_ts"]
    status = c["status"]

    f = pd.DataFrame(index=c.index)
    f["claims"] = True
    f["open_claims"] = status == "Open"
    f["claims_withdrawn"] = status == "Withdrawn"
    f["pc_due"] = (bd10_due <= as_of) & (res.isna() | (res > bd10_due))
    f["pc_issued"] = c["issued_ts"].notna()
    f["pc_within_10bd"] = f["pc_due"] & f["pc_issued"] & (c["issued_ts"] <= bd10_due)
    f["pc_kept_by_customer"] = c["final_status"] == "Kept by customer"
    f["pc_reversed"] = c["final_status"] == "Reversed"
    f["pc_finalized"] = f["pc_kept_by_customer"] | f["pc_reversed"]
    f["customer_wins"] = status == "Resolved - customer win"
    f["resolved_no_error"] = status == "Resolved - no error found"
    f["resolved_claims"] = f["customer_wins"] | f["resolved_no_error"]
    elapsed = (res - c["received_ts"]).dt.total_seconds() / 86_400
    f["resolved_within_deadline"] = f["resolved_claims"] & (elapsed <= c["deadline_days"])

    g = cb.assign(
        decided=cb["network_outcome"].isin(["Won", "Lost"]),
        won=cb["network_outcome"] == "Won",
        pending=cb["network_outcome"] == "Pending",
    )
    per = pd.DataFrame({
        "cb_rows": g.groupby("claim_id").size(),
        "cb_amount": g.groupby("claim_id")["amount"].sum(),
        "cb_decided_rows": g.groupby("claim_id")["decided"].sum(),
        "cb_decided_amount": g[g["decided"]].groupby("claim_id")["amount"].sum(),
        "cb_won_rows": g.groupby("claim_id")["won"].sum(),
        "cb_won_amount": g[g["won"]].groupby("claim_id")["amount"].sum(),
        "cb_pending": g.groupby("claim_id")["pending"].any(),
        "recovered": g.groupby("claim_id")["recovered_amount"].sum(),
    })
    c = c.join(per, on="claim_id")
    for col in ["cb_rows", "cb_amount", "cb_decided_rows", "cb_decided_amount", "cb_won_rows", "cb_won_amount",
                "recovered"]:
        c[col] = c[col].fillna(0)
    c["cb_pending"] = c["cb_pending"].astype("boolean").fillna(False).astype(bool)

    f["chargebacks_filed"] = c["cb_rows"] > 0
    f["chargebacks_decided"] = c["cb_decided_rows"] > 0
    f["chargebacks_won"] = c["cb_won_rows"] > 0
    loss_basis = f["customer_wins"] & ~c["cb_pending"]
    loss = np.where(loss_basis, (c["claimed_amount"] - c["recovered"]).round(2), 0.0)
    f["written_off_claims"] = loss > 0

    out = c[["claim_id", "received_ts", "resolved_ts", "reason_category", "status"]].copy()
    txns = {
        "chargebacks_filed": c["cb_rows"], "chargebacks_decided": c["cb_decided_rows"],
        "chargebacks_won": c["cb_won_rows"],
    }
    amounts = {
        "pc_issued": c["pc_amount"], "pc_within_10bd": c["pc_amount"], "pc_kept_by_customer": c["pc_amount"],
        "pc_reversed": c["pc_amount"], "pc_finalized": c["pc_amount"],
        "chargebacks_filed": c["cb_amount"], "chargebacks_decided": c["cb_decided_amount"],
        "chargebacks_won": c["cb_won_amount"],
    }
    for name, _, txn_col, amt_col, *_ in COUNT_METRICS:
        m = f[name].to_numpy()
        out[name] = m.astype(int)
        out[txn_col] = np.where(m, txns.get(name, c["n_txns"]), 0).astype(int)
        out[amt_col] = np.where(m, amounts.get(name, c["claimed_amount"]).fillna(0), 0.0)
    out["credited_amount"] = out["customer_wins_amount"]
    out["recovered_amount"] = c["recovered"]
    out["written_off_amount"] = loss
    return out


def period_key(ts: pd.Series, grain: str) -> pd.Series:
    if grain == "month":
        return ts.dt.to_period("M").dt.start_time
    return ts.dt.to_period("W-SUN").dt.start_time  # weeks start Monday


def funnel(c: pd.DataFrame, vol: pd.DataFrame, grain: str) -> pd.DataFrame:
    value_cols = [col for col in c.columns
                  if col not in ("claim_id", "received_ts", "resolved_ts", "reason_category", "status")]
    f = c[value_cols].groupby(period_key(c["received_ts"], grain).rename("period_start")).sum()
    v = vol.groupby(period_key(vol["date"], grain).rename("period_start"))[["card_transactions", "card_dollars"]].sum()
    f = v.join(f, how="outer").fillna(0)
    for col in f.columns:
        if col.endswith("amount") or col == "card_dollars":
            f[col] = f[col].round(2)
        else:
            f[col] = f[col].astype("int64")
    for rid, _, num, den, *_ in RATES:
        f[rid] = np.where(f[den] > 0, f[num] / f[den].where(f[den] > 0, 1), np.nan)
    f = f.reset_index()
    f["period_start"] = f["period_start"].dt.strftime("%Y-%m-%d")
    return f


def maturation(c: pd.DataFrame, last_day: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    cur = last_day.to_period("M")
    cohorts = pd.period_range(cur - 12, cur, freq="M")
    c = c.assign(
        cohort=c["received_ts"].dt.to_period("M"),
        bucket=np.where(
            c["status"] == "Open", -1,
            (c["resolved_ts"].dt.year * 12 + c["resolved_ts"].dt.month)
            - (c["received_ts"].dt.year * 12 + c["received_ts"].dt.month)),
        outcome=c["status"].map(OUTCOME_LABEL),
    )
    c = c[c["cohort"].isin(cohorts)]
    both = pd.concat([c, c.assign(reason_category="Total")])

    rows = []
    for cohort in cohorts:
        for reason in REASONS + ["Total"]:
            sub = both[(both["cohort"] == cohort) & (both["reason_category"] == reason)]
            n = len(sub)
            row = {"cohort_month": str(cohort), "reason_category": reason, "claims": n}
            resolved = 0
            for i in range(7):
                if cohort + i > cur:
                    row[f"M{i}_count"] = None
                else:
                    k = int((sub["bucket"] == i).sum())
                    row[f"M{i}_count"] = k
                    resolved += k
            for i in range(7):
                k = row[f"M{i}_count"]
                row[f"M{i}_rate"] = None if k is None or n == 0 else k / n
            row["resolved_rate"] = resolved / n if n else None
            rows.append(row)
    mat = pd.DataFrame(rows)
    count_cols = [f"M{i}_count" for i in range(7)]
    mat[count_cols] = mat[count_cols].astype("Int64")

    st = (both[both["bucket"].between(0, 6)]
          .groupby(["cohort", "reason_category", "bucket", "outcome"]).size().rename("n").reset_index())
    st["cohort"] = st["cohort"].astype(str)
    st = st.rename(columns={"cohort": "cohort_month"})
    return mat, st


def yoy(fm: pd.DataFrame, last_day: pd.Timestamp) -> pd.DataFrame:
    d = fm.copy()
    ps = pd.to_datetime(d["period_start"])
    d = d[(ps.dt.year >= last_day.year - 2) & (d["card_transactions"] > 0)]
    ps = pd.to_datetime(d["period_start"])
    latest = sorted(ps.unique())[-2:]
    return pd.DataFrame({
        "year": ps.dt.year.to_numpy(),
        "month_num": ps.dt.month.to_numpy(),
        "claim_rate": (d["claim_transactions"] / d["card_transactions"] * 1e4).round(4).to_numpy(),
        "is_incomplete": ps.isin(latest).to_numpy(),
    })


def dictionary(meta: dict, window_start: pd.Timestamp, last_day: pd.Timestamp, threshold: float) -> pd.DataFrame:
    rows = [
        ("Data window", "Scope", f"{meta['start']} to {last_day.date()} (as of {meta['as_of']})",
         "Demo data for Northwind Bank, generated for this portfolio project with a fixed seed."),
        ("Dashboard window", "Scope",
         f"Last 12 full months plus the current partial month: {window_start.date()} to {last_day.date()}",
         "Charts and tables open on this rolling window; tables can look back further."),
        ("Grain", "Scope", "Claims are assigned to the period (month, or week starting Monday) they were received",
         "A claim always counts in the period it came in, even if it was resolved later."),
        ("Reg E provisional credit", "Scope",
         "12 CFR 1005.11: credit if not resolved within 10 business days of notice (weekends skipped; holidays ignored)",
         "If a claim takes longer than 10 business days, the customer gets their money back temporarily."),
        ("Reg E resolution deadline", "Scope",
         "45 days standard; 90 days for new accounts (opened <= 30 days) and foreign / point-of-sale transactions",
         "The deadline for reaching a decision."),
        ("Cardholder notice", "Scope", "Within 3 business days of resolution",
         "Customers are told the outcome within 3 business days."),
        ("Chargeback window", "Scope", "Generic network rule: filed within 120 days of the transaction",
         "How long the bank has to dispute a charge with the merchant's bank."),
        ("Mature data", "Scope",
         f"A cohort month is mature when its Total resolved_rate >= {threshold:.0%}; a week is mature when every "
         "month it touches is mature; months older than the maturation table are mature",
         "Recent periods still have open claims, so their rates are not final yet."),
        ("Monthly targets", "Scope", "Fixed per rate (see each rate below); met = at or above a higher-is-better "
         "target, at or below a lower-is-better target",
         "Northwind's goal for each rate: the dashed line on the trend charts and the green / red table shading."),
        ("period_start", "Keys", "Month: first day of the month. Week: the Monday that starts the week",
         "The period a row covers."),
    ]
    for col, section, method, plain in EXTRA_COLUMNS:
        rows.append((col, section, method, plain))
    for name, section, txn_col, amt_col, label, method, plain in COUNT_METRICS:
        rows.append((name, section, method, plain))
        rows.append((txn_col, section, "Disputed transactions on the claims counted in " + name,
                     plain.rstrip(".") + ", counted by transaction."))
        rows.append((amt_col, section, "Dollar amount of the claims counted in " + name,
                     plain.rstrip(".") + ", in dollars."))
    for rid, label, num, den, direction, fmt, _, desc, target in RATES:
        better = {"higher": "Higher is better", "lower": "Lower is better"}[direction]
        shown = " Shown per 10,000 transactions." if fmt == "per10k" else ""
        goal = f"{target * 1e4:g} per 10,000" if fmt == "per10k" else f"{target:.1%}"
        sign = ">=" if direction == "higher" else "<="
        rows.append((rid, "Rates", f"{num} / {den}; monthly target {sign} {goal}",
                     f"{desc} {better}. Target: {'at least' if direction == 'higher' else 'at most'} {goal}.{shown}"))
    for col, method, plain in [
        ("cohort_month", "Month the claim was received (YYYY-MM)", "The group of claims a heatmap row follows."),
        ("M0_count … M6_count", "Claims resolved or withdrawn 0…6 calendar months after the received month; "
                                "blank when that month is in the future", "How many claims closed in each month."),
        ("M0_rate … M6_rate", "Mi_count / claims", "Share of the cohort that closed in each month."),
        ("resolved_rate", "SUM(M0..M6 counts) / claims", "Share of the cohort closed so far."),
    ]:
        rows.append((col, "Resolution timing", method, plain))
    return pd.DataFrame(rows, columns=["column", "section", "methodology", "plain_english"])


def records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for col in df.select_dtypes("float").columns:
        df[col] = df[col].round(8)
    return json.loads(df.to_json(orient="records"))


def main() -> None:
    a = parse_args()
    raw, agg = Path(a.raw), Path(a.agg)
    agg.mkdir(parents=True, exist_ok=True)
    meta = json.loads((raw / "_meta.json").read_text())
    as_of = pd.Timestamp(meta["as_of"])
    last_day = as_of - pd.Timedelta(days=1)
    window_start = (last_day.to_period("M") - 12).start_time

    c = claim_frame(raw, as_of)
    vol = pd.read_parquet(raw / "card_volume_daily.parquet")
    fm = funnel(c, vol, "month")
    fw = funnel(c, vol, "week")
    mat, st = maturation(c, last_day)
    yy = yoy(fm, last_day)
    dic = dictionary(meta, window_start, last_day, a.maturity_threshold)

    tables = {
        "funnel_month": fm, "funnel_week": fw, "resolution_maturation": mat,
        "resolution_status": st, "yoy": yy, "dictionary": dic,
    }
    for name, df in tables.items():
        df.to_csv(agg / f"{name}.csv", index=False)

    payload = {
        "issuer": meta["issuer"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": meta["as_of"],
        "data_start": meta["start"],
        "last_day": str(last_day.date()),
        "window_start": str(window_start.date()),
        "maturity_threshold": a.maturity_threshold,
        "rates": [dict(zip(["id", "label", "num", "den", "direction", "format", "table", "description", "target"], r))
                  for r in RATES],
        "labels": {name: label for name, _, _, _, label, *_ in COUNT_METRICS},
        **{name: records(df) for name, df in tables.items()},
    }
    Path(a.json).write_text(json.dumps(payload, separators=(",", ":")))
    for name, df in tables.items():
        print(f"{name:<24} {len(df):>5} rows")
    print(f"data.json {Path(a.json).stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
