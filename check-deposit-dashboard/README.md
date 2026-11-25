# Mobile check deposit flow

A portfolio dashboard that follows every mobile check deposit from receipt, through the
deposit vendor's screening and the manual review queues, to the reviewer's decision and
whether the deposited check was later returned.

**All data is synthetic and seeded.** Northwind Bank, its reviewers, analysts and returning
banks are invented, and every rate is drawn from made-up ranges. Nothing comes from a real
bank, vendor or employer system.

**Live:** https://gerardomiron95.github.io/personal-portfolio/check-deposit-dashboard/

## What's here

```
generate_data.py    seeded generator: raw checks and returns, then the aggregates the page reads
data/               generated CSVs (committed so GitHub Pages can serve them)
index.html          the page
app.js              loads the CSVs, filters by tab, date range and segment, and sums
styles.css          the portfolio's dashboard palette, responsive layout
HANDOFF.md          the build brief: flow, data ranges, page behavior and checks
```

| File | Grain | Read by the page |
|---|---|---|
| `checks.csv` | one row per check | no (raw) |
| `returns.csv` | one row per returned check | no (raw) |
| `node_counts.csv` | date × segment × flowchart node or breakdown key | yes |
| `timing_rows.csv` | one row per decided check with timing | yes |
| `reviewer_rejections.csv` | review week × reviewer × reason × queue | yes |

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python generate_data.py --seed 42 --out data/
python3 -m http.server 8000
```

Then open http://localhost:8000/. The page loads its CSVs with `fetch`, which doesn't work
from `file://`, so it needs a local server. The generator prints row counts and monthly
totals, and asserts the flow's invariants before it writes anything. The same seed always
gives byte-identical files.

## What it demonstrates

- **Following one deposit end to end.** Screening, review and returns are separate
  systems that don't share a key. The generator links them per check, so every check
  lands in exactly one path through the flowchart, and the totals reconcile:
  received = auto-denied + approved; approved = deposited + rejected + still in queue.
- **Two-speed design.** The heavy work (linking, business-day timing, aggregation) runs
  offline in Python. The page only filters and sums, so it stays fast with no backend.
- **Business-day timing.** Days to funds available, rejection and return count weekdays
  and skip US federal holidays (observed dates included). Checks whose hold hadn't ended
  by the cut-off have no timing yet, as in real data.
- **Medians recomputed per selection.** Every median comes from the individual check
  rows for the current tab, date range and segment. Medians are never averaged.
- **Drill-downs that keep context.** One panel opens at a time under the flowchart:
  rejections by reviewer and week, days to deposit per queue, and returns by analyst,
  reason and returning bank, each cross-filtering the others.
- **Every segment row is written twice,** once under its own segment and once under
  `all`, and the generator checks that `all` equals the sum of the three segments.
