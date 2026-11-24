# Card Dispute Operations Analytics

A data pipeline and dashboard that follows card disputes from intake to chargeback
recovery, measured against the public Reg E error-resolution timelines.

> **About this data:** Northwind Bank is not a real bank, and every account, claim and
> dollar figure in this project was generated for it. No real people, card numbers,
> merchants or business results appear anywhere: merchant names are labels like
> `Merchant 0412`, and card numbers are never created. Metric definitions are generic
> industry concepts documented in this repo; none come from any employer's systems,
> definitions, thresholds or reports.

## What it shows

| Tab | Question it answers |
|---|---|
| **Rate trends** | Are claim volume, on-time resolution, provisional-credit timeliness and chargeback wins moving the right way? Each chart has a dashed line at Northwind's monthly target, and an option to hide immature months. |
| **Claims funnel** | How many claims and disputed transactions moved through intake, provisional credit, resolution and chargebacks each month or week? Rates are shaded green when they meet Northwind's monthly target and red when they miss it. |
| **Dollars funnel** | The same flow in dollars: credited to customers, recovered from merchants' banks, written off. |
| **Resolution timing** | How quickly does each month's group of claims close? A heatmap by reason, with outcome breakdowns on hover, plus a year-over-year claim-rate chart. |
| **Dictionary** | Every column, its formula, and a plain-English definition. |

## Public rules the data follows (simplified for a demo)

| Rule | Value used | Source |
|---|---|---|
| Provisional credit if not resolved within | 10 business days of notice (weekends skipped) | Reg E, 12 CFR 1005.11(c) |
| Resolution deadline (standard) | 45 days | Reg E, 12 CFR 1005.11(c) |
| Resolution deadline (extended) | 90 days for new accounts, point-of-sale and foreign transactions | Reg E, 12 CFR 1005.11(c)(3) |
| Cardholder notice after resolution | 3 business days | Reg E, 12 CFR 1005.11(d) |
| Chargeback filing window | 120 days from the transaction | Generic card-network rule |

## How it's built

```
generate_raw.py       seeded generator        -> data/raw/*.parquet   (7 row-level tables)
build_aggregates.py   pandas aggregation      -> data/agg/*.csv + data/data.json
web/                  static page, Chart.js 4 -> reads data/data.json only
check.py              42 acceptance checks (integrity, reproducibility, reconciliation)
```

### Raw data (`data/raw/`, Parquet, about 8 MB)

| Table | Rows | Grain |
|---|---|---|
| `accounts` | 150,000 | one card account |
| `card_volume_daily` | ~5,500 | day × merchant category (the claim-rate denominator) |
| `claims` | 80,000 | one dispute claim |
| `claim_transactions` | ~123,000 | one disputed transaction |
| `claim_events` | ~418,000 | one status change |
| `provisional_credits` | ~38,000 | one provisional credit |
| `chargebacks` | ~30,000 | one chargeback filed with the network |

The full dataset is committed as Parquet (compressed and columnar) so it stays small
enough for git. Read it with pandas, Polars or DuckDB:

```python
import pandas as pd
claims = pd.read_parquet("data/raw/claims.parquet")
```

```sql
-- DuckDB
SELECT reason_category, COUNT(*) FROM 'data/raw/claims.parquet' GROUP BY 1;
```

### Modeling choices

- **Seasonality and growth:** card volume follows a weekday pattern, a holiday peak
  (Nov–Dec +35%), a February dip and ~6% yearly growth. Claim rates run higher Nov–Jan.
- **Immature recent months:** claims received recently are still open, so their rates
  aren't final. The dashboard marks a month as mature once 98% of its claims have closed.
- **Monthly targets are fixed goals** set per rate in `build_aggregates.py`, each with a
  direction (higher or lower is better). They drive the chart target lines and table shading.
- **Reproducible:** the same flags and seed produce byte-identical files (`check.py`
  verifies this).

## Run it

Requires Python 3.9+.

```bash
make setup    # create .venv with numpy, pandas, pyarrow
make data     # regenerate data/raw/ (optional; it's committed)
make build    # data/raw -> data/agg + data/data.json
make check    # run the acceptance checks
make serve    # then open http://localhost:8000/web/
```

Generator flags: `--accounts`, `--claims`, `--start`, `--end` (as-of date), `--seed`.
For a larger run: `make data ARGS="--claims 400000"`.

The data starts on Jan 1 of the previous year, so the year-over-year chart shows two
years. Pass `--start` two years back for three.
