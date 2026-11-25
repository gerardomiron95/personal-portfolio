# Handoff: Northwind Bank Banking Operations deck

A weekly operations review deck for a fictional neobank, built as a static HTML
page from synthetic data. This is a portfolio piece: everything in it is
invented, and nothing in it may reference a real employer, vendor, customer or
metric value.

Read this file end to end before changing the deck.

---

## 0. Ground rules

**Invented world.** The company is **Northwind Bank**, a fictional consumer
neobank. The team is **Banking Operations**. The image-capture vendor is
**Clearwave**. No other organisation is named anywhere: not in a slide, a
footer, a chart label or the speaker notes.

**No proprietary anything.** No real company's colours, logo, wordmark,
confidentiality footer, dashboard names, internal system names, queue names,
table names, metric definitions or figures. The Northwind Bank logo (a
north-pointing needle in a rounded tile) is invented. The footer reads
`Northwind Bank · Illustrative data` and nothing else. If you are unsure whether
a term or a number came from a real workplace, replace it.

**Every number comes from `data/`.** `figures.py` computes each figure from the
CSVs; `build_deck.py` only formats them. Titles and leads are written from the
computed results (which way a rate moved, which test passed), so nothing is
typed in. If a figure cannot be computed from the data, generate the data for
it or drop the claim.

**The audience is a hiring manager, not an executive.** Same discipline as a
real review deck, but the deck also makes its reasoning legible: windows
stated, denominators labelled, tests reported, small samples flagged.

---

## 1. Build

```bash
cd banking-operations-review
python3 generate_data.py --summary   # data/*.csv, fixed seed
python3 figures.py                   # optional: print every figure and the reconciliation checks
python3 build_deck.py                # index.html
```

Standard library only. `SEED` is fixed, so the output is identical on every
run. `build_deck.py` refuses to build if any reconciliation check fails (for
example, funnel outcomes not summing to volume).

| File | Grain | Feeds |
|---|---|---|
| `check_deposits.csv` | one row per check | funnel, capture device, targets, queue timing |
| `ach_deposits.csv` | one row per settled day | early-pay rate and days-early mix |
| `card_reissues.csv` | one row per reissued card | reason mix, repeat members |

**As-of date is 2026-10-14.** October is deliberately partial. The last two
days of `check_deposits.csv` carry about a quarter of normal volume; they are
detected as immature (under half the median daily volume), excluded, and the
exclusion is stated on the slides.

### What each source is built to show

- **Checks.** The deposited-and-kept rate runs near 77% for April to
  September, then rises in October, significantly against the same days of
  September. The headline cannot say why. Split by capture device, the rise is
  almost all Android, where image-quality auto-denials fall. The data records
  which captures improved, not why, so the deck stops short of a cause.
- **Queues.** Instant and Standard Review hold their shape; Enhanced Review
  shifts later in October. Its median barely moves, which is the point: only
  the distribution shows it.
- **ACH.** The early-pay rate rises above its eight-week range in the latest
  complete week while the days-early mix tilts toward two days early. The mix
  is a share of *early* deposits; the rate is a share of *all* deposits. A mix
  shift cannot move the rate.
- **Card reissues.** One reason (system-detected fraud) moves significantly
  against the same days of last month; the others do not, so each reason is
  tested rather than eyeballed. Repeat loss-driven members only appear over a
  12-month lookback.

---

## 2. Figures (`figures.py`)

**Checks**
- Deposited-and-kept rate = `Deposited AND returned_after_deposit = 'N'` ÷
  checks received, current month to the last mature day.
- Monthly rate for each complete month and the pooled average of those months
  (ratio of sums, never a mean of monthly rates).
- Like-for-like comparison: current window against the same elapsed days of
  the prior month. Two-proportion z-test and 95% CI for every funnel row.
  Pending is shown, not dropped. Return rate is a share of *deposited*.
- By capture device: the same comparison per device, image-quality
  auto-denials per device, and a split of the headline change into each
  device's contribution (its share of checks × its rate change) plus a
  device-mix residual. The pieces sum to the headline.
- Auto-deny reasons as a share of auto-denials.
- Days to decision per queue, last three months (the current one to the last
  mature day), with medians, counts and a chi-square test of shape against the
  prior month. Queue-months under 100 checks are flagged, not read.
- p-chart (3σ around the pooled rate) computed for the speaker notes only.

**ACH**
- Early-pay rate for the latest complete week against the prior eight
  complete weeks: reported against the range when outside it, the median when
  inside.
- Days-early mix as a share of early deposits, every bucket shown.

**Card reissues**
- Reason mix, month to date against the same elapsed days of the prior month,
  with a two-proportion test per reason.
- Loss-driven = Lost, Stolen, Fraud (member reported), Fraud (system
  detected), with the four counts wherever the group is named.
- Members with a loss-driven reissue this month, and every loss-driven card
  each has had in the trailing 12 months: distribution (1, 2, 3, 4–5, 6+),
  repeat share, and the share of the cohort's cards that repeats hold.

**Targets** (policy inputs, set at the top of `figures.py`): 82% deposited and
kept; auto-denied 8–10%; agent rejected 3–4%.

---

## 3. Slides

| # | id | What it carries |
|---|---|---|
| 1 | `title` | Centered title page: department, deck title, date |
| 2 | `checks-cover` | Section 1 cover: check deposits, three KPIs |
| 3 | `checks-funnel` | Monthly trend with the average line + like-for-like outcome table with tests |
| 4 | `checks-device` | The change split by capture device, with each device's contribution |
| 5 | `checks-target` | Current rates against target, auto-deny reasons |
| 6 | `checks-queues` | Days-to-decision distribution, three queues × three months |
| 7 | `ach-cover` | Section 2 cover: ACH early pay, three KPIs and both denominators |
| 8 | `ach-early` | Early-pay rate vs the eight-week range + days-early mix |
| 9 | `reissue-cover` | Section 3 cover: card reissues, three KPIs and the loss-driven definition |
| 10 | `reissue-mix` | Reason mix, same elapsed days, tested per reason |
| 11 | `reissue-repeat` | Loss-driven definition + repeat distribution |

Every section opens with a green cover slide (`section_cover` in
`build_deck.py`): department and section number, section name, one-line scope,
three computed numbers and an optional footnote.

Speaker notes sit under each slide in the preview. The funnel notes record
the p-chart that was tested and not used, with its actual result.

---

## 4. Visual system

Same greens as the portfolio site and the card dispute dashboard.

```
paper   #f4f7f5    card   #ffffff    line   #e0e6e2
ink     #1c2a24    muted  #5f6b64    body   #3d4a43
accent  #1e6b4f    dark   #124532    light  #9cc9b2
negative #c23b22   amber  #9a6414
tints   #e8f2ec / #fae3df / #fbf0d8 / #eef1ef
cover   linear-gradient(160deg, #1e6b4f 0%, #124532 100%), text #f3f8f5, accent #a8e0c0
```

Inter throughout; bold titles. Each slide carries the logo top left, a
department kicker, a one-sentence conclusion title, a lead with the number,
white cards, and tinted callouts with a short uppercase heading.

Slides are 1920×1080 with inline styles only, padding `128px 128px 160px`, and
the footer pinned at `bottom:64px`; its top edge is y=987. Measure every
slide's content against it after a change.

---

## 5. Writing

Titles state the conclusion in one sentence; leads give the number; callouts
are two short sentences. Both sides of any contrast measure the same thing.
Define non-obvious terms where they appear. Only call something a move if its
test says so. No emojis.
