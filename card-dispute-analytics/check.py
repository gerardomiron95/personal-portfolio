#!/usr/bin/env python3
"""Acceptance checks: data integrity, reproducibility and aggregate reconciliation.

Run after `make data build`. Exits non-zero if any check fails.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

RAW, AGG, JSON = Path("data/raw"), Path("data/agg"), Path("data/data.json")
DEFAULT_ROWS = {"accounts": 150_000, "claims": 80_000, "claim_transactions": 125_000,
                "claim_events": 420_000, "provisional_credits": 38_000, "chargebacks": 30_000}
results: list[tuple[bool, str]] = []


def check(ok, label: str) -> None:
    results.append((bool(ok), label))


def digest(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.glob("*")) if p.suffix in (".parquet", ".json")}


def main() -> None:
    meta = json.loads((RAW / "_meta.json").read_text())
    as_of = pd.Timestamp(meta["as_of"])
    t = {n: pd.read_parquet(RAW / f"{n}.parquet") for n in meta["rows"]}

    # ---- sizes and reproducibility
    if meta["claims"] == 80_000 and meta["accounts"] == 150_000:
        for name, target in DEFAULT_ROWS.items():
            n = len(t[name])
            check(abs(n / target - 1) <= .05, f"{name}: {n:,} rows within ±5% of {target:,}")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "generate_raw.py", "--out", tmp, "--seed", str(meta["seed"]),
                        "--start", meta["start"], "--end", meta["as_of"], "--accounts", str(meta["accounts"]),
                        "--claims", str(meta["claims"])], check=True, capture_output=True)
        check(digest(Path(tmp)) == digest(RAW), "same seed reproduces byte-identical files")

    # ---- referential integrity
    claim_ids = set(t["claims"]["claim_id"])
    check(t["claims"]["account_id"].isin(set(t["accounts"]["account_id"])).all(), "every claim's account exists")
    for child in ["claim_transactions", "claim_events", "provisional_credits", "chargebacks"]:
        check(t[child]["claim_id"].isin(claim_ids).all(), f"every {child} claim_id exists in claims")
    c = t["claims"].set_index("claim_id")
    ct_sum = t["claim_transactions"].groupby("claim_id")["amount"].sum().round(2)
    check(np.allclose(c.loc[ct_sum.index, "claimed_amount"], ct_sum), "claimed_amount = sum of its transactions")

    # ---- timestamps
    ts_cols = [("claims", "received_ts"), ("claims", "resolved_ts"), ("claim_events", "event_ts"),
               ("provisional_credits", "issued_ts"), ("provisional_credits", "final_ts"),
               ("chargebacks", "filed_ts"), ("chargebacks", "outcome_ts")]
    check(all((t[n][col].dropna() < as_of).all() for n, col in ts_cols), "no timestamps on or after the as-of date")
    check((c["resolved_ts"].dropna() > c.loc[c["resolved_ts"].notna(), "received_ts"]).all(), "received < resolved")
    pc = t["provisional_credits"].join(c, on="claim_id")
    check((pc["issued_ts"] > pc["received_ts"]).all(), "received < provisional credit")
    check(((pc["issued_ts"] < pc["resolved_ts"]) | pc["resolved_ts"].isna()).all(), "provisional credit < resolved")
    ev = t["claim_events"].join(c[["resolved_ts"]], on="claim_id")
    notified = ev[ev["event"] == "Customer notified"]
    last_notice = notified.groupby("claim_id")["event_ts"].max()
    res_at = c.loc[last_notice.index, "resolved_ts"]
    # A notice is due within 3 business days; resolutions in the last week may still be waiting for one.
    due = pd.to_datetime(np.busday_offset(res_at.to_numpy().astype("datetime64[D]"), 3, roll="forward"))
    settled = due < as_of
    check((last_notice[settled] > res_at[settled]).all(), "final notice comes after final resolution")
    resolved_c = c[c["status"].str.startswith("Resolved")]
    due_all = pd.to_datetime(np.busday_offset(resolved_c["resolved_ts"].to_numpy().astype("datetime64[D]"), 3,
                                              roll="forward")) + pd.Timedelta(days=1)
    notice_ok = last_notice.reindex(resolved_c.index)
    check((notice_ok[due_all <= as_of] <= due_all[due_all <= as_of]).all(),
          "customer notified within 3 business days of resolution")
    recv_ev = ev[ev["event"] == "Received"].set_index("claim_id")["event_ts"]
    check((recv_ev == c.loc[recv_ev.index, "received_ts"]).all() and len(recv_ev) == len(c),
          "one Received event per claim, matching received_ts")
    first = t["claim_events"].groupby("claim_id")["event_ts"].min()
    check((first == c.loc[first.index, "received_ts"]).all(), "no event precedes Received")
    cb = t["chargebacks"].merge(t["claim_transactions"], on=["claim_id", "amount"], how="left")
    check(((cb["filed_ts"] - pd.to_datetime(cb["txn_date"])).dt.days <= 120).all(),
          "chargebacks filed within 120 days of the transaction")

    # ---- deadline logic
    check(set(c["deadline_days"]) == {45, 90}, "deadline_days is 45 or 90")
    recv_d = c["received_ts"].to_numpy().astype("datetime64[D]")
    bd10 = np.busday_offset(recv_d, 10, roll="forward")
    check(np.is_busday(bd10).all(), "business day 10 never lands on a weekend")
    issued_on = pc["issued_ts"].to_numpy().astype("datetime64[D]")
    check(np.is_busday(issued_on).all(), "provisional credits are issued on business days")

    # ---- aggregates reconcile to raw
    fm = pd.read_csv(AGG / "funnel_month.csv")
    fw = pd.read_csv(AGG / "funnel_week.csv")
    for name, f in [("month", fm), ("week", fw)]:
        check(f["claims"].sum() == len(c), f"funnel_{name}: SUM(claims) = rows in claims")
        check(f["claim_transactions"].sum() == len(t["claim_transactions"]),
              f"funnel_{name}: SUM(claim_transactions) = rows in claim_transactions")
        check(f["chargebacks_filed_txns"].sum() == len(t["chargebacks"]),
              f"funnel_{name}: SUM(chargebacks_filed_txns) = rows in chargebacks")
        check(f["pc_issued"].sum() == len(t["provisional_credits"]),
              f"funnel_{name}: SUM(pc_issued) = rows in provisional_credits")
        check(f["card_transactions"].sum() == t["card_volume_daily"]["card_transactions"].sum(),
              f"funnel_{name}: SUM(card_transactions) matches card_volume_daily")
        check(np.isclose(f["recovered_amount"].sum(), t["chargebacks"]["recovered_amount"].sum()),
              f"funnel_{name}: SUM(recovered_amount) matches chargebacks")
    data = json.loads(JSON.read_text())
    bad = []
    for r in data["rates"]:
        for f in (fm, fw):
            expect = np.where(f[r["den"]] > 0, f[r["num"]] / f[r["den"]].where(f[r["den"]] > 0, 1), np.nan)
            if not np.allclose(f[r["id"]], expect, equal_nan=True):
                bad.append(r["id"])
    check(not bad, "every rate = numerator / denominator" + (f" (bad: {bad})" if bad else ""))
    check(len(data["funnel_month"]) == len(fm) and len(data["funnel_week"]) == len(fw),
          "data.json matches the aggregate CSVs")

    # ---- maturation
    mat = pd.read_csv(AGG / "resolution_maturation.csv")
    st = pd.read_csv(AGG / "resolution_status.csv")
    tot = mat[mat["reason_category"] == "Total"].sort_values("cohort_month")
    thr = data["maturity_threshold"]
    check((tot["resolved_rate"].iloc[-2:] < thr).all(), "current and previous month are immature")
    long = mat.melt(id_vars=["cohort_month", "reason_category"],
                    value_vars=[f"M{i}_count" for i in range(7)], var_name="b", value_name="n").dropna()
    long["bucket"] = long["b"].str[1].astype(int)
    sums = st.groupby(["cohort_month", "reason_category", "bucket"])["n"].sum()
    merged = long.set_index(["cohort_month", "reason_category", "bucket"])["n"]
    check((sums.reindex(merged.index).fillna(0) == merged).all(), "heatmap breakdowns sum to their cells")
    reasons = mat[mat["reason_category"] != "Total"].groupby("cohort_month")["claims"].sum()
    check((reasons == tot.set_index("cohort_month")["claims"]).all(), "reason cohorts sum to Total")

    for ok, label in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
    failed = sum(not ok for ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
