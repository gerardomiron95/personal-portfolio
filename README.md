# professional-portfolio

A portfolio showcasing personal projects. Each project lives in its own folder with
its own README.

**Live site:** https://gerardomiron95.github.io/personal-portfolio/

| Project | What it is | Tools | Live |
|---|---|---|---|
| [Card Dispute Operations Analytics](card-dispute-analytics/) | A data pipeline and dashboard, built on generated sample data, tracking card disputes from intake to chargeback recovery, measured against the public Reg E error-resolution timelines. | Python, pandas, Parquet, Chart.js | [Dashboard](https://gerardomiron95.github.io/personal-portfolio/card-dispute-analytics/web/) |

## Site layout

The site is served by GitHub Pages from the repository root on `main`.

- `index.html` and `assets/`: the landing page (summary, projects, experience, education).
- Each project folder is published at its own path, e.g. `card-dispute-analytics/web/`.
- `.nojekyll` tells GitHub Pages to serve files as-is.

To add a project: give it its own folder, then add a card to the Projects section of
`index.html` and a row to the table above. Every project card must have View, Code and
About buttons, and an About pop-up with Problem, Insight and Initiative sections. See
[CLAUDE.md](CLAUDE.md) for the rules and the markup to copy.

To preview locally, serve the repository root and open http://localhost:8000/:

```bash
python3 -m http.server 8000
```
