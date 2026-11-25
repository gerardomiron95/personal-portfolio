# Portfolio rules

## Every project needs an About pop-up

Any project added to the portfolio must have, on its card in the Projects section of `index.html`:

1. Three buttons, in this order: **View** (the live page, e.g. "View dashboard"), **Code** (the project's folder on GitHub) and **About**.
2. An About pop-up that explains, in plain English, why the project was started and completed, under three headings, always in this order:
   - **Problem**: the gap, friction point or business impact being solved.
   - **Insight**: the underlying "why" found through data or observation that explains the root cause.
   - **Initiative**: the concrete solution that was built to address the insight and solve the problem.

### Writing the pop-up

- One or two short sentences per heading. Straight to the point; no jargon a non-specialist would trip on.
- No "I" statements. Start the Initiative with a past-tense verb ("Built…", "Automated…").
- Describe the real-world work the project mirrors. The data is sample data, but the problem and the work are real.

### Markup

Copy this pattern. The `data-about` value on the button must match the `<dialog>` id, and the ids must be unique per project. Do not change the classes: `assets/site.css` styles the pop-up (bold headings, spacing and dividers between sections), and the script at the bottom of `index.html` opens and closes every pop-up (× button, Esc, or a click outside).

```html
<article class="project">
  <div>
    <h3>Project Title</h3>
    <p>One or two sentences on what the project is.</p>
    <p class="tags">Tool · Tool · Tool</p>
  </div>
  <div class="project-actions">
    <a class="button" href="project-folder/">View dashboard</a>
    <a class="button ghost" href="https://github.com/gerardomiron95/personal-portfolio/tree/main/project-folder">Code</a>
    <button type="button" class="button ghost" data-about="about-project-slug">About</button>
  </div>
</article>

<dialog class="about" id="about-project-slug" aria-labelledby="about-project-slug-title">
  <div class="about-head">
    <h3 id="about-project-slug-title">Project Title</h3>
    <button type="button" class="about-close" aria-label="Close">×</button>
  </div>
  <dl>
    <dt>Problem</dt>
    <dd>…</dd>
    <dt>Insight</dt>
    <dd>…</dd>
    <dt>Initiative</dt>
    <dd>…</dd>
  </dl>
</dialog>
```

Reference: the Card Dispute Operations Analytics card in `index.html`.

## Also when adding a project

- Give the project its own folder at the repository root with its own README.
- Add a row to the project table in the root `README.md`.
