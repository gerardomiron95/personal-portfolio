# Northwind Bank: Weekly Operations Performance Review

A portfolio piece: a repeatable weekly metrics deck for the Banking Operations
team of a fictional consumer neobank, built from synthetic data.

**Everything here is invented.** Northwind Bank and its vendor Clearwave do not
exist. No figure, label, queue name or metric definition comes from any real
organisation.

## What's here

```
generate_data.py    synthetic data generator (fixed seed, deterministic)
data/*.csv          three sources: check deposits, ACH direct deposits, card reissues
figures.py          every figure on the slides, computed from the CSVs, plus reconciliation checks
build_deck.py       renders the slides and speaker notes to index.html
HANDOFF.md          the build brief: rules, figures, slides and visual system
```

## Rebuild

```bash
python3 generate_data.py --summary
python3 build_deck.py
```

Then open `index.html` through a local web server, or view it on the portfolio site.

## What it demonstrates

- **Like-for-like windows.** A partial month is compared with the same elapsed
  days of the month before, never with a full month.
- **Significance before story.** Every funnel row and every reissue reason is
  tested, and only significant changes are called moves.
- **Finding the driver.** The headline change is split by capture device, and
  each device's contribution adds up to the total.
- **Distributions, not just medians.** Decision times are shown as full
  distributions, because a queue can slow down while its median barely moves.
- **Denominators kept apart.** The early-pay rate and the days-early mix use
  different denominators, and each chart is labelled with its own.

It also records a technique it tested and did not use, a control chart on the
deposit rate, and explains why in the speaker notes.
