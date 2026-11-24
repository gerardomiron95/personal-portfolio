/* Dictionary: definition lookup for tooltips, and the Dictionary tab. */
window.Dictionary = (function () {
  'use strict';
  let byColumn = {};

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function init(rows) {
    byColumn = {};
    rows.forEach((r) => { byColumn[r.column] = r; });
  }

  /** Plain-English definition plus methodology, for hover tooltips. */
  function tipFor(column) {
    const r = byColumn[column];
    return r ? `${r.plain_english}\n\nHow it's calculated: ${r.methodology}` : '';
  }

  function render(el, rows) {
    const body = rows.map((r) => `
      <tr class="${r.section === 'Scope' ? 'scope' : ''}">
        <td>${esc(r.column)}</td>
        <td>${esc(r.section)}</td>
        <td class="method">${esc(r.methodology)}</td>
        <td class="desc">${esc(r.plain_english)}</td>
      </tr>`).join('');
    el.innerHTML = `
      <table class="dictionary">
        <thead><tr><th>Column</th><th>Section</th><th>Methodology</th><th>Description</th></tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  }

  return { init, tipFor, render };
})();
