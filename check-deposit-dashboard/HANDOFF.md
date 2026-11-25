# Handoff: mobile check deposit flow dashboard (portfolio project)

A personal portfolio piece: a dashboard that follows every mobile check deposit
from receipt through vendor screening, manual review queues, the reviewer's
decision, and whether a deposited check was later returned.

**Everything here is fictional.** Build it from this document only. Do not copy
code, data, names, IDs, colors or wording from any employer system.

---

## 1. Goal

- One static web page (HTML + CSS + JS) that reads a set of CSV files.
- A Python script that generates the CSVs: fake, seeded, reproducible.
- Hostable on GitHub Pages. No backend, no accounts, no API keys.

---

## 2. De-identification rules (non-negotiable)

| Never include | Use instead |
|---|---|
| Any real company, product, bank, vendor or processor name | "Northwind Bank" (the portfolio's fictional bank), "the deposit vendor", "the core banking platform" |
| Real people, agent or analyst names, usernames, emails | Generated fake names (Python `faker`, fixed seed) |
| Real IDs: receipt numbers, account numbers, routing numbers, spreadsheet or script IDs, event-type codes | Generated IDs, e.g. `R-000123`. Routing numbers as `Routing 9XXXXXXXX` from a random 9-digit generator |
| Real figures: monthly volumes, rates, medians, baselines | New ranges (section 4); never tune the data to match a real dashboard |
| Real bank names for "returning bank" | Invented names, e.g. "Harbor State Bank", "Pinecrest Credit Union" |
| Employer brand colors or fonts | The neutral palette in section 6 |
| Internal terms, ticket keys, team names | Plain descriptions |

Allowed: industry-standard return reasons (NSF, Stop Payment, Closed Account,
etc.) and US federal holidays. These are public and not company-specific.

Before publishing, grep the repo for any employer name, vendor name, or real ID
pattern. It should return nothing.

---

## 3. The flow being modeled

```
Checks received
├── Auto-denied by vendor screening        (with reason → sub-reason)
└── Approved for review
    ├── Fast-track queue    ──┬─ Deposited
    │                         └─ Rejected
    ├── Standard review     ──┬─ Deposited
    │                         └─ Rejected
    ├── High-risk review    ──┬─ Deposited
    │                         └─ Rejected
    └── Still in queue      (only if undecided at data cut-off)

Deposited (total) ─┬─ Deposited, not returned
                   └─ Returned after deposit   (counted in the deposit month)
Rejected (total)  = sum of the three queue Rejected boxes
```

Every check also carries a member segment: `Direct deposit`, `No direct deposit`
or `Unknown`, used as a filter.

---

## 4. Dummy data

### 4.1 Size

Generate about 9–10 months of data (e.g. February through November of a
recent year) so the output CSVs land near these row counts:

| File | Approx. rows | Grain |
|---|---|---|
| `checks.csv` (raw) | 35,000–45,000 | one row per check |
| `node_counts.csv` (aggregated) | 30,000–36,000 | date × segment bucket × node or breakdown key |
| `timing_rows.csv` (aggregated) | 25,000–30,000 | one row per decided check that has timing |
| `reviewer_rejections.csv` (aggregated) | 800–1,000 | review week × reviewer × reason × queue |
| `returns.csv` (raw) | 600–900 | one row per returned check |

### 4.2 Rates and ranges (invented; vary by month with noise)

| Item | Range |
|---|---|
| Checks received per month | 2,800–6,500, weekday-heavy, about half the volume on weekends |
| Auto-denied | 18–25% of received |
| Queue split of approved | fast-track 55–65%, standard 28–38%, high-risk 3–6% |
| Deposit rate | fast-track 90–96%, standard 72–85%, high-risk 75–88% |
| Returned after deposit | 1.5–4% of deposited |
| Segment mix | Direct deposit 80–90%, No direct deposit 3–6%, Unknown the rest (all auto-denied checks are Unknown) |
| Still in queue | 0, except up to 2% for the last 3 days before cut-off |
| Amount per check | log-normal, median about $350, capped at $10,000 |

### 4.3 Timing

Business days = weekdays, excluding US federal holidays.

- **Days to funds available (deposited):** business days from receipt to funds
  available. Use a hold policy: same day, 2 days or 4–5 days, with the share
  depending on queue (fast-track mostly 0–2, standard mostly 4–5, high-risk
  mixed).
- **Days to rejection:** 0–2 business days.
- **Days to return:** 2–15 business days after funds available.
- Checks received in the last few days before cut-off whose hold hasn't ended
  have no timing row yet. Keep this behavior; it's realistic.

### 4.4 Breakdowns

- **Auto-deny reasons:** 4–6 invented vendor reasons (e.g. "Duplicate item
  detected", "Daily item limit exceeded"), each with 2–5 sub-reasons.
- **Rejection reasons** (review decisions): 10–14, e.g. Endorsement missing,
  Image unreadable, Amount mismatch, Post-dated, Stale-dated, Altered item.
- **Reviewers:** 8–12 fake names. Each review week, a few reviewers handle most
  rejections (skewed, Pareto-like). The queue is known per rejection.
- **Returns:** reason from a standard list (NSF, Uncollected funds hold, Stop
  payment, Closed account, Unable to locate account, Refer to maker, Duplicate
  presentment, Altered/fictitious item, Signature missing, Forgery), returning
  bank from 30–60 invented names, the analyst who entered the reason, and the
  assigned analyst (4–6 fake names). About 3% of returns have no reason
  recorded.

### 4.5 CSV schemas

`checks.csv`

```
check_id, received_date, segment, amount, auto_denied (0/1), auto_deny_reason,
auto_deny_sub_reason, queue (fast_track|standard|high_risk|in_queue|''),
outcome (deposited|rejected|in_queue|''), reject_reason, reviewer,
funds_available_date, decision_date
```

`returns.csv`

```
check_id, deposit_date, return_date, return_amount, return_reason,
returning_bank, reason_entered_by, case_assigned_to
```

`node_counts.csv` (what the page reads for counts)

```
date, month, segment (all|direct_deposit|no_direct_deposit|unknown),
node_id, label, parent, kind, key, count, amount
```

- `kind`: `flow` (a flowchart node), `queue_outcome`, `auto_deny_reason`,
  `auto_deny_sub`, `reject_reason`, `return_combo`.
- `return_combo` key: `reason||bank||entered_by||assigned_to`, so the page can
  cross-filter.
- Every row is written once per segment **and** once under `all`. Never sum
  across segment buckets.

`timing_rows.csv`

```
month, segment, queue, decision (deposited|rejected), days_to_decision, days_to_return
```

`reviewer_rejections.csv`

```
week_start, week_end, reviewer, reason, queue, count
```

### 4.6 Generator requirements

- `python generate_data.py --seed 42 --out data/`
- Uses `numpy` + `faker` with a fixed seed; the same seed gives identical files.
- Writes the raw files, then aggregates them into the three files the page
  reads. Keep aggregation in Python so the page only filters and sums.
- Prints a summary: row counts per file and per-month totals.
- Asserts the invariants in section 7 before writing.

---

## 5. The page

### 5.1 Layout

1. **Header:** title "Mobile check deposit flow", subtitle with data range and a
   "Sample data" tag.
2. **Tabs:** Overview, plus one tab per month.
3. **Controls:** Count / Amount ($) toggle; segment filter (All / Direct deposit
   / No direct deposit / Unknown). Overview also gets a From/To date range.
4. **Scorecards:** Checks received, Auto-denied, Approved for review, Deposited
   with no returns, Rejected, Still in queue, Returned after deposit. Each shows
   a share of its base; month tabs add month-over-month change in percentage
   points (for Auto-denied, Rejected and Returned, down is good).
5. **Flowchart:** an SVG in the section 3 shape.
6. **Auto-deny reasons:** a sorted horizontal bar chart; click a bar for its
   sub-reasons.
7. **Overview only:** trend charts by month or week: volume, outcome mix
   (deposited vs rejected vs auto-denied share), auto-deny reasons over time.

### 5.2 Flowchart behavior (differs from the original on purpose)

- **Fully open on load:** every node visible at once. No expand/collapse
  buttons.
- **No baseline flags:** no thresholds, warning icons, red outlines or alert
  banner.
- Each box shows the label, the value (count or $), its share of the parent, and
  a median business-days line on decision boxes and on Returned after deposit.
- A short note above the chart says what the medians measure: receipt to funds
  available or rejection, and deposit to return.

### 5.3 Drill-downs (kept)

A small ▾ button at the bottom-left of these nodes opens a panel under the
chart. Only one panel is open at a time; clicking the same button again closes
it.

| Node | Panel |
|---|---|
| Rejected (total) | Rejections by reviewer: weekly tabs; reviewers and their volume on the left (click one to filter), rejection reasons on the right |
| Each queue | Two tabs: **Rejections by reviewer** (same layout, that queue only) and **Days to deposit** (column chart of business days to funds available, deposited checks, 0…10+, share labels, plus deposits / median / 90th percentile / share within 2 days) |
| Returned after deposit | Tabs for analyst who entered the reason / assigned analyst; analysts on the left, return reasons on the right; click a reason to see its banks, with a Back button |

### 5.4 Tech

- Plain HTML/CSS/JS. Load CSVs with `fetch` and parse with Papa Parse (CDN,
  pinned version).
- Charts: Chart.js (pinned version) or hand-built SVG. The flowchart is
  hand-built SVG.
- Everything is computed in the browser from the CSVs: filter by tab, date
  range and segment, then sum. Medians are recomputed from `timing_rows.csv`
  for each selection; never average medians.
- `fetch` doesn't work from `file://`. Serve locally with
  `python -m http.server`, and deploy to GitHub Pages.
- Make it responsive: the flowchart scrolls horizontally inside its card on
  small screens.

---

## 6. Visual style (neutral, not any employer's brand)

> **Update:** the page now follows the Card Dispute Operations dashboard's palette and components
> (green primary `#1e6b4f`, the Northwind Bank logo and wordmark above the title with a "Portfolio demo"
> subtitle, controls above the tabs), so the portfolio's dashboards match. Still not any employer's brand.
> The colors below were the first draft. The data now starts January 1, with monthly volume of
> 2,800–3,800 checks so the row counts in 4.1 still hold over the longer window.
> The Overview tab (5.1 items 2, 3 and 7) is switched off for now with `SHOW_OVERVIEW` in `app.js`:
> the page shows only the month tabs and opens on the latest month.

- Font: Inter (Google Fonts), falling back to the system sans-serif.
- Colors:
  - Ink `#1F2933`, muted `#52606D`, background `#F7F8FA`, card `#FFFFFF`,
    border `#E4E7EB`.
  - Primary `#2F6FED` (bars, active toggles), positive `#2E9D6A`, negative
    `#D64545`, neutral `#E3A008`.
  - Flowchart fills: received gray, auto-denied orange, approved blue, queues
    violet, deposited green, rejected red, not-returned teal.
- Sentence case everywhere. Terse labels. No pie or donut charts: use sorted
  horizontal bars for part-to-whole, with the share in the label.

---

## 7. Checks before calling it done

Data invariants, asserted by the generator for every month and segment:

- received = auto-denied + approved
- approved = fast-track + standard + high-risk + still in queue
- approved = deposited + rejected + still in queue
- deposited total = sum of the queue deposited boxes; same for rejected
- returned ≤ deposited; the `return_combo` rows sum to returned
- the `segment = all` rows equal the sum of the three segments
- `reviewer_rejections.csv` contains only rejected checks

Page checks:

- The first and last month's totals from the generator summary match the page's
  scorecards exactly.
- Every drill-down opens, filters and closes with no console errors.
- The Days to deposit bars, as shares, match a direct count from
  `timing_rows.csv`.
- Works at phone width.
- The de-identification grep from section 2 returns nothing.

---

## 8. Suggested repo layout

```
check-deposit-dashboard/
├── README.md            what it is, "all data is synthetic", how to run
├── generate_data.py
├── requirements.txt     numpy, faker
├── data/                generated CSVs (committed, so Pages works)
├── index.html
├── app.js
└── styles.css
```

README talking points for the portfolio:

- The problem: following each deposit end to end across systems that don't
  share a key.
- Two-speed design: heavy aggregation offline, a light page that only filters
  and sums.
- Business-day timing with a holiday calendar, and medians recomputed per
  selection.
- Drill-downs that keep context: one open at a time, cross-filtering.
- All data is synthetic and seeded.
