/* Mobile check deposit flow dashboard.
 * Reads the generated CSVs in data/ and only filters and sums them: every figure is
 * recomputed from rows for the selected tab, date range and segment. Medians come from
 * timing_rows.csv for each selection; medians are never averaged. */
(() => {
  'use strict';

  // ------------------------------------------------------------------ constants
  // The Overview tab (date range + trend charts) is switched off for now; the page opens on the
  // latest month. Set to true to bring it back.
  const SHOW_OVERVIEW = false;
  const SEGMENTS = [['all', 'All'], ['direct_deposit', 'Direct deposit'],
    ['no_direct_deposit', 'No direct deposit'], ['unknown', 'Unknown']];
  const QUEUES = [['fast_track', 'Fast-track queue'], ['standard', 'Standard review'], ['high_risk', 'High-risk review']];
  const QUEUE_NAME = Object.fromEntries(QUEUES);
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  // Colors follow the portfolio's dashboard palette (see styles.css).
  const COLOR = {
    received: '#869189', auto: '#c97a2b', approved: '#4a8fd8', queue: '#2f5f8a', inQueue: '#a7b0aa',
    deposited: '#1e6b4f', rejected: '#c8372d', notReturned: '#5fa37f', returned: '#a3522a',
  };
  const SERIES = ['#1e6b4f', '#4a8fd8', '#c97a2b', '#5fa37f', '#8a6fb0', '#869189'];
  const INK = '#1c2a24'; const MUTED = '#869189'; const GRID = '#e0e6e2';

  // Flowchart: [column, row, color, label, parent for the share line]
  const NODES = {
    received: [0, 2, 'received', 'Checks received', null],
    auto_denied: [1, 0, 'auto', 'Auto-denied by vendor', 'received'],
    approved: [1, 4, 'approved', 'Approved for review', 'received'],
    fast_track: [2, 1.5, 'queue', 'Fast-track queue', 'approved'],
    standard: [2, 3.5, 'queue', 'Standard review', 'approved'],
    high_risk: [2, 5.5, 'queue', 'High-risk review', 'approved'],
    in_queue: [2, 7, 'inQueue', 'Still in queue', 'approved'],
    fast_track_deposited: [3, 1, 'deposited', 'Deposited', 'fast_track'],
    fast_track_rejected: [3, 2, 'rejected', 'Rejected', 'fast_track'],
    standard_deposited: [3, 3, 'deposited', 'Deposited', 'standard'],
    standard_rejected: [3, 4, 'rejected', 'Rejected', 'standard'],
    high_risk_deposited: [3, 5, 'deposited', 'Deposited', 'high_risk'],
    high_risk_rejected: [3, 6, 'rejected', 'Rejected', 'high_risk'],
    deposited: [4, 2, 'deposited', 'Deposited (total)', 'approved'],
    rejected: [4, 5, 'rejected', 'Rejected (total)', 'approved'],
    not_returned: [5, 1.4, 'notReturned', 'Deposited, not returned', 'deposited'],
    returned: [5, 2.6, 'returned', 'Returned after deposit', 'deposited'],
  };
  const EDGES = [['received', 'auto_denied'], ['received', 'approved'],
    ...QUEUES.map(([q]) => ['approved', q]), ['approved', 'in_queue'],
    ...QUEUES.flatMap(([q]) => [[q, `${q}_deposited`], [q, `${q}_rejected`],
      [`${q}_deposited`, 'deposited'], [`${q}_rejected`, 'rejected']]),
    ['deposited', 'not_returned'], ['deposited', 'returned']];
  const DRILL = ['rejected', 'fast_track', 'standard', 'high_risk', 'returned'];
  const BOX = { w: 176, h: 80, px: 212, py: 96, m: 14 };

  // ------------------------------------------------------------------ state and data
  const state = {
    tab: 'overview', measure: 'count', segment: 'all', from: '', to: '', grain: 'month',
    panel: null, panelTab: null, week: 'all', reviewer: null,
    retMode: 'entered', analyst: null, reason: null, adReason: null,
  };
  const D = { nodes: [], timing: [], rej: [], months: [], monthRange: {}, first: '', last: '' };
  let charts = [];

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ------------------------------------------------------------------ formatting
  const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
  const iso = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  const dayLabel = (s, year = true) => { const d = parse(s); return `${MONTHS[d.getMonth()]} ${d.getDate()}${year ? `, ${d.getFullYear()}` : ''}`; };
  const monthLabel = (ym) => `${MONTHS[Number(ym.slice(5)) - 1]} ${ym.slice(0, 4)}`;
  const weekLabel = (a, b) => (a === b ? dayLabel(a, false)
    : parse(a).getMonth() === parse(b).getMonth() ? `${dayLabel(a, false)}–${parse(b).getDate()}` : `${dayLabel(a, false)} – ${dayLabel(b, false)}`);
  const mondayOf = (s) => { const d = parse(s); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return iso(d); };

  const fmtN = (n) => Math.round(n).toLocaleString('en-US');
  const usdShort = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 });
  const usdFull = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  const fmtV = (n, full = false) => (state.measure === 'count' ? fmtN(n) : (full ? usdFull : usdShort).format(n));
  const fmtP = (x, d = 1) => (x == null || !Number.isFinite(x) ? '–' : `${(x * 100).toFixed(d)}%`);
  const ratio = (a, b) => (b > 0 ? a / b : null);
  const fmtDays = (m) => (m == null ? '–' : `${Number.isInteger(m) ? m : m.toFixed(1)} business day${m === 1 ? '' : 's'}`);

  function median(xs) {
    if (!xs.length) return null;
    const s = [...xs].sort((a, b) => a - b); const h = s.length >> 1;
    return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
  }
  function percentile(xs, q) {  // nearest rank
    if (!xs.length) return null;
    const s = [...xs].sort((a, b) => a - b);
    return s[Math.max(0, Math.ceil(q * s.length) - 1)];
  }

  // ------------------------------------------------------------------ selection
  function period(tab = state.tab) {
    return tab === 'overview' ? { from: state.from, to: state.to } : D.monthRange[tab];
  }
  function prevMonth() {
    if (state.tab === 'overview') return null;
    const i = D.months.indexOf(state.tab);
    return i > 0 ? D.months[i - 1] : null;
  }

  /** Sum node_counts.csv rows for a period and the selected segment. */
  function aggregate(p) {
    const out = { node: {}, adReason: new Map(), adSub: new Map(), reject: new Map(), combo: new Map() };
    const add = (map, key, x) => {
      let e = map.get(key);
      if (!e) { e = { key, label: x.label, parent: x.parent, count: 0, amount: 0 }; map.set(key, e); }
      e.count += x.count; e.amount += x.amount;
    };
    for (const x of D.nodes) {
      if (x.segment !== state.segment || x.date < p.from || x.date > p.to) continue;
      if (x.kind === 'flow' || x.kind === 'queue_outcome') {
        const e = out.node[x.node] || (out.node[x.node] = { count: 0, amount: 0 });
        e.count += x.count; e.amount += x.amount;
      } else if (x.kind === 'auto_deny_reason') add(out.adReason, x.key, x);
      else if (x.kind === 'auto_deny_sub') add(out.adSub, x.key, x);
      else if (x.kind === 'reject_reason') add(out.reject, `${x.node}||${x.key}`, x);
      else if (x.kind === 'return_combo') add(out.combo, x.key, x);
    }
    return out;
  }
  const val = (a, id) => (a.node[id] ? a.node[id][state.measure] : 0);
  const m = (e) => e[state.measure];

  function timingFor(p) {
    return D.timing.filter((t) => t.date >= p.from && t.date <= p.to
      && (state.segment === 'all' || t.segment === state.segment));
  }

  // ------------------------------------------------------------------ setup
  const load = (file) => new Promise((resolve, reject) => Papa.parse(`data/${file}`, {
    download: true, header: true, skipEmptyLines: true, complete: (r) => resolve(r.data), error: reject,
  }));

  function init([nodes, timing, rej]) {
    D.nodes = nodes.map((x) => ({
      date: x.date, month: x.month, segment: x.segment, node: x.node_id, label: x.label, parent: x.parent,
      kind: x.kind, key: x.key, count: Number(x.count), amount: Number(x.amount),
    }));
    D.timing = timing.map((t) => ({
      month: t.month, date: t.date, segment: t.segment, queue: t.queue, decision: t.decision,
      days: Number(t.days_to_decision), ret: t.days_to_return === '' ? null : Number(t.days_to_return),
    }));
    D.rej = rej.map((r) => ({ ...r, count: Number(r.count) }));
    for (const x of D.nodes) {
      const r = D.monthRange[x.month] || (D.monthRange[x.month] = { from: x.date, to: x.date });
      if (x.date < r.from) r.from = x.date;
      if (x.date > r.to) r.to = x.date;
    }
    D.months = Object.keys(D.monthRange).sort();
    D.first = D.monthRange[D.months[0]].from;
    D.last = D.monthRange[D.months[D.months.length - 1]].to;
    state.from = D.first; state.to = D.last;
    state.tab = SHOW_OVERVIEW ? 'overview' : D.months[D.months.length - 1];
    $('#range').textContent = `Data ${dayLabel(D.first)} – ${dayLabel(D.last)}`;
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    $('#flow').addEventListener('keydown', (e) => {
      const g = e.target.closest('.drill');
      if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); togglePanel(g.dataset.node); }
    });
    render();
    if (document.fonts) document.fonts.ready.then(revealActiveTab);  // tab widths change once Inter loads
  }

  // ------------------------------------------------------------------ render
  function render() {
    renderTabs();
    renderControls();
    const p = period();
    const a = aggregate(p);
    const pm = prevMonth();
    renderCards(a, pm ? aggregate(period(pm)) : null, pm);
    renderFlow(a, p);
    renderPanel(a, p);
    renderAutoDeny(a);
    renderTrends();
  }

  function renderTabs() {
    const tabs = [...(SHOW_OVERVIEW ? [['overview', 'Overview']] : []), ...D.months.map((ym) => [ym, monthLabel(ym)])];
    $('#tabs').innerHTML = tabs.map(([id, label]) => `<button type="button" role="tab" data-tab="${id}"`
      + ` aria-selected="${state.tab === id}" class="${state.tab === id ? 'active' : ''}">${label}</button>`).join('');
    revealActiveTab();
  }

  /** Keep the active month visible when the tab strip scrolls (the page opens on the latest month). */
  function revealActiveTab() {
    const strip = $('#tabs'); const active = $('#tabs .active');
    if (!active) return;
    if (!active.nextElementSibling) { strip.scrollLeft = strip.scrollWidth; return; }
    const sr = strip.getBoundingClientRect(); const ar = active.getBoundingClientRect();
    if (ar.right > sr.right) strip.scrollLeft += ar.right - sr.right + 8;
    else if (ar.left < sr.left) strip.scrollLeft -= sr.left - ar.left + 8;
  }

  function renderControls() {
    const seg = (list, attr, cur) => list.map(([id, label]) => `<button type="button" data-${attr}="${id}"`
      + ` class="${cur === id ? 'active' : ''}" aria-pressed="${cur === id}">${label}</button>`).join('');
    let html = `
      <div class="control"><span class="control-label">Show</span>
        <div class="segmented" role="group" aria-label="Measure">${seg([['count', 'Count'], ['amount', 'Amount ($)']], 'measure', state.measure)}</div></div>
      <div class="control"><span class="control-label">Segment</span>
        <div class="segmented" role="group" aria-label="Member segment">${seg(SEGMENTS, 'segment', state.segment)}</div></div>`;
    if (state.tab === 'overview') {
      const full = state.from === D.first && state.to === D.last;
      html += `
      <div class="control"><label class="control-label" for="from">From</label>
        <input type="date" id="from" value="${state.from}" min="${D.first}" max="${D.last}">
        <label class="control-label" for="to">To</label>
        <input type="date" id="to" value="${state.to}" min="${D.first}" max="${D.last}">
        ${full ? '' : '<button type="button" class="link-button" data-action="reset-range">Reset</button>'}</div>`;
    }
    $('#controls').innerHTML = html;
  }

  // ---------- scorecards
  function renderCards(a, prev, pm) {
    const defs = [
      ['received', 'Checks received', null],
      ['auto_denied', 'Auto-denied', 'received', 'down'],
      ['approved', 'Approved for review', 'received', 'up'],
      ['not_returned', 'Deposited with no returns', 'approved', 'up'],
      ['rejected', 'Rejected', 'approved', 'down'],
      ['in_queue', 'Still in queue', 'approved', 'flat'],
      ['returned', 'Returned after deposit', 'deposited', 'down'],
    ];
    const baseName = { received: 'received', approved: 'approved', deposited: 'deposited' };
    const p = period();
    $('#cards').innerHTML = defs.map(([id, label, base, good]) => {
      const v = val(a, id);
      const sh = base ? ratio(v, val(a, base)) : null;
      const shareText = base ? `${fmtP(sh)} of ${baseName[base]}` : `${dayLabel(p.from, false)} – ${dayLabel(p.to, false)}`;
      let delta = '';
      if (prev) {
        let text = ''; let cls = 'flat';
        if (base) {
          const ps = ratio(val(prev, id), val(prev, base));
          if (sh != null && ps != null) {
            const pts = (sh - ps) * 100;
            const r = Math.round(Math.abs(pts) * 10) / 10;
            text = `${r === 0 ? '–' : pts > 0 ? '▲' : '▼'} ${r.toFixed(1)} pts vs ${MONTHS[Number(pm.slice(5)) - 1]}`;
            if (r !== 0 && good !== 'flat') cls = (pts > 0) === (good === 'up') ? 'good' : 'bad';
          }
        } else {
          const pv = val(prev, id);
          if (pv > 0) {
            const ch = v / pv - 1;
            text = `${ch >= 0 ? '▲' : '▼'} ${Math.abs(ch * 100).toFixed(1)}% vs ${MONTHS[Number(pm.slice(5)) - 1]}`;
          }
        }
        delta = text ? `<div class="delta ${cls}">${text}</div>` : '';
      }
      return `<div class="score"><div class="label">${label}</div><div class="value" title="${esc(fmtV(v, true))}">${fmtV(v)}</div>`
        + `<div class="share">${shareText}</div>${delta}</div>`;
    }).join('');
  }

  // ---------- flowchart
  function renderFlow(a, p) {
    const t = timingFor(p);
    const med = {};
    const days = (rows) => rows.map((r) => r.days);
    for (const [q] of QUEUES) {
      med[`${q}_deposited`] = median(days(t.filter((r) => r.queue === q && r.decision === 'deposited')));
      med[`${q}_rejected`] = median(days(t.filter((r) => r.queue === q && r.decision === 'rejected')));
    }
    med.deposited = median(days(t.filter((r) => r.decision === 'deposited')));
    med.rejected = median(days(t.filter((r) => r.decision === 'rejected')));
    med.returned = median(t.filter((r) => r.ret != null).map((r) => r.ret));

    const { w, h, px, py, m: mg } = BOX;
    const pos = (id) => ({ x: mg + NODES[id][0] * px, y: mg + NODES[id][1] * py });
    const width = mg * 2 + 5 * px + w;
    const height = mg * 2 + 7 * py + h + 10;
    const total = val(a, 'received') || 1;

    const edges = EDGES.map(([s, d]) => {
      const A = pos(s); const B = pos(d);
      const x1 = A.x + w; const y1 = A.y + h / 2; const x2 = B.x; const y2 = B.y + h / 2; const cx = (x1 + x2) / 2;
      const sw = Math.max(1.5, 16 * val(a, d) / total);
      return `<path class="edge" d="M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}" stroke-width="${sw.toFixed(1)}"/>`;
    }).join('');

    const boxes = Object.entries(NODES).map(([id, [, , colorKey, label, parent]]) => {
      const { x, y } = pos(id); const c = COLOR[colorKey];
      const v = val(a, id);
      const share = parent ? `${fmtP(ratio(v, val(a, parent)))} of ${NODES[parent][3].toLowerCase().replace(' (total)', '')}` : '';
      const medianLine = id in med ? `Median ${fmtDays(med[id])}` : '';
      let drill = '';
      if (DRILL.includes(id)) {
        const open = state.panel === id;
        drill = `<g class="drill${open ? ' open' : ''}" data-node="${id}" role="button" tabindex="0"`
          + ` aria-expanded="${open}" aria-label="${open ? 'Hide' : 'Show'} details for ${esc(label)}">`
          + `<rect x="${x + 10}" y="${y + h - 4}" width="28" height="17" rx="8.5" stroke="${c}" stroke-width="1.5"/>`
          + `<text x="${x + 24}" y="${y + h + 8.5}" text-anchor="middle" fill="${c}">${open ? '▴' : '▾'}</text></g>`;
      }
      return `<g class="box" data-id="${id}"><title>${esc(label)}: ${esc(fmtV(v, true))}</title>`
        + `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="${c}" fill-opacity="0.1" stroke="${c}" stroke-width="1.2"/>`
        + `<rect x="${x}" y="${y}" width="5" height="${h}" rx="2" fill="${c}"/>`
        + `<text class="box-label" x="${x + 14}" y="${y + 19}">${esc(label)}</text>`
        + `<text class="box-value" x="${x + 14}" y="${y + 40}">${esc(fmtV(v))}</text>`
        + `<text class="box-share" x="${x + 14}" y="${y + 56}">${esc(share)}</text>`
        + `<text class="box-median" x="${x + 14}" y="${y + 71}">${esc(medianLine)}</text>${drill}</g>`;
    }).join('');

    $('#flow').innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Deposit flowchart">${edges}${boxes}</svg>`;
  }

  // ---------- reusable sorted bar list (share in the label)
  function bars(items, total, { attr = null, selected = null, fmt = (x) => fmtV(x), color = 'var(--primary)' } = {}) {
    const list = items.filter((i) => i.value > 0).sort((x, y) => y.value - x.value || x.label.localeCompare(y.label));
    if (!list.length) return '<div class="empty-note">Nothing in this selection.</div>';
    const max = list[0].value;
    return `<div class="bars">${list.map((i) => {
      const pct = (i.value / max) * 100;
      const tag = attr ? 'button' : 'div';
      const sel = selected === i.key ? ' selected' : '';
      const at = attr ? ` type="button" data-${attr}="${esc(i.key)}" aria-pressed="${selected === i.key}"` : '';
      return `<${tag} class="bar-row${sel}"${at}><span class="name" title="${esc(i.label)}">${esc(i.label)}</span>`
        + `<span class="track"><span class="fill" style="width:${pct.toFixed(1)}%;background:${color}"></span></span>`
        + `<span class="num">${esc(fmt(i.value))} · ${fmtP(ratio(i.value, total))}</span></${tag}>`;
    }).join('')}</div>`;
  }

  // ---------- drill-down panels
  function togglePanel(id) {
    if (state.panel === id) { state.panel = null; } else {
      Object.assign(state, { panel: id, panelTab: id === 'returned' ? 'entered' : 'reviewers', week: 'all',
        reviewer: null, analyst: null, reason: null, retMode: 'entered' });
    }
    render();
  }

  function renderPanel(a, p) {
    const el = $('#panel');
    const id = state.panel;
    if (!id) { el.innerHTML = ''; return; }
    const title = id === 'rejected' ? 'Rejected (total)' : id === 'returned' ? 'Returned after deposit' : QUEUE_NAME[id];
    let tabs = ''; let body = '';
    if (id === 'rejected') body = reviewerSection(p, null);
    else if (id === 'returned') {
      tabs = subtabs([['entered', 'Analyst who entered the reason'], ['assigned', 'Assigned analyst']], state.retMode, 'ret-mode');
      body = returnsSection(a);
    } else {
      tabs = subtabs([['reviewers', 'Rejections by reviewer'], ['days', 'Days to deposit']], state.panelTab, 'panel-tab');
      body = state.panelTab === 'days' ? daysSection(p, id) : reviewerSection(p, id);
    }
    el.innerHTML = `<div class="panel-head"><h3>${esc(title)}</h3>`
      + `<button type="button" class="close" data-action="close-panel" aria-label="Close details">×</button></div>${tabs}${body}`;
  }

  const subtabs = (list, cur, attr) => `<div class="subtabs" role="tablist">${list.map(([id, label]) =>
    `<button type="button" role="tab" data-${attr}="${id}" class="${cur === id ? 'active' : ''}" aria-selected="${cur === id}">${label}</button>`).join('')}</div>`;

  function reviewerSection(p, queue) {
    // Review weeks are cut at month boundaries, so a month's weeks match its Rejected boxes exactly.
    const rows = D.rej.filter((r) => (!queue || r.queue === queue) && r.week_start >= p.from && r.week_start <= p.to);
    const weeks = [...new Set(rows.map((r) => r.week_start))].sort();
    if (state.week !== 'all' && !weeks.includes(state.week)) state.week = 'all';
    const inWeek = state.week === 'all' ? rows : rows.filter((r) => r.week_start === state.week);
    const byReviewer = new Map();
    inWeek.forEach((r) => byReviewer.set(r.reviewer, (byReviewer.get(r.reviewer) || 0) + r.count));
    if (state.reviewer && !byReviewer.has(state.reviewer)) state.reviewer = null;
    const byReason = new Map();
    inWeek.filter((r) => !state.reviewer || r.reviewer === state.reviewer)
      .forEach((r) => byReason.set(r.reason, (byReason.get(r.reason) || 0) + r.count));
    const total = [...byReviewer.values()].reduce((s, x) => s + x, 0);
    const reasonTotal = [...byReason.values()].reduce((s, x) => s + x, 0);
    const weekTabs = `<div class="weeks" role="tablist" aria-label="Review week">`
      + [['all', 'All weeks'], ...weeks.map((w) => [w, weekLabel(w, rows.find((r) => r.week_start === w).week_end)])].map(([k, label]) =>
        `<button type="button" role="tab" data-week="${k}" class="${state.week === k ? 'active' : ''}" aria-selected="${state.week === k}">${label}</button>`).join('')
      + '</div>';
    const count = (x) => fmtN(x);
    return `${weekTabs}<div class="two-col">
      <div><h4>Reviewers · ${fmtN(total)} rejections${state.reviewer ? ' (click again to clear)' : ''}</h4>
        ${bars([...byReviewer].map(([k, v]) => ({ key: k, label: k, value: v })), total, { attr: 'reviewer', selected: state.reviewer, fmt: count })}</div>
      <div><h4>Rejection reasons${state.reviewer ? ` · ${esc(state.reviewer)}` : ''}</h4>
        ${bars([...byReason].map(([k, v]) => ({ key: k, label: k, value: v })), reasonTotal, { fmt: count, color: COLOR.rejected })}</div>
    </div><p class="panel-note">Weeks run Monday to Sunday by the date the check was received, cut at the start and end of the
      month so they add up to the Rejected boxes. Counts of checks across all segments: the reviewer file has no segment or dollar amount.</p>`;
  }

  function daysSection(p, queue) {
    const xs = timingFor(p).filter((r) => r.queue === queue && r.decision === 'deposited').map((r) => r.days);
    const n = xs.length;
    const buckets = Array(11).fill(0);
    xs.forEach((d) => { buckets[Math.min(d, 10)] += 1; });
    const shares = buckets.map((b) => (n ? b / n : 0));
    const max = Math.max(...shares, 0.0001);
    const within2 = n ? xs.filter((d) => d <= 2).length / n : null;
    const stat = (k, v) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`;
    const p90 = percentile(xs, 0.9);
    return `<div class="stats">${stat('Deposits', fmtN(n))}${stat('Median', fmtDays(median(xs)))}`
      + `${stat('90th percentile', fmtDays(p90))}${stat('Within 2 business days', fmtP(within2))}</div>`
      + `<div class="columns" role="img" aria-label="Share of deposits by business days to funds available">${shares.map((s, i) =>
        `<div class="col" title="${i === 10 ? '10+' : i} business days: ${fmtN(buckets[i])} deposits"><span class="pct">${s > 0 ? fmtP(s, s < 0.1 ? 1 : 0) : ''}</span>`
        + `<div class="bar" style="height:${((s / max) * 85).toFixed(1)}%"></div></div>`).join('')}</div>`
      + `<div class="col-labels">${buckets.map((_, i) => `<span>${i === 10 ? '10+' : i}</span>`).join('')}</div>`
      + `<p class="panel-note">Business days from receipt to funds available (weekdays, excluding US federal holidays), for deposited checks.
        Checks whose hold had not ended by the data cut-off are not counted yet.</p>`;
  }

  function returnsSection(a) {
    const combos = [...a.combo.values()].map((c) => {
      const [reason, bank, entered, assigned] = c.key.split('||');
      return { reason, bank, analyst: state.retMode === 'entered' ? entered : assigned, value: m(c) };
    });
    const byAnalyst = new Map();
    combos.forEach((c) => byAnalyst.set(c.analyst, (byAnalyst.get(c.analyst) || 0) + c.value));
    if (state.analyst && !byAnalyst.has(state.analyst)) state.analyst = null;
    const scoped = combos.filter((c) => !state.analyst || c.analyst === state.analyst);
    const total = combos.reduce((s, c) => s + c.value, 0);
    const scopedTotal = scoped.reduce((s, c) => s + c.value, 0);
    const sumBy = (rows, f) => { const mp = new Map(); rows.forEach((r) => mp.set(r[f], (mp.get(r[f]) || 0) + r.value)); return mp; };
    const who = state.retMode === 'entered' ? 'Analyst who entered the reason' : 'Assigned analyst';
    let right;
    if (state.reason) {
      const rows = scoped.filter((c) => c.reason === state.reason);
      const rt = rows.reduce((s, c) => s + c.value, 0);
      right = `<div class="back-row"><button type="button" class="link-button" data-action="reason-back">← Back to reasons</button></div>
        <h4>Returning banks · ${esc(state.reason)}${state.analyst ? ` · ${esc(state.analyst)}` : ''}</h4>
        ${bars([...sumBy(rows, 'bank')].map(([k, v]) => ({ key: k, label: k, value: v })), rt, { color: COLOR.returned })}`;
    } else {
      right = `<h4>Return reasons${state.analyst ? ` · ${esc(state.analyst)}` : ''} · click one for its banks</h4>
        ${bars([...sumBy(scoped, 'reason')].map(([k, v]) => ({ key: k, label: k, value: v })), scopedTotal, { attr: 'reason', color: COLOR.returned })}`;
    }
    return `<div class="two-col">
      <div><h4>${who}${state.analyst ? ' (click again to clear)' : ''}</h4>
        ${bars([...byAnalyst].map(([k, v]) => ({ key: k, label: k, value: v })), total, { attr: 'analyst', selected: state.analyst })}</div>
      <div>${right}</div></div>
      <p class="panel-note">Returns are counted in the period the check was received and deposited, whenever the return arrived.</p>`;
  }

  // ---------- auto-deny reasons
  function renderAutoDeny(a) {
    const reasons = [...a.adReason.values()].map((r) => ({ key: r.key, label: r.label, value: m(r) }));
    const total = val(a, 'auto_denied');
    const sorted = reasons.filter((r) => r.value > 0).sort((x, y) => y.value - x.value);
    if (!sorted.some((r) => r.key === state.adReason)) state.adReason = sorted.length ? sorted[0].key : null;
    const subs = [...a.adSub.values()].filter((s) => s.parent === state.adReason)
      .map((s) => ({ key: s.key, label: s.label, value: m(s) }));
    const subTotal = subs.reduce((s, x) => s + x.value, 0);
    $('#autodeny').innerHTML = `
      <div><h4>Reasons · ${fmtV(total)} auto-denied</h4>
        ${bars(reasons, total, { attr: 'ad-reason', selected: state.adReason, color: COLOR.auto })}</div>
      <div><h4>Sub-reasons${state.adReason ? ` · ${esc(state.adReason)}` : ''}</h4>
        ${state.adReason ? bars(subs, subTotal, { color: COLOR.auto }) : '<div class="empty-note">Nothing in this selection.</div>'}</div>`;
  }

  // ---------- overview trends
  function renderTrends() {
    charts.forEach((c) => c.destroy());
    charts = [];
    const card = $('#trends');
    card.hidden = state.tab !== 'overview';
    if (card.hidden) return;
    document.querySelectorAll('#grain button').forEach((b) => b.classList.toggle('active', b.dataset.grain === state.grain));

    const p = period();
    const bucket = (x) => (state.grain === 'month' ? x.month : mondayOf(x.date));
    const keys = new Set(); const flow = {}; const reasons = {}; const reasonTotals = new Map();
    for (const x of D.nodes) {
      if (x.segment !== state.segment || x.date < p.from || x.date > p.to) continue;
      const k = bucket(x);
      if (x.kind === 'flow') {
        keys.add(k);
        const f = flow[k] || (flow[k] = {});
        f[x.node] = (f[x.node] || 0) + m(x);
      } else if (x.kind === 'auto_deny_reason') {
        const r = reasons[k] || (reasons[k] = {});
        r[x.key] = (r[x.key] || 0) + m(x);
        reasonTotals.set(x.key, (reasonTotals.get(x.key) || 0) + m(x));
      }
    }
    const xs = [...keys].sort();
    const labels = xs.map((k) => (state.grain === 'month' ? `${MONTHS[Number(k.slice(5)) - 1]} ${k.slice(2, 4)}` : dayLabel(k, false)));
    const title = (items) => (items.length ? (state.grain === 'month' ? monthLabel(xs[items[0].dataIndex])
      : `Week of ${dayLabel(xs[items[0].dataIndex])}`) : '');
    const get = (k, id) => (flow[k] && flow[k][id]) || 0;
    const fmtAxis = (v) => (state.measure === 'count' ? fmtN(v) : usdShort.format(v));
    const base = (extra = {}) => ({
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { title } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
        y: { beginAtZero: true, grid: { color: GRID }, ticks: { color: MUTED, callback: fmtAxis } },
      },
      ...extra,
    });

    const line = (label, color, data) => ({
      label, data, borderColor: color, backgroundColor: color, borderWidth: 2,
      pointRadius: xs.length > 20 ? 0 : 3, pointHoverRadius: 4, tension: 0.25, spanGaps: true,
    });
    const legend = { display: true, position: 'bottom', labels: { boxWidth: 10, boxHeight: 2, color: MUTED } };

    // Share of received checks by outcome (each line is its own share, not stacked).
    const mix = [['deposited', 'Deposited', COLOR.deposited], ['auto_denied', 'Auto-denied', COLOR.auto],
      ['rejected', 'Rejected', COLOR.rejected]];
    charts.push(new Chart($('#chart-mix'), {
      type: 'line',
      data: {
        labels,
        datasets: mix.map(([id, label, color]) => line(label, color,
          xs.map((k) => (get(k, 'received') ? (get(k, id) / get(k, 'received')) * 100 : null)))),
      },
      options: base({
        plugins: {
          legend,
          tooltip: { callbacks: { title, label: (c) => `${c.dataset.label}: ${c.parsed.y == null ? '–' : `${c.parsed.y.toFixed(1)}%`} of received` } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
          y: { min: 0, max: 100, grid: { color: GRID }, ticks: { color: MUTED, callback: (v) => `${v}%` } },
        },
      }),
    }));

    const order = [...reasonTotals].sort((x, y) => y[1] - x[1]).map(([k]) => k);
    charts.push(new Chart($('#chart-reasons'), {
      type: 'line',
      data: {
        labels,
        datasets: order.map((r, i) => line(r, SERIES[i % SERIES.length], xs.map((k) => (reasons[k] && reasons[k][r]) || 0))),
      },
      options: base({
        plugins: { legend, tooltip: { callbacks: { title, label: (c) => `${c.dataset.label}: ${fmtV(c.parsed.y, true)}` } } },
      }),
    }));
  }

  // ------------------------------------------------------------------ events
  function onClick(e) {
    const t = e.target.closest('[data-tab],[data-measure],[data-segment],[data-grain],[data-action],[data-week],'
      + '[data-reviewer],[data-panel-tab],[data-ret-mode],[data-analyst],[data-reason],[data-ad-reason],.drill');
    if (!t) return;
    const d = t.dataset;
    if (t.classList.contains('drill')) { togglePanel(d.node); return; }
    if (d.tab) state.tab = d.tab;
    else if (d.measure) state.measure = d.measure;
    else if (d.segment) state.segment = d.segment;
    else if (d.grain) state.grain = d.grain;
    else if (d.week) { state.week = d.week; state.reviewer = null; }
    else if (d.reviewer) state.reviewer = state.reviewer === d.reviewer ? null : d.reviewer;
    else if (d.panelTab) state.panelTab = d.panelTab;
    else if (d.retMode) Object.assign(state, { retMode: d.retMode, analyst: null, reason: null });
    else if (d.analyst) state.analyst = state.analyst === d.analyst ? null : d.analyst;
    else if (d.reason) state.reason = d.reason;
    else if (d.adReason) state.adReason = d.adReason;
    else if (d.action === 'close-panel') state.panel = null;
    else if (d.action === 'reason-back') state.reason = null;
    else if (d.action === 'reset-range') { state.from = D.first; state.to = D.last; }
    render();
  }

  function onChange(e) {
    if (e.target.id !== 'from' && e.target.id !== 'to') return;
    let { value } = e.target;
    if (!value) value = e.target.id === 'from' ? D.first : D.last;
    value = value < D.first ? D.first : value > D.last ? D.last : value;
    state[e.target.id] = value;
    if (state.from > state.to) {
      if (e.target.id === 'from') state.to = state.from; else state.from = state.to;
    }
    render();
  }

  function start() {
    Promise.all([load('node_counts.csv'), load('timing_rows.csv'), load('reviewer_rejections.csv')])
      .then(init)
      .catch((err) => {
        $('#range').textContent = 'Could not load the data files. Serve this folder over HTTP (python -m http.server).';
        console.error(err);
      });
  }
  if (window.Papa && window.Chart) start(); else window.addEventListener('load', start);
})();
