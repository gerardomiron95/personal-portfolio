/* Card dispute operations dashboard. Reads ../data/data.json (pre-aggregated). */
(function () {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  const DEFAULT_METRICS = ['claim_rate', 'on_time_resolution_rate', 'pc_timeliness_rate',
    'customer_win_rate', 'chargeback_win_rate', 'loss_rate'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const REASONS = ['Total', 'Unauthorized', 'Merchant dispute', 'Processing error'];
  const TABLE_TABS = ['counts', 'dollars'];
  const GRAIN_TABS = ['trends', 'counts', 'dollars'];

  // Funnel table layouts: [kind, column, label?]. m = claim + transaction counts,
  // card = transactions only, d = dollars, r = rate row.
  const COUNT_LAYOUT = [
    ['Intake', [['m', 'claims'], ['card', 'card_transactions'], ['r', 'claim_rate'],
      ['m', 'open_claims'], ['m', 'claims_withdrawn'], ['r', 'withdrawal_rate']]],
    ['Provisional credit', [['m', 'pc_due'], ['m', 'pc_issued'], ['m', 'pc_within_10bd'],
      ['m', 'pc_kept_by_customer'], ['m', 'pc_reversed'],
      ['r', 'pc_rate'], ['r', 'pc_timeliness_rate'], ['r', 'pc_reversal_rate']]],
    ['Resolution', [['m', 'resolved_claims'], ['m', 'customer_wins'], ['m', 'resolved_no_error'],
      ['m', 'resolved_within_deadline'], ['r', 'customer_win_rate'], ['r', 'on_time_resolution_rate']]],
    ['Chargebacks', [['m', 'chargebacks_filed'], ['m', 'chargebacks_decided'], ['m', 'chargebacks_won'],
      ['r', 'chargeback_rate'], ['r', 'chargeback_win_rate']]],
    ['Losses', [['r', 'loss_rate']]],
  ];
  const DOLLAR_LAYOUT = [
    ['Intake', [['d', 'card_dollars', 'Card spending'], ['d', 'claimed_amount', 'Claimed'],
      ['d', 'open_claims_amount', 'Open claims'], ['d', 'claims_withdrawn_amount', 'Claims withdrawn']]],
    ['Provisional credit', [['d', 'pc_issued_amount', 'Provisional credits issued'],
      ['d', 'pc_kept_by_customer_amount', 'Provisional credits kept by customer'], ['d', 'pc_reversed_amount', 'Reversed']]],
    ['Resolution', [['d', 'resolved_claims_amount', 'Resolved'],
      ['d', 'customer_wins_amount', 'Customer wins'], ['d', 'resolved_no_error_amount', 'No error found']]],
    ['Chargebacks', [['d', 'chargebacks_filed_amount', 'Chargebacks filed'],
      ['d', 'chargebacks_won_amount', 'Chargebacks won'], ['d', 'recovered_amount', 'Recovered'],
      ['r', 'recovery_rate']]],
    ['Losses', [['d', 'credited_amount', 'Credited to customers'], ['d', 'written_off_amount', 'Written off'],
      ['r', 'write_off_rate']]],
  ];

  const state = {
    grain: 'month', tab: 'trends', lookback: null, selected: [...DEFAULT_METRICS],
    mature: true, reason: 'Total', timingView: 'rate',
  };
  let D; let RATE; let palette; let matTotal = {}; let earliestCohort = ''; let statusIndex = {};
  let charts = []; let yoyChart = null;

  // ------------------------------------------------------------------ formatting
  const pad = (n) => String(n).padStart(2, '0');
  const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d || 1); };
  const iso = (dt) => `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
  const addDays = (s, n) => { const dt = parse(s); dt.setDate(dt.getDate() + n); return iso(dt); };
  const monthYear = (s) => { const dt = parse(s); return `${MONTHS[dt.getMonth()]} ${dt.getFullYear()}`; };
  const dayLabel = (s, withYear = true) => {
    const dt = parse(s);
    return `${MONTHS[dt.getMonth()]} ${dt.getDate()}${withYear ? `, ${dt.getFullYear()}` : ''}`;
  };
  const periodLabel = (s) => (state.grain === 'month' ? monthYear(s) : dayLabel(s));
  const axisLabel = (s) => {
    const dt = parse(s);
    return state.grain === 'month'
      ? `${MONTHS[dt.getMonth()]} ${String(dt.getFullYear()).slice(2)}`
      : `${MONTHS[dt.getMonth()]} ${dt.getDate()}`;
  };
  const fmtCount = (v) => (v == null ? '–' : Math.round(v).toLocaleString('en-US'));
  const usd = new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2,
  });
  const fmtUsd = (v) => (v == null ? '–' : usd.format(v));
  const scaleRate = (r, v) => (v == null ? null : r.format === 'per10k' ? v * 1e4 : v * 100);
  const fmtScaled = (r, v, digits = 2) => (v == null ? '–'
    : r.format === 'per10k' ? v.toFixed(digits) : `${v.toFixed(digits)}%`);
  const fmtRate = (r, v, digits = 2) => fmtScaled(r, scaleRate(r, v), digits);

  // ------------------------------------------------------------------ data helpers
  const byPeriod = (a, b) => (a.period_start < b.period_start ? -1 : a.period_start > b.period_start ? 1 : 0);
  const table = (grain) => D[`funnel_${grain}`];
  const rowsFrom = (grain, from) => table(grain).filter((r) => r.period_start >= from);
  const currentRow = (grain) => table(grain)[table(grain).length - 1];

  function isMonthMature(ym) {
    if (ym < earliestCohort) return true;
    const r = matTotal[ym];
    return r != null && r >= D.maturity_threshold;
  }

  function isMature(row, grain) {
    const start = row.period_start;
    if (grain === 'month') return isMonthMature(start.slice(0, 7));
    const end = addDays(start, 6) > D.last_day ? D.last_day : addDays(start, 6);
    return isMonthMature(start.slice(0, 7)) && isMonthMature(end.slice(0, 7));
  }

  /** "Target ≥ 98.00%" / "Target ≤ 45.00": the side of the target that counts as met. */
  const targetText = (r) => `Target ${r.direction === 'higher' ? '≥' : '≤'} ${fmtRate(r, r.target)}`;

  function isPartial(row, grain) {
    if (grain === 'month') {
      const dt = parse(row.period_start);
      return iso(new Date(dt.getFullYear(), dt.getMonth() + 1, 0)) > D.last_day;
    }
    return addDays(row.period_start, 6) > D.last_day;
  }

  function windowLabel(rows, grain) {
    if (!rows.length) return '';
    const first = rows[0]; const last = rows[rows.length - 1];
    if (grain === 'month') {
      const base = `${monthYear(first.period_start)} – ${monthYear(last.period_start)}`;
      return isPartial(last, grain) ? `${base} (${monthYear(last.period_start)} partial)` : base;
    }
    const base = `Weeks of ${dayLabel(first.period_start)} – ${dayLabel(last.period_start)}`;
    return isPartial(last, grain) ? `${base} (week of ${dayLabel(last.period_start, false)} partial)` : base;
  }

  // ------------------------------------------------------------------ setup
  function init(data) {
    D = data;
    D.funnel_month.sort(byPeriod);
    D.funnel_week.sort(byPeriod);
    RATE = Object.fromEntries(D.rates.map((r) => [r.id, r]));
    palette = {
      primary: cssVar('--primary'), prior: cssVar('--prior'), muted: cssVar('--muted'), miss: cssVar('--miss'),
      border: cssVar('--border'), ink: cssVar('--ink'), card: cssVar('--card'),
    };
    D.resolution_maturation.filter((r) => r.reason_category === 'Total')
      .forEach((r) => { matTotal[r.cohort_month] = r.resolved_rate; });
    earliestCohort = Object.keys(matTotal).sort()[0] || '';
    D.resolution_status.forEach((s) => {
      const k = `${s.cohort_month}|${s.reason_category}|${s.bucket}`;
      (statusIndex[k] = statusIndex[k] || {})[s.outcome] = s.n;
    });
    Dictionary.init(D.dictionary);
    state.lookback = D.window_start;

    const generated = new Date(D.generated_at);
    $('#updated').textContent = `Updated ${generated.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}`;
    $('#updated').title = `Data through ${dayLabel(D.last_day)}`;

    setupControls();
    setupMultiselect();
    setupTooltip();
    Dictionary.render($('#dictionary-table'), D.dictionary);
    render();
  }

  function setupControls() {
    $$('[data-grain]').forEach((b) => b.addEventListener('click', () => {
      if (b.disabled) return;
      state.grain = b.dataset.grain;
      render();
    }));

    const sel = $('#lookback');
    const months = D.funnel_month.map((r) => r.period_start).filter((s) => s <= D.window_start);
    sel.innerHTML = months.slice().reverse()
      .map((s) => `<option value="${s}">Since ${monthYear(s)}</option>`).join('');
    sel.value = D.window_start;
    sel.addEventListener('change', () => { state.lookback = sel.value; render(); });

    $$('.tabs [data-tab]').forEach((b) => b.addEventListener('click', () => {
      state.tab = b.dataset.tab;
      render();
    }));

    $('#mature-toggle').addEventListener('change', (e) => { state.mature = e.target.checked; renderTrends(); });

    $('#reason-buttons').innerHTML = REASONS
      .map((r) => `<button type="button" data-reason="${esc(r)}">${esc(r)}</button>`).join('');
    $$('#reason-buttons [data-reason]').forEach((b) => b.addEventListener('click', () => {
      state.reason = b.dataset.reason;
      renderTiming();
    }));
    $$('#timing-views [data-view]').forEach((b) => b.addEventListener('click', () => {
      state.timingView = b.dataset.view;
      renderTiming();
    }));
  }

  function setupMultiselect() {
    const root = $('#metric-select');
    const btn = $('.ms-button', root);
    const panel = $('.ms-panel', root);
    const list = $('.ms-list', root);
    list.innerHTML = D.rates
      .map((r) => `<label><input type="checkbox" value="${r.id}"> ${esc(r.label)}</label>`).join('');

    const setOpen = (open) => { panel.hidden = !open; btn.setAttribute('aria-expanded', String(open)); };
    btn.addEventListener('click', () => setOpen(panel.hidden));
    list.addEventListener('change', () => {
      state.selected = $$('input:checked', list).map((i) => i.value);
      syncMultiselect();
      renderTrends();
    });
    $$('.ms-actions [data-act]', root).forEach((b) => b.addEventListener('click', () => {
      const act = b.dataset.act;
      state.selected = act === 'all' ? D.rates.map((r) => r.id) : act === 'clear' ? [] : [...DEFAULT_METRICS];
      syncMultiselect();
      renderTrends();
    }));
    document.addEventListener('click', (e) => { if (!root.contains(e.target)) setOpen(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setOpen(false); });
    syncMultiselect();
  }

  function syncMultiselect() {
    const root = $('#metric-select');
    $$('.ms-list input', root).forEach((i) => { i.checked = state.selected.includes(i.value); });
    const n = state.selected.length;
    $('.ms-button', root).textContent = `${n} metric${n === 1 ? '' : 's'} selected`;
  }

  function setupTooltip() {
    const tip = $('#tip');
    const place = (e) => {
      const pad8 = 12;
      const w = tip.offsetWidth; const h = tip.offsetHeight;
      let x = e.clientX + pad8; let y = e.clientY + pad8;
      if (x + w > window.innerWidth - 8) x = Math.max(8, e.clientX - w - pad8);
      if (y + h > window.innerHeight - 8) y = Math.max(8, e.clientY - h - pad8);
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
    };
    document.addEventListener('mouseover', (e) => {
      const t = e.target.closest('[data-tip]');
      if (!t || !t.dataset.tip) { tip.hidden = true; return; }
      tip.innerHTML = esc(t.dataset.tip).replace(/\n/g, '<br>');
      tip.hidden = false;
      place(e);
    });
    document.addEventListener('mousemove', (e) => { if (!tip.hidden) place(e); });
    document.addEventListener('mouseout', (e) => {
      const t = e.target.closest('[data-tip]');
      if (t && !t.contains(e.relatedTarget)) tip.hidden = true;
    });
    window.addEventListener('scroll', () => { tip.hidden = true; }, true);
  }

  // ------------------------------------------------------------------ render
  function render() {
    $$('.tabs [data-tab]').forEach((b) => {
      const on = b.dataset.tab === state.tab;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    $$('.panel').forEach((p) => { p.hidden = p.id !== `panel-${state.tab}`; });

    const grainOn = GRAIN_TABS.includes(state.tab);
    $$('[data-grain]').forEach((b) => {
      b.classList.toggle('active', b.dataset.grain === state.grain);
      b.disabled = !grainOn;
    });
    $('.controls .segmented').classList.toggle('disabled', !grainOn);
    const lookOn = TABLE_TABS.includes(state.tab);
    $('#lookback').disabled = !lookOn;
    $('.lookback').classList.toggle('disabled', !lookOn);
    $('#control-note').textContent = state.tab === 'trends'
      ? 'Rate trends always show the rolling window; look back applies to the funnel tables.'
      : lookOn ? 'Look back widens the table beyond the rolling 12-month window.'
        : 'Period and look back apply to rate trends and the funnel tables.';

    if (state.tab === 'trends') renderTrends();
    if (state.tab === 'counts') renderFunnel('counts');
    if (state.tab === 'dollars') renderFunnel('dollars');
    if (state.tab === 'timing') renderTiming();
  }

  // ---------- rate trends
  const pointLabels = {
    id: 'pointLabels',
    afterDatasetsDraw(chart, _args, opts) {
      const pts = chart.getDatasetMeta(0).data;
      const n = pts.length;
      if (!n || !opts.format) return;
      const area = chart.chartArea;
      const showAll = area.width / n >= 46;
      const { ctx } = chart;
      ctx.save();
      ctx.font = '500 10.5px Inter, system-ui, sans-serif';
      ctx.fillStyle = opts.color;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      pts.forEach((p, i) => {
        if (!showAll && i !== 0 && i !== n - 1) return;
        const v = chart.data.datasets[0].data[i];
        if (v == null) return;
        const text = opts.format(v);
        const half = ctx.measureText(text).width / 2;
        const x = Math.min(Math.max(p.x, area.left + half), area.right - half);
        ctx.fillText(text, x, p.y - 6);
      });
      ctx.restore();
    },
  };

  function renderTrends() {
    charts.forEach((c) => c.destroy());
    charts = [];
    const grain = state.grain;
    const all = rowsFrom(grain, D.window_start);
    const shown = state.mature ? all.filter((r) => isMature(r, grain)) : all;
    const hidden = all.length - shown.length;
    $('#window-note').textContent = windowLabel(all, grain)
      + (state.mature && hidden ? ` · ${hidden} immature ${grain}${hidden === 1 ? '' : 's'} hidden` : '');

    const grid = $('#chart-grid');
    const ids = D.rates.map((r) => r.id).filter((id) => state.selected.includes(id));
    if (!ids.length) {
      grid.innerHTML = '<div class="card empty">Select at least one metric to view its trend.</div>';
      return;
    }
    grid.innerHTML = ids.map((id) => `
      <div class="card chart-card">
        <h3>${esc(RATE[id].label)}</h3>
        <p>${esc(RATE[id].description)} <strong>${esc(targetText(RATE[id]))}</strong> (dashed line); red points missed it.</p>
        <div class="chart-box"><canvas data-metric="${id}" aria-label="${esc(RATE[id].label)} trend" role="img"></canvas></div>
      </div>`).join('');
    $$('canvas[data-metric]', grid).forEach((cv) => charts.push(lineChart(cv, RATE[cv.dataset.metric], shown)));
  }

  function lineChart(canvas, r, rows) {
    const labels = rows.map((x) => axisLabel(x.period_start));
    const values = rows.map((x) => scaleRate(r, x[r.id]));
    const target = scaleRate(r, r.target);
    // Points that miss the target are red; the current (in-progress) period is never judged.
    const cur = currentRow(state.grain);
    const pointColors = rows.map((x) => (x[r.id] != null && x !== cur && !meetsTarget(r, x[r.id])
      ? palette.miss : palette.primary));
    // Zoom the y-axis when the data and target sit in a narrow band far from zero (e.g. 97–99%),
    // so misses against the target line are visible; otherwise keep a zero baseline.
    const seen = values.filter((v) => v != null).concat(target);
    const lo = Math.min(...seen); const hi = Math.max(...seen);
    const zoom = lo > hi * 0.5;
    const pad = Math.max((hi - lo) * 0.35, hi * 0.005);
    const step = hi - lo < 4 ? 0.5 : 1;
    const yMin = zoom ? Math.floor((lo - pad) / step) * step : 0;
    let yMax = zoom ? Math.ceil((hi + pad) / step) * step : undefined;
    if (r.format === 'pct' && (yMax > 100 || (!zoom && hi > 88))) yMax = 100;
    const tickDigits = zoom && hi - lo < 4 ? 1 : 0;
    return new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: r.label, data: values, borderColor: palette.primary, backgroundColor: palette.primary,
            pointBackgroundColor: pointColors, pointBorderColor: pointColors,
            borderWidth: 2, pointRadius: 3.5, pointHoverRadius: 5, tension: 0.25, spanGaps: true,
          },
          {
            label: 'Target', data: labels.map(() => target), borderColor: palette.muted,
            borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0, fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        layout: { padding: { top: 18, right: 6 } },
        scales: {
          y: {
            min: yMin, max: yMax, grace: zoom ? 0 : '12%',
            grid: { color: palette.border },
            ticks: { color: palette.muted, font: { size: 11 }, maxTicksLimit: 6,
              callback: (v) => fmtScaled(r, v, tickDigits) },
          },
          x: {
            grid: { display: false },
            ticks: { color: palette.muted, font: { size: 11 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 7 },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => (items.length ? periodLabel(rows[items[0].dataIndex].period_start) : ''),
              label: (ctx) => (ctx.datasetIndex === 1
                ? targetText(r)
                : `${r.label}: ${fmtScaled(r, ctx.parsed.y)}`
                  + (pointColors[ctx.dataIndex] === palette.miss ? ' · missed target' : '')),
            },
          },
          pointLabels: { format: (v) => fmtScaled(r, v, 1), color: palette.ink },
        },
      },
      plugins: [pointLabels],
    });
  }

  // ---------- funnel tables
  function renderFunnel(kind) {
    const grain = state.grain;
    const rows = rowsFrom(grain, state.lookback);
    const cur = currentRow(grain);
    const counts = kind === 'counts';
    const layout = counts ? COUNT_LAYOUT : DOLLAR_LAYOUT;
    const span = counts ? 2 : 1;
    $(`#${kind}-note`).textContent = 'Rates shaded against Northwind\'s monthly targets: green meets the target, '
      + 'red misses it. Hover a rate for its target. Current period not shaded.';

    const head1 = rows.map((r) => `<th class="divider${r === cur ? ' current' : ''}" colspan="${span}">`
      + `${esc(periodLabel(r.period_start))}${r === cur ? ' *' : ''}</th>`).join('');
    const head2 = counts
      ? `<tr>${rows.map(() => '<th class="divider">Claims</th><th>Transactions</th>').join('')}</tr>` : '';
    const thead = `<thead><tr><th class="label"${counts ? ' rowspan="2"' : ''}>Metric</th>${head1}</tr>${head2}</thead>`;

    let body = '';
    layout.forEach(([section, items]) => {
      body += `<tr class="section"><td class="label">${esc(section)}</td><td colspan="${rows.length * span}"></td></tr>`;
      items.forEach(([type, col, label]) => {
        if (type === 'r') {
          const r = RATE[col];
          const tip = Dictionary.tipFor(col);
          body += `<tr class="rate"><td class="label" data-tip="${esc(tip)}">${esc(r.label)}</td>`
            + rows.map((row) => rateCell(r, row, span, row === cur)).join('') + '</tr>';
          return;
        }
        const name = type === 'm' ? D.labels[col] : type === 'card' ? 'Card transactions' : label;
        body += `<tr><td class="label" data-tip="${esc(Dictionary.tipFor(col))}">${esc(name)}</td>`;
        body += rows.map((row) => {
          const c = row === cur ? ' current' : '';
          if (type === 'm') {
            const txnCol = col === 'claims' ? 'claim_transactions' : `${col}_txns`;
            return `<td class="value divider${c}">${fmtCount(row[col])}</td><td class="value${c}">${fmtCount(row[txnCol])}</td>`;
          }
          if (type === 'card') {
            return `<td class="divider muted${c}">–</td><td class="value${c}">${fmtCount(row[col])}</td>`;
          }
          return `<td class="value divider${c}">${fmtUsd(row[col])}</td>`;
        }).join('');
        body += '</tr>';
      });
    });

    $(`#${kind}-table`).innerHTML = `<table class="funnel">${thead}<tbody>${body}</tbody></table>`
      + '<p class="panel-note" style="margin:8px 10px">* Current period, still in progress.</p>';
  }

  /** Meets target: at or above it for "higher" rates, at or below it for "lower" rates. */
  const meetsTarget = (r, v) => (r.direction === 'higher' ? v >= r.target - 1e-12 : v <= r.target + 1e-12);

  function rateCell(r, row, span, isCurrent) {
    const v = row[r.id];
    const text = fmtRate(r, v);
    let cls = 'value divider';
    let tip = '';
    if (v != null) {
      const ok = meetsTarget(r, v);
      tip = targetText(r);
      if (isCurrent) tip += '\nCurrent period: not shaded';
      else {
        tip += ok ? ' · met' : ' · missed';
        cls += ok ? ' better' : ' worse';
      }
    }
    if (isCurrent) cls += ' current';
    return `<td class="${cls}" colspan="${span}"${tip ? ` data-tip="${esc(tip)}"` : ''}>${text}</td>`;
  }

  // ---------- resolution timing
  function mix(hex, t) {
    const n = parseInt(hex.replace('#', ''), 16);
    const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => Math.round(255 + (c - 255) * t));
    return `rgb(${rgb.join(',')})`;
  }

  function renderTiming() {
    $$('#reason-buttons [data-reason]').forEach((b) => {
      b.classList.toggle('active', b.dataset.reason === state.reason);
      b.disabled = state.timingView === 'yoy';
    });
    $('#reason-buttons').classList.toggle('disabled', state.timingView === 'yoy');
    $$('#timing-views [data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === state.timingView));

    const yoy = state.timingView === 'yoy';
    $('#heatmap').hidden = yoy;
    $('#yoy-wrap').hidden = !yoy;
    if (yoy) { renderYoy(); return; }

    const rate = state.timingView === 'rate';
    $('#timing-note').textContent = (rate
      ? 'Share of each month\'s claims resolved or withdrawn in each month after receipt (M0 = same month). '
      : 'Claims resolved or withdrawn in each month after receipt (M0 = same month). ')
      + 'Hover a cell for its outcome breakdown. Hatched cells are still in the future.';

    const rows = D.resolution_maturation.filter((r) => r.reason_category === state.reason)
      .sort((a, b) => (a.cohort_month < b.cohort_month ? 1 : -1));
    const buckets = [0, 1, 2, 3, 4, 5, 6];
    const cellVal = (row, i) => (rate ? row[`M${i}_rate`] : row[`M${i}_count`]);
    const summaryVal = (row) => (rate ? row.resolved_rate
      : buckets.reduce((s, i) => s + (row[`M${i}_count`] || 0), 0));
    const colMax = buckets.map((i) => Math.max(0, ...rows.map((r) => cellVal(r, i) || 0)));
    const sumMax = Math.max(0, ...rows.map(summaryVal));
    const fmt = (v) => (v == null ? '' : rate ? `${(v * 100).toFixed(1)}%` : fmtCount(v));

    const cell = (v, max, tip, extra = '') => {
      if (v == null) return `<td class="cell blank${extra}"></td>`;
      const t = max > 0 ? v / max : 0;
      const bg = mix(palette.primary, t * 0.92);
      const color = t > 0.55 ? '#fff' : palette.ink;
      return `<td class="cell${extra}" style="background:${bg};color:${color}" data-tip="${esc(tip)}">${fmt(v)}</td>`;
    };
    const breakdown = (row, list) => {
      const totals = { 'Customer wins': 0, 'No error found': 0, 'Claims withdrawn': 0 };
      list.forEach((i) => {
        const s = statusIndex[`${row.cohort_month}|${row.reason_category}|${i}`] || {};
        Object.keys(totals).forEach((k) => { totals[k] += s[k] || 0; });
      });
      const total = Object.values(totals).reduce((a, b) => a + b, 0);
      return Object.entries(totals).map(([k, v]) => `${k}: ${fmtCount(v)}`).join('\n') + `\nTotal: ${fmtCount(total)}`;
    };

    const head = `<thead><tr><th class="label">Cohort (month received)</th><th>Claims</th>${
      buckets.map((i) => `<th>M${i}</th>`).join('')}<th class="summary">Resolved so far</th></tr></thead>`;
    const body = rows.map((row) => {
      const title = monthYear(`${row.cohort_month}-01`);
      const cells = buckets.map((i) => {
        const v = cellVal(row, i);
        const tip = `${title} · M${i} (${state.reason})\n${breakdown(row, [i])}`;
        return cell(v, colMax[i], tip);
      }).join('');
      const done = buckets.filter((i) => row[`M${i}_count`] != null);
      const sTip = `${title} · resolved so far (${state.reason})\n${breakdown(row, done)}\nOf ${fmtCount(row.claims)} claims`;
      return `<tr><td class="label">${title}</td><td>${fmtCount(row.claims)}</td>${cells}`
        + `${cell(summaryVal(row), sumMax, sTip, ' summary')}</tr>`;
    }).join('');
    $('#heatmap').innerHTML = `<table class="heatmap">${head}<tbody>${body}</tbody></table>`;
  }

  function renderYoy() {
    $('#timing-note').textContent = 'Claim rate per 10,000 card transactions, all reasons. '
      + 'Dashed segments are the latest two months, which are still incomplete.';
    if (yoyChart) yoyChart.destroy();
    const years = [...new Set(D.yoy.map((r) => r.year))].sort((a, b) => b - a).slice(0, 3);
    const colors = [palette.primary, palette.prior, palette.muted];
    const datasets = years.map((y, k) => {
      const byMonth = {};
      D.yoy.filter((r) => r.year === y).forEach((r) => { byMonth[r.month_num] = r; });
      const data = MONTHS.map((_, m) => (byMonth[m + 1] ? byMonth[m + 1].claim_rate : null));
      const incomplete = MONTHS.map((_, m) => !!(byMonth[m + 1] && byMonth[m + 1].is_incomplete));
      return {
        label: String(y), data, borderColor: colors[k], backgroundColor: colors[k],
        pointBackgroundColor: incomplete.map((f) => (f ? palette.card : colors[k])),
        pointRadius: 3.5, borderWidth: k === 0 ? 2.5 : 2, tension: 0.25,
        segment: { borderDash: (ctx) => (incomplete[ctx.p1DataIndex] ? [6, 4] : undefined) },
        incomplete,
      };
    });
    yoyChart = new Chart($('#yoy-chart'), {
      type: 'line',
      data: { labels: MONTHS, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          y: { beginAtZero: true, grid: { color: palette.border }, ticks: { color: palette.muted },
            title: { display: true, text: 'Claims per 10k transactions', color: palette.muted } },
          x: { grid: { display: false }, ticks: { color: palette.muted } },
        },
        plugins: {
          legend: { position: 'bottom', labels: { usePointStyle: true, boxHeight: 6, color: palette.ink } },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} per 10k`
                + (ctx.dataset.incomplete[ctx.dataIndex] ? ' (incomplete)' : ''),
            },
          },
        },
      },
    });
  }

  // ------------------------------------------------------------------ boot
  fetch('../data/data.json')
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(init)
    .catch((err) => {
      $('main').innerHTML = `<div class="card empty">Could not load data (${esc(err.message)}). `
        + 'Serve the project folder over HTTP, for example with <code>make serve</code>.</div>';
      console.error(err);
    });
})();
