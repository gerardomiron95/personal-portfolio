#!/usr/bin/env python3
"""Build the Weekly Operations Performance Review deck (Banking Operations) as a static HTML preview.

    python3 generate_data.py      # data/*.csv (fixed seed)
    python3 build_deck.py         # index.html: 1920x1080 slides + speaker notes

Every number on a slide comes from figures.compute(); nothing is typed in.
Slides use inline styles only, so each one can be lifted into a slide tool as-is.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from figures import compute, reconcile

OUT = Path(__file__).parent / "index.html"

# ----------------------------------------------------------------------------- visual system
# Same greens as the portfolio site and the card dispute dashboard.
PAPER, CARD, LINE = "#f4f7f5", "#ffffff", "#e0e6e2"
INK, MUTED, BODY_TEXT = "#1c2a24", "#5f6b64", "#3d4a43"
ACCENT, ACCENT_DARK, ACCENT_LIGHT = "#1e6b4f", "#124532", "#9cc9b2"
POS, NEG, AMBER = "#1e6b4f", "#c23b22", "#9a6414"
POS_T, NEG_T, AMBER_T, GREY_T = "#e8f2ec", "#fae3df", "#fbf0d8", "#eef1ef"
COVER_BG = "linear-gradient(160deg, #1e6b4f 0%, #124532 100%)"
COVER_TEXT, COVER_ACCENT = "#f3f8f5", "#a8e0c0"
BODY = "Inter, 'Helvetica Neue', Arial, sans-serif"
DISPLAY = BODY
DEPT = "Banking Operations"
NUM = "font-variant-numeric:tabular-nums;"
CONTENT_W = 1920 - 2 * 128
FOOTER = "Northwind Bank · Illustrative data"
MINUS = "−"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ----------------------------------------------------------------------------- formatting
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve"]


def word(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else num(n)


def joined(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def esc(s) -> str:
    return html.escape(str(s))


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%".replace("-", MINUS)


def pts(x: float, digits: int = 1) -> str:
    """Signed percentage-point change from a difference of proportions."""
    v = round(x * 100, digits)
    sign = "+" if v > 0 else MINUS if v < 0 else "±"
    return f"{sign}{abs(v):.{digits}f} pts"


def ci(x: float) -> str:
    """A CI bound in points, keeping the sign of tiny values (e.g. -0.04 shows as -0.0, not 0.0)."""
    return f"{x * 100:+.1f}".replace("-", MINUS)


def num(n: float) -> str:
    return f"{int(round(n)):,}"


def mon(s: str) -> str:
    return MONTHS[d(s).month - 1]


def month_name(s: str) -> str:
    return d(s).strftime("%B")


def pval(p: float) -> str:
    return "p < 0.01" if p < 0.01 else f"p = {p:.2f}"


def mean_day(dist: list[int]) -> float:
    n = sum(dist)
    return sum(i * x for i, x in enumerate(dist)) / n if n else 0.0


def span(a: str, b: str) -> str:
    a, b = d(a), d(b)
    if (a.year, a.month) == (b.year, b.month):
        return f"{MONTHS[a.month - 1]} {a.day}–{b.day}"
    return f"{MONTHS[a.month - 1]} {a.day} – {MONTHS[b.month - 1]} {b.day}"


def long_date(s: str) -> str:
    x = d(s)
    return f"{MONTHS[x.month - 1]} {x.day}, {x.year}"


def full_date(s: str) -> str:
    x = d(s)
    return x.strftime("%B ") + f"{x.day}, {x.year}"


def week_span(monday: str) -> str:
    m = d(monday)
    return span(m.isoformat(), (m + dt.timedelta(days=6)).isoformat())


# ----------------------------------------------------------------------------- building blocks
def logo(cover: bool = False, size: int = 40) -> str:
    """Northwind Bank: a two-tone north-pointing needle in a rounded tile, beside the wordmark.

    Invented for this portfolio; not based on any real institution's mark.
    """
    tile, left, right, word_c = ((COVER_TEXT, ACCENT, ACCENT_DARK, COVER_TEXT) if cover
                                 else (ACCENT, "#ffffff", COVER_ACCENT, ACCENT))
    mark = (
        f'<svg width="{size}" height="{size}" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" '
        f'style="display:block;flex:none;">'
        f'<rect width="40" height="40" rx="10" fill="{tile}"/>'
        f'<polygon points="20,7 20,25 11,32" fill="{left}"/>'
        f'<polygon points="20,7 29,32 20,25" fill="{right}"/>'
        f'</svg>'
    )
    return (
        f'<div style="position:absolute;left:128px;top:52px;display:flex;align-items:center;gap:12px;">{mark}'
        f'<div style="font-size:24px;line-height:26px;font-weight:800;letter-spacing:-0.4px;color:{word_c};">'
        f'Northwind<span style="font-weight:500;"> Bank</span></div></div>'
    )


def frame(body: str, cover: bool = False) -> str:
    bg, color = (COVER_BG, COVER_TEXT) if cover else (PAPER, INK)
    foot = "rgba(243,248,245,0.65)" if cover else MUTED
    return (
        f'<div style="position:relative;width:1920px;height:1080px;overflow:hidden;background:{bg};'
        f'color:{color};font-family:{BODY};">'
        f'<div data-content style="position:absolute;left:128px;top:128px;width:{CONTENT_W}px;'
        f'display:flex;flex-direction:column;">{body}</div>'
        f'{logo(cover)}'
        f'<div data-footer style="position:absolute;left:128px;bottom:64px;font-size:22px;line-height:29px;'
        f'color:{foot};">{FOOTER}</div></div>'
    )


def header(section: str, title: str, lead: str) -> str:
    section = section.split(" · ")[0]
    return (
        f'<div style="font-size:22px;line-height:28px;font-weight:600;letter-spacing:3px;'
        f'text-transform:uppercase;color:{ACCENT};">{esc(DEPT)}'
        f'<span style="color:{MUTED};"> · {esc(section)}</span></div>'
        f'<div style="margin-top:16px;font-size:54px;line-height:64px;font-weight:700;letter-spacing:-1px;'
        f'color:{INK};max-width:1600px;">{esc(title)}</div>'
        f'<div style="margin-top:18px;font-size:28px;line-height:38px;color:{BODY_TEXT};max-width:1640px;">'
        f'{lead}</div>'
    )


def card(inner: str, width: int, title: str = "", sub: str = "", pad: int = 28, extra: str = "",
         badge: str = "") -> str:
    head = ""
    if title:
        head = (f'<div style="display:flex;align-items:center;gap:14px;font-size:25px;line-height:32px;'
                f'font-weight:600;color:{INK};">{esc(title)}{badge}</div>')
    if sub:
        head += f'<div style="font-size:20px;line-height:26px;color:{MUTED};margin-top:4px;">{sub}</div>'
    if head:
        head = f'<div style="margin-bottom:18px;">{head}</div>'
    return (f'<div style="box-sizing:border-box;width:{width}px;background:{CARD};border:1px solid {LINE};'
            f'border-radius:18px;padding:{pad}px;{extra}">{head}{inner}</div>')


def row(*items: str, gap: int = 32, top: int = 40) -> str:
    return (f'<div style="display:flex;gap:{gap}px;margin-top:{top}px;align-items:stretch;">'
            + "".join(items) + "</div>")


def callout(text: str, top: int = 24, tone: str = "accent", heading: str = "") -> str:
    fg, bg = {"accent": (ACCENT, POS_T), "pos": (POS, POS_T), "neg": (NEG, NEG_T),
              "amber": (AMBER, AMBER_T), "grey": (MUTED, GREY_T)}[tone]
    head = (f'<div style="font-size:19px;line-height:24px;font-weight:700;letter-spacing:2px;'
            f'text-transform:uppercase;color:{fg};margin-bottom:6px;">{esc(heading)}</div>') if heading else ""
    return (f'<div style="margin-top:{top}px;padding:16px 22px;background:{bg};border-radius:14px;'
            f'font-size:23px;line-height:32px;color:{INK};">{head}{text}</div>')


def inner_w(width: int, pad: int = 28) -> int:
    return width - 2 * pad - 2


def table(cols: list[tuple[str, str]], rows: list[list[str]], size: int = 22,
          row_styles: list[str] | None = None, vpad: int = 9) -> str:
    """cols: (header, align). Each column is widthed from its own header and values (~0.6 x font-size per char)."""
    widths = []
    for i, (h, _) in enumerate(cols):
        longest = max([len(h)] + [len(html.unescape(_strip(r[i]))) for r in rows])
        widths.append(int(0.6 * size * longest + 36))
    th = "".join(
        f'<th style="text-align:{a};padding:0 18px 10px;font-weight:600;font-size:{size - 2}px;color:{MUTED};'
        f'white-space:nowrap;border-bottom:2px solid {LINE};width:{w}px;">{esc(h)}</th>'
        for (h, a), w in zip(cols, widths))
    body = ""
    for k, r in enumerate(rows):
        st = row_styles[k] if row_styles else ""
        body += "<tr>" + "".join(
            f'<td style="text-align:{a};padding:{vpad}px 18px;white-space:nowrap;border-bottom:1px solid {LINE};'
            f'{NUM}{st}">{v}</td>' for v, (_, a) in zip(r, cols)) + "</tr>"
    return (f'<table style="border-collapse:collapse;font-size:{size}px;line-height:{size + 8}px;color:{INK};">'
            f'<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>')


def _strip(s: str) -> str:
    out, skip = [], False
    for ch in s:
        if ch == "<":
            skip = True
        elif ch == ">":
            skip = False
        elif not skip:
            out.append(ch)
    return "".join(out)


def tag(text: str, fg: str, bg: str) -> str:
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;font-size:17px;'
            f'line-height:24px;font-weight:600;color:{fg};background:{bg};">{esc(text)}</span>')


def svg(w: int, h: int, body: str) -> str:
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
            f'style="display:block;font-family:{BODY};">{body}</svg>')


def text(x, y, s, size=18, fill=MUTED, anchor="middle", weight=400) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}" style="{NUM}">{esc(s)}</text>')


# ----------------------------------------------------------------------------- slides
def slide_title(F: dict) -> tuple[str, str]:
    c = F["checks"]
    body = (
        f'<div style="text-align:center;margin-top:200px;">'
        f'<div style="font-size:24px;letter-spacing:4px;text-transform:uppercase;color:{COVER_ACCENT};'
        f'font-weight:600;">{esc(DEPT)}</div>'
        f'<div style="font-size:112px;line-height:120px;font-weight:700;letter-spacing:-2px;margin-top:28px;'
        f'color:{COVER_TEXT};">Weekly Operations<br>Performance Review</div>'
        f'<div style="font-size:48px;line-height:58px;font-weight:600;margin-top:36px;color:{COVER_ACCENT};">'
        f'{full_date(c["as_of"])}</div></div>'
    )
    notes = (
        f"A repeatable weekly review for {DEPT} at a fictional neobank, built from synthetic data. Every figure "
        "is computed from the CSVs at build time. Each section states its window: checks use "
        f"{span(c['cur_start'], c['cur_end'])} because the last two days in the file carry about a fifth of "
        "normal volume; early pay uses the latest complete week; card reissues use month to date against the "
        "same elapsed days of the prior month."
    )
    return frame(body, cover=True), notes


SECTIONS = ["Check deposits", "ACH early pay", "Card reissues"]


def section_cover(title: str, subtitle: str, tiles: list[tuple[str, str, str]], footnote: str = "") -> str:
    """Green section title page: department and section number, section name, three big numbers."""
    k = SECTIONS.index(title) + 1
    tw = (CONTENT_W - 2 * 64) // 3
    tile_html = "".join(
        f'<div style="width:{tw}px;">'
        f'<div style="font-size:104px;line-height:112px;font-weight:700;letter-spacing:-2px;{NUM}">{v}</div>'
        f'<div style="font-size:26px;line-height:36px;margin-top:12px;color:{COVER_ACCENT};{NUM}">{esc(a)}</div>'
        f'<div style="font-size:22px;line-height:30px;margin-top:8px;color:rgba(243,248,245,0.65);{NUM}">'
        f'{esc(b)}</div></div>' for v, a, b in tiles)
    foot = (f'<div style="font-size:22px;line-height:30px;margin-top:52px;color:rgba(243,248,245,0.6);">'
            f'{esc(footnote)}</div>') if footnote else ""
    body = (
        f'<div style="font-size:24px;letter-spacing:4px;text-transform:uppercase;color:{COVER_ACCENT};'
        f'font-weight:600;margin-top:40px;">{esc(DEPT)} · Section {k} of {len(SECTIONS)}</div>'
        f'<div style="font-size:112px;line-height:118px;font-weight:700;letter-spacing:-2px;margin-top:28px;">'
        f'{esc(title)}</div>'
        f'<div style="font-size:32px;line-height:44px;margin-top:28px;color:rgba(243,248,245,0.85);max-width:1400px;">'
        f'{esc(subtitle)}</div>'
        f'<div style="display:flex;gap:64px;margin-top:72px;">{tile_html}</div>{foot}'
    )
    return frame(body, cover=True)


def slide_checks_cover(F: dict) -> tuple[str, str]:
    c = F["checks"]
    cur, t = c["cur"], c["targets"]
    win = span(c["cur_start"], c["cur_end"])
    imm = joined([num(v) for v in c["immature_volume"]])
    tiles = [
        (pct(cur["kept"] / cur["n"]), f"of {num(cur['n'])} checks received were deposited and kept",
         f"{mon(c['pooled_span'][0])}–{mon(c['pooled_span'][1])} average {pct(c['pooled'])} · "
         f"target {pct(t['kept'], 0)}"),
        (pct(cur["auto"] / cur["n"]), f"auto-denied by Clearwave ({num(cur['auto'])} checks)",
         f"Target range {pct(t['auto'][0], 0)}–{pct(t['auto'][1], 0)}"),
        (pct(cur["reject"] / cur["n"]), f"rejected by an agent ({num(cur['reject'])} checks)",
         f"Target range {pct(t['reject'][0], 0)}–{pct(t['reject'][1], 0)}"),
    ]
    slide = section_cover(
        "Check deposits",
        f"Mobile checks received {win}, {d(c['cur_end']).year}, as a share of every check received.",
        tiles,
        f"{span(c['immature_days'][0], c['immature_days'][-1])} excluded: {imm} checks, against a typical "
        f"{num(c['median_day_volume'])} a day, so those days are still filling in.")
    notes = (
        "Three numbers carry the section: the share of checks that end up deposited and kept, and the two "
        "routes by which checks fail before that, Clearwave's automatic denials and agent rejections. All three "
        f"are shares of checks received in {win}. The days after that window are excluded because their "
        "volume shows they are still filling in."
    )
    return slide, notes


def slide_ach_cover(F: dict) -> tuple[str, str]:
    a = F["ach"]
    wk = week_span(a["latest_week"])
    lo, hi = a["band"]
    base_end = (d(a["base_weeks"][1]) + dt.timedelta(days=6)).isoformat()
    two_now, two_base = a["mix_latest"]["shares"][1], a["mix_base"]["shares"][1]
    tiles = [
        (pct(a["rate"]), f"of {num(a['latest']['deposits'])} direct deposits paid early",
         f"Week of {wk}"),
        (pct(a["median"]), "median early-pay rate, prior eight weeks",
         f"Range {pct(lo)}–{pct(hi)} · {span(a['base_weeks'][0], base_end)}"),
        (pct(two_now), "of early deposits arrived two days early",
         f"Prior eight weeks: {pct(two_base)}"),
    ]
    slide = section_cover(
        "ACH early pay",
        f"Direct deposits released to members before payday, for the latest complete week against the eight "
        f"before it.",
        tiles,
        "Early-pay rate: early deposits ÷ all direct deposits. Days-early mix: each bucket ÷ early deposits only.")
    notes = (
        "Early pay is the share of direct deposits made available before the employer's pay date. The section "
        f"compares the latest complete week ({wk}) with the eight complete weeks before it, and keeps two "
        "denominators apart: the rate is over all deposits, the days-early mix is over early deposits only."
    )
    return slide, notes


def slide_reissue_cover(F: dict) -> tuple[str, str]:
    r = F["reissues"]
    cur_l, prev_l = span(*r["cur_span"]), span(*r["prev_span"])
    tiles = [
        (num(r["n_cur"]), f"cards reissued {cur_l}", f"{num(r['n_prev'])} in {prev_l}, the same elapsed days"),
        (pct(r["ld_total"] / r["n_cur"]), "of this month's reissues were loss-driven",
         f"{num(r['ld_total'])} cards: lost, stolen or fraud"),
        (pct(r["repeat_share"]), "of loss-driven members had another within a year",
         f"{num(r['repeat'])} of {num(r['cohort'])} members"),
    ]
    slide = section_cover(
        "Card reissues",
        f"Debit cards reissued {cur_l}, {d(r['cur_span'][1]).year}, against the same days of "
        f"{month_name(r['prev_span'][0])}.",
        tiles,
        "Loss-driven: Lost, Stolen, Fraud (member reported) and Fraud (system detected).")
    notes = (
        "Card reissues are compared month to date against the same elapsed days of the prior month. The section "
        "first tests whether the reason mix moved, then follows the members behind this month's loss-driven "
        "reissues over a 12-month lookback, because a few weeks is too short to see anyone repeat."
    )
    return slide, notes


def trend_chart(c: dict, w: int, h: int) -> str:
    months = c["months"]
    cur = c["cur"]
    pts_ = [(mon(m["month"]), m["rate"], False) for m in months]
    pts_.append((f"{span(c['cur_start'], c['cur_end'])}", cur["kept"] / cur["n"], True))
    vals = [p[1] for p in pts_] + [c["pooled"]]
    lo = int(min(vals) * 50) / 50 - 0.01
    hi = int(max(vals) * 50 + 1) / 50 + 0.005
    left, right, top, bottom = 64, 56, 34, 40
    pw, ph = w - left - right, h - top - bottom
    inset = 34
    X = lambda i: left + inset + (pw - 2 * inset) * (i / (len(pts_) - 1))
    Y = lambda v: top + ph * (1 - (v - lo) / (hi - lo))
    out = []
    tick = lo
    step = 0.02 if hi - lo > 0.06 else 0.01
    tick = round(int(lo / step + 0.999) * step, 4)
    while tick <= hi:
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{Y(tick):.1f}" y2="{Y(tick):.1f}" stroke="{LINE}"/>')
        out.append(text(left - 12, Y(tick) + 6, f"{tick * 100:.0f}%", 18, MUTED, "end"))
        tick = round(tick + step, 4)
    ya = Y(c["pooled"])
    out.append(f'<line x1="{left}" x2="{left + pw}" y1="{ya:.1f}" y2="{ya:.1f}" stroke="{MUTED}" '
               f'stroke-width="2" stroke-dasharray="8 6"/>')
    full = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v, partial) in enumerate(pts_) if not partial)
    out.append(f'<polyline points="{full}" fill="none" stroke="{ACCENT}" stroke-width="3"/>')
    n = len(pts_)
    out.append(f'<line x1="{X(n - 2):.1f}" y1="{Y(pts_[-2][1]):.1f}" x2="{X(n - 1):.1f}" y2="{Y(pts_[-1][1]):.1f}" '
               f'stroke="{ACCENT}" stroke-width="3" stroke-dasharray="6 6"/>')
    for i, (lbl, v, partial) in enumerate(pts_):
        fill = CARD if partial else ACCENT
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="7" fill="{fill}" stroke="{ACCENT}" stroke-width="3"/>')
        out.append(text(X(i), Y(v) - 16, pct(v), 19, INK, "middle", 600))
        out.append(text(X(i), h - 10, lbl, 19, MUTED))
    return svg(w, h, "".join(out))


def slide_checks_funnel(F: dict) -> tuple[str, str]:
    c = F["checks"]
    cur, prev, T = c["cur"], c["prev_like"], c["tests"]
    win, pwin = span(c["cur_start"], c["cur_end"]), span(c["prev_start"], c["prev_like_end"])
    rate, prate = cur["kept"] / cur["n"], prev["kept"] / prev["n"]
    avg_lbl = f"{mon(c['pooled_span'][0])}–{mon(c['pooled_span'][1])} average"
    above = rate > c["pooled"]
    labels = {"kept": "Deposited and kept", "returned": "Deposited, returned", "auto": "Auto-denied",
              "reject": "Agent rejected", "pending": "Still pending"}
    head_sig = T["kept"]["significant"]
    early_prev = f"early {month_name(c['prev_start'])}"
    if head_sig:
        verdict = (f"a significant {'rise' if rate > prate else 'drop'} on {early_prev}")
    else:
        verdict = f"the gap to {early_prev} is within noise"
    title = f"Deposit rate is {pct(rate)}, {'above' if above else 'below'} the {avg_lbl}: {verdict}"
    lead = (f"<b>{num(cur['kept'])} of {num(cur['n'])}</b> checks deposited and kept, against {pct(prate)} for "
            f"{pwin}: {pts(rate - prate)}, " + ("significant at 95%." if head_sig else "not significant at 95%."))
    trows, styles = [], []
    for k in ("kept", "returned", "auto", "reject", "pending"):
        t = T[k]
        sig = tag("Yes", INK, AMBER_T) if t["significant"] else f'<span style="color:{MUTED};">No</span>'
        trows.append([labels[k], f"{pct(prev[k] / prev['n'])} ({num(prev[k])})",
                      f"{pct(cur[k] / cur['n'])} ({num(cur[k])})", pts(t["diff"]),
                      f"{ci(t['lo'])} to {ci(t['hi'])}", sig])
        styles.append("font-weight:600;" if k == "kept" else "")
    trows.append(["All checks received", f"100% ({num(prev['n'])})", f"100% ({num(cur['n'])})", "", "", ""])
    styles.append(f"color:{MUTED};")
    tbl = table([("Outcome", "left"), (pwin, "right"), (win, "right"), ("Change", "right"),
                 ("95% CI, pts", "right"), ("Significant", "left")], trows, 19, styles, 7)
    tw = 1000
    chart_w = CONTENT_W - tw - 28
    moved = [f"{labels[k].lower()} {'rose' if T[k]['diff'] > 0 else 'fell'} {pts(abs(T[k]['diff'])).lstrip('+')}"
             for k in ("kept", "returned", "auto", "reject", "pending") if T[k]["significant"]]
    if moved:
        note = (joined(moved)[0].upper() + joined(moved)[1:] + ", significant at 95%; nothing else moved."
                + ("" if head_sig else " The headline did not move, so none of these explains a change in it."))
    else:
        note = "No outcome moved significantly."
    body = (
        header("Check deposits · funnel", title, lead)
        + row(card(trend_chart(c, inner_w(chart_w, 24), 290), chart_w,
                   "Deposited and kept by month",
                   f"Dashed: {mon(c['pooled_span'][0])}–{mon(c['pooled_span'][1])} average, {pct(c['pooled'])}. "
                   "Open point: partial month.", pad=24),
              card(tbl, tw, f"Outcome split, {pwin} vs {win}",
                   "Same elapsed days; two-proportion z-test at 95%", pad=24), gap=28, top=30)
        + callout(f"{note} Returns are {pct(cur['returned'] / cur['deposited'])} of <i>deposited</i> checks "
                  f"({num(cur['returned'])} of {num(cur['deposited'])}).", 22, "amber" if moved else "grey",
                  "What moved" if moved else "Nothing moved")
    )
    out_months = [p for p in c["pchart"] if p["outside"]]
    k_out, k_all = len(out_months), len(c["pchart"])
    if k_out * 2 >= k_all:
        pchart_note = ("Month-to-month swings are wider than binomial sampling noise, so limits built on that "
                       "noise turn ordinary variation into alarms.")
    else:
        pchart_note = ("With so few months flagged the chart adds little over the average line, and it answers a "
                       "different question (is the process stable?) from the one the room asks.")
    notes = (
        f"Lead with the deposit rate. {win} is compared with {pwin}, the same elapsed days, not with all of "
        f"{month_name(c['prev_start'])}: a partial month against a full one is not like for like. The dashed line "
        f"is the pooled average of the complete months only ({mon(c['pooled_span'][0])}–"
        f"{mon(c['pooled_span'][1])}), a ratio of sums rather than a mean of monthly rates, and it is computed, so "
        f"it moves as months enter and leave the window. {win} sits {'above' if above else 'below'} it. "
        f"Each funnel row was tested with a two-proportion z-test and a 95% interval on the difference. "
        f"Pending is shown rather than dropped; it is {pct(cur['pending'] / cur['n'])} of {win}. "
        f"A control chart was tested and not used: with 3-sigma p-chart limits around the pooled rate, "
        f"{k_out} of {k_all} complete months fall outside ({', '.join(mon(p['month']) for p in out_months) or 'none'}). "
        f"{pchart_note} The plain average line answers whether this window is better or worse than usual."
    )
    return frame(body), notes


def device_bars(devs: list[dict], pwin: str, win: str, w: int) -> str:
    """Auto-denial rate by capture device, prior window against current, horizontal bars."""
    vmax = max(max(x["auto"]["p1"], x["auto"]["p2"]) for x in devs)
    lw, vw = 190, 120
    bw = w - lw - vw
    out = ""
    for x in devs:
        rows_ = ""
        for v, color, lbl in ((x["auto"]["p1"], ACCENT_LIGHT, pwin), (x["auto"]["p2"], ACCENT, win)):
            rows_ += (f'<div style="display:flex;align-items:center;height:30px;">'
                      f'<div style="width:{bw}px;"><div style="height:20px;width:{bw * v / vmax:.0f}px;'
                      f'background:{color};border-radius:4px;"></div></div>'
                      f'<div style="width:{vw}px;font-size:20px;{NUM}"><b>{pct(v)}</b></div></div>')
        sig = (tag("Significant", INK, AMBER_T) if x["auto"]["significant"]
               else f'<span style="font-size:17px;color:{MUTED};">not significant</span>')
        out += (f'<div style="display:flex;align-items:center;margin-top:18px;">'
                f'<div style="width:{lw}px;font-size:22px;font-weight:600;line-height:28px;">{esc(x["device"])}'
                f'<div style="margin-top:2px;">{sig}</div></div><div>{rows_}</div></div>')
    legend = (f'<div style="display:flex;gap:24px;font-size:18px;color:{MUTED};margin-top:18px;">'
              f'<span><span style="display:inline-block;width:14px;height:14px;background:{ACCENT_LIGHT};'
              f'border-radius:3px;margin-right:8px;"></span>{esc(pwin)}</span>'
              f'<span><span style="display:inline-block;width:14px;height:14px;background:{ACCENT};'
              f'border-radius:3px;margin-right:8px;"></span>{esc(win)}</span></div>')
    return out + legend


def slide_checks_device(F: dict) -> tuple[str, str]:
    c = F["checks"]
    devs = c["devices"]
    win, pwin = span(c["cur_start"], c["cur_end"]), span(c["prev_start"], c["prev_like_end"])
    total = c["total_change"]
    top = max(devs, key=lambda x: abs(x["contribution"]))
    sig = [x for x in devs if x["kept"]["significant"]]
    if len(sig) == 1 and sig[0] is top:
        title = (f"{top['device']} drove the change: the only capture device whose deposit rate moved "
                 f"significantly")
    elif not sig:
        title = "No single capture device moved significantly on its own"
    else:
        title = f"{joined([x['device'] for x in sig])} moved significantly; the others held"
    t = top
    lead = (f"<b>{top['device']}</b> auto-denials fell from {pct(t['auto']['p1'])} to {pct(t['auto']['p2'])} of "
            f"checks; image-quality denials alone went from {pct(t['image_quality']['p1'])} to "
            f"{pct(t['image_quality']['p2'])}." if t["auto"]["diff"] < 0 else
            f"<b>{top['device']}</b> auto-denials rose from {pct(t['auto']['p1'])} to {pct(t['auto']['p2'])} of checks.")
    rows_, styles = [], []
    for x in devs:
        k = x["kept"]
        rows_.append([esc(x["device"]), f"{num(x['prev']['n'])} / {num(x['cur']['n'])}",
                      pct(k["p1"]), pct(k["p2"]), pts(k["diff"]),
                      tag("Yes", INK, AMBER_T) if k["significant"] else f'<span style="color:{MUTED};">No</span>',
                      pts(x["contribution"])])
        styles.append("font-weight:600;" if x is top else "")
    rows_.append(["Device mix", "", "", "", "", "", pts(c["mix_effect"])])
    styles.append(f"color:{MUTED};")
    rows_.append(["All checks", f"{num(c['prev_like']['n'])} / {num(c['cur']['n'])}",
                  pct(c["prev_like"]["kept"] / c["prev_like"]["n"]), pct(c["cur"]["kept"] / c["cur"]["n"]),
                  pts(total), "", pts(total)])
    styles.append("font-weight:600;")
    tbl = table([("Capture device", "left"), ("Checks", "right"), (pwin, "right"), (win, "right"),
                 ("Change", "right"), ("Significant", "left"), ("Share of change", "right")], rows_, 20, styles, 8)
    lw = 1010
    rw = CONTENT_W - lw - 28
    share = t["contribution"] / total if total else 0
    body = (
        header("Check deposits · by capture device", title, lead)
        + row(card(tbl, lw, f"Deposited and kept by capture device, {pwin} vs {win}",
                   "Checks: prior / current window. Share of change: the device's share of checks times its "
                   "rate change, in points of the headline.", pad=24),
              card(device_bars(devs, pwin, win, inner_w(rw, 24)), rw, "Auto-denied by Clearwave",
                   "Share of each device's checks received", pad=24), gap=28, top=30)
        + callout(f"Of the {pts(total)} headline change, {top['device']} accounts for {pts(t['contribution'])} "
                  f"({pct(share, 0)}). The data shows <i>which</i> captures improved, not why: that needs the "
                  f"capture team, not this deck.", 22, "pos", "Where the change came from")
    )
    notes = (
        "The headline rate hides where a change comes from, so the funnel is split by capture device. Each device "
        f"is compared on the same elapsed days ({pwin} vs {win}) with a two-proportion z-test. The share-of-change "
        "column splits the headline movement into each device's rate change weighted by its share of current "
        "checks, plus a residual for the shift in device mix; the pieces add up to the headline. The data shows "
        "which captures stopped being auto-denied and for which reason; it does not record why, so the slide "
        "stops short of a cause."
    )
    return frame(body), notes


def target_bar(label: str, value: float, count: int, target, kind: str, w: int) -> str:
    """kind 'min': target is a floor; 'range': target is a band."""
    scale = 1.0
    track = w - 300 - 300
    pos = lambda v: track * v / scale
    if kind == "min":
        mark = (f'<div style="position:absolute;left:{pos(target):.0f}px;top:-10px;width:3px;height:64px;'
                f'background:{POS};"></div>'
                f'<div style="position:absolute;left:{pos(target) - 140:.0f}px;top:-40px;width:280px;text-align:center;'
                f'font-size:18px;color:{POS};font-weight:600;">Target {pct(target, 0)}</div>')
        tgt = f"Target ≥ {pct(target, 0)}"
        gap = target - value
        gap_txt = f"{pts(-gap).replace('+', '').replace(MINUS, '')} short" if gap > 0 else "on target"
    else:
        lo, hi = target
        mark = (f'<div style="position:absolute;left:{pos(lo):.0f}px;top:-6px;width:{max(pos(hi) - pos(lo), 4):.0f}px;'
                f'height:56px;background:{POS_T};border:2px solid {POS};box-sizing:border-box;"></div>')
        tgt = f"Target {pct(lo, 0)}–{pct(hi, 0)}"
        gap = value - hi
        gap_txt = f"{pts(gap).replace('+', '')} above range" if gap > 0 else "in range"
    ok = (value >= target) if kind == "min" else (target[0] <= value <= target[1])
    color = POS if ok else NEG
    return (
        f'<div style="display:flex;align-items:center;gap:0;margin-top:34px;">'
        f'<div style="width:300px;font-size:24px;line-height:30px;font-weight:600;">{esc(label)}'
        f'<div style="font-size:19px;font-weight:400;color:{MUTED};">{esc(tgt)}</div></div>'
        f'<div style="position:relative;width:{track}px;height:44px;background:#eef2f5;border-radius:6px;">'
        f'<div style="position:absolute;left:0;top:0;height:44px;width:{pos(value):.0f}px;background:{color};'
        f'border-radius:6px;"></div>{mark}</div>'
        f'<div style="width:300px;padding-left:24px;box-sizing:border-box;{NUM}">'
        f'<div style="font-size:30px;line-height:34px;font-weight:700;color:{color};">{pct(value)}</div>'
        f'<div style="font-size:19px;color:{MUTED};">{num(count)} checks · {esc(gap_txt)}</div></div></div>'
    )


def slide_checks_target(F: dict) -> tuple[str, str]:
    c = F["checks"]
    cur, t = c["cur"], c["targets"]
    win = span(c["cur_start"], c["cur_end"])
    kept, auto, rej = cur["kept"] / cur["n"], cur["auto"] / cur["n"], cur["reject"] / cur["n"]
    short = t["kept"] - kept
    auto_over, rej_over = auto - t["auto"][1], rej - t["reject"][1]
    bigger = "auto-denials" if auto_over >= rej_over else "agent rejections"
    title = (f"Deposited and kept is {pts(short).replace('+', '')} short of {pct(t['kept'], 0)}; "
             f"{bigger} are the wider gap to close" if short > 0 else
             f"Deposited and kept meets its {pct(t['kept'], 0)} target")
    lead = (f"Over {win}, auto-denials ran {pts(auto_over).replace('+', '')} above their {pct(t['auto'][1], 0)} "
            f"ceiling and agent rejections {pts(rej_over).replace('+', '')} above {pct(t['reject'][1], 0)}.")
    lw = 1040
    bars = (target_bar("Deposited and kept", kept, cur["kept"], t["kept"], "min", inner_w(lw))
            + target_bar("Auto-denied", auto, cur["auto"], t["auto"], "range", inner_w(lw))
            + target_bar("Agent rejected", rej, cur["reject"], t["reject"], "range", inner_w(lw)))
    rw = CONTENT_W - lw - 32
    reasons = c["auto_reasons"]
    total = sum(n for _, n in reasons)
    rmax = max(n for _, n in reasons)
    bw = inner_w(rw) - 250 - 150
    rrows = "".join(
        f'<div style="display:flex;align-items:center;margin-top:16px;font-size:21px;line-height:28px;">'
        f'<div style="width:250px;">{esc(k)}</div>'
        f'<div style="width:{bw}px;"><div style="height:24px;width:{bw * n / rmax:.0f}px;background:{NEG};'
        f'opacity:0.85;border-radius:4px;"></div></div>'
        f'<div style="width:150px;text-align:right;{NUM}"><b>{pct(n / total)}</b> '
        f'<span style="color:{MUTED};">({num(n)})</span></div></div>' for k, n in reasons)
    body = (
        header("Check deposits · against target", title, lead)
        + row(card(f'<div style="padding-top:0;">{bars}</div>', lw,
                   f"Share of checks received, {win}", "Bars are actuals; green marks the target or target range."),
              card(rrows, rw, "Why Clearwave auto-denied",
                   f"Share of {num(total)} auto-denials, {win}"), top=34)
        + callout(f"The {pct(t['kept'], 0)} target is the goal; the two ranges are the route to it. They do not "
                  f"resolve to a single output rate, so no modelled rate is shown.", 20, "grey", "How to read the targets")
    )
    notes = (
        f"The target is {pct(t['kept'], 0)} of checks deposited and kept. Auto-deny and agent-rejection ranges are "
        f"the levers that get there, not a forecast: pending and returned checks sit between them and the "
        f"headline, and the ranges do not resolve to one number, so the slide does not publish a modelled output "
        f"rate. {reasons[0][0]} is the largest auto-deny reason this window, at {pct(reasons[0][1] / total)} of "
        f"auto-denials."
    )
    return frame(body), notes


def queue_strip(ms: list[dict], labels: list[str], w: int, h: int) -> str:
    """Three months of day-0..5 decision shares side by side, median day highlighted."""
    groups = len(ms)
    ggap = 28
    gw = (w - ggap * (groups - 1)) / groups
    gap = 5
    nbins = len(ms[0]["dist"])
    bw = (gw - gap * (nbins - 1)) / nbins
    base = h - 58
    top_share = max(max((x / m["n"]) if m["n"] else 0 for x in m["dist"]) for m in ms) or 1
    out = []
    for g, (m, lbl) in enumerate(zip(ms, labels)):
        gx = g * (gw + ggap)
        med = m["median"]
        for i, cnt in enumerate(m["dist"]):
            sh = cnt / m["n"] if m["n"] else 0
            bh = (base - 26) * sh / top_share
            x = gx + i * (bw + gap)
            is_med = med is not None and float(med) == i
            out.append(f'<rect x="{x:.1f}" y="{base - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2" '
                       f'fill="{ACCENT if is_med else ACCENT_LIGHT}"/>')
            if is_med:
                out.append(text(x + bw / 2, base - bh - 6, f"{sh * 100:.0f}%", 15, ACCENT, weight=700))
            out.append(text(x + bw / 2, base + 17, str(i), 13, MUTED))
        out.append(f'<line x1="{gx:.1f}" x2="{gx + gw:.1f}" y1="{base:.1f}" y2="{base:.1f}" stroke="{LINE}"/>')
        med_txt = f"med {med:g}d" if med is not None else "no decisions"
        out.append(text(gx + gw / 2, h - 18, f"{lbl} · {med_txt}", 16, INK, weight=600))
        out.append(text(gx + gw / 2, h - 4, f"n = {num(m['n'])}", 14, MUTED))
    return svg(w, h, "".join(out))


def slide_checks_queues(F: dict) -> tuple[str, str]:
    c = F["checks"]
    Q, S = c["queues"], c["queue_shape_tests"]
    cur_lbl = span(c["cur_start"], c["cur_end"])
    shifted = [q for q, t in S.items() if t["significant"]]
    held = [q for q in Q if q not in shifted]
    slower = {q: mean_day(Q[q][-1]["dist"]) > mean_day(Q[q][-2]["dist"]) for q in shifted}
    if not shifted:
        title = "Decision times held: no queue's shape shifted against last month"
    else:
        moved = joined([f"{q} {'slowed' if slower[q] else 'sped up'}" for q in shifted])
        title = (f"{moved} in {month_name(c['cur_start'])}; "
                 + (f"{joined(held)} held steady" if held else "every queue moved"))
    lead = (f"Business days to decision by review queue, last three months: bars are day 0–"
            f"{len(Q['Instant'][0]['dist']) - 1}, the median day in <b>dark green</b>.")
    cw = (CONTENT_W - 2 * 28) // 3
    cards = []
    for q, ms in Q.items():
        labels = [mon(x["month"]) if k < len(ms) - 1 else cur_lbl for k, x in enumerate(ms)]
        first, last = ms[0]["median"], ms[-1]["median"]
        tone_fg, tone_bg = ((MUTED, GREY_T) if first == last else (POS, POS_T) if last < first else (AMBER, AMBER_T))
        badge = tag(f"{first:g}d → {last:g}d", tone_fg, tone_bg)
        cur = ms[-1]
        shares = [x / cur["n"] for x in cur["dist"]]
        i = max(range(len(shares) - 1), key=lambda k: shares[k] + shares[k + 1])
        mass = shares[i] + shares[i + 1]
        t = S[q]
        cutoff = i + 1 == len(shares) - 1 and mass > 0.6
        msg = (f"Mass sits on days {i}–{i + 1}: <b>{pct(mass, 0)}</b> of {cur_lbl} decisions"
               + (", a cutoff, not a slow average." if cutoff else "."))
        if t["significant"]:
            msg += (f" Mean {mean_day(ms[-2]['dist']):.1f} → <b>{mean_day(cur['dist']):.1f} days</b> "
                    f"against {mon(ms[-2]['month'])}.")
        small = [x for x in ms if x["n"] < 100]
        if small:
            msg += f" {len(small)} month(s) under 100 checks: too few to read a shift."
        verdict = (f'<div style="font-size:19px;line-height:26px;color:{MUTED};margin-top:4px;">'
                   f'Shape vs {mon(ms[-2]["month"])}: '
                   + ("significant shift" if t["significant"] else "no significant change")
                   + f' ({pval(t["p"])})</div>')
        inner = (queue_strip(ms, labels, inner_w(cw, 24), 196)
                 + callout(msg + verdict, 18, "amber" if (t["significant"] or cutoff) else "pos"))
        cards.append(card(inner, cw, q, pad=24, badge=badge))
    body = (header("Check deposits · time to decision", title, lead)
            + row(*cards, gap=28, top=30))
    notes = (
        "The distribution is the exhibit, not the median: a median can hold still while the shape moves, and "
        "only the shape shows whether decisions are piling up later. Each panel shows the share of reviewed "
        f"checks decided on day 0 to day {len(Q['Instant'][0]['dist']) - 1} after receipt, with the median day "
        "highlighted, and the badge shows the median in the first and latest month. "
        f"Shapes were compared between {mon(Q['Instant'][-2]['month'])} and {cur_lbl} with a chi-square test: "
        + "; ".join(f"{q} {pval(S[q]['p'])}" for q in Q)
        + ". Queue-months under 100 checks would be flagged and not read as a change; none fall under it here."
    )
    return frame(body), notes


def ach_rate_chart(a: dict, w: int, h: int) -> str:
    s = a["series"]
    lo, hi = a["band"]
    vals = [x["rate"] for x in s]
    ymin = min(vals + [lo]) - 0.004
    ymax = max(vals + [hi]) + 0.004
    left, right, top, bottom = 76, 24, 30, 44
    pw, ph = w - left - right, h - top - bottom
    X = lambda i: left + pw * i / (len(s) - 1)
    Y = lambda v: top + ph * (1 - (v - ymin) / (ymax - ymin))
    out = []
    t = round(int(ymin * 200 + 1) / 200, 4)
    while t <= ymax:
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{LINE}"/>')
        out.append(text(left - 10, Y(t) + 6, f"{t * 100:.1f}%", 17, MUTED, "end"))
        t = round(t + 0.005, 4)
    out.append(f'<rect x="{X(0):.1f}" y="{Y(hi):.1f}" width="{X(len(s) - 2) - X(0):.1f}" height="{Y(lo) - Y(hi):.1f}" '
               f'fill="{POS_T}" stroke="{POS}" stroke-dasharray="6 5"/>')
    out.append(text(X(0) + 10, Y(hi) - 10, f"Prior 8 weeks: {pct(lo)}–{pct(hi)}", 18, POS, "start", 600))
    out.append(f'<polyline points="{" ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))}" '
               f'fill="none" stroke="{ACCENT}" stroke-width="3"/>')
    for i, v in enumerate(vals):
        last = i == len(vals) - 1
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{7 if last else 5}" '
                   f'fill="{NEG if last and a["outside"] else ACCENT}"/>')
        if last:
            out.append(text(X(i) - 12, Y(v) + 6, pct(v), 20, NEG if a["outside"] else INK, "end", 700))
        if i % 2 == 0 or last:
            out.append(text(X(i), h - 12, f"{mon(s[i]['week'])} {d(s[i]['week']).day}", 16, MUTED))
    return svg(w, h, "".join(out))


def ach_mix_chart(a: dict, w: int, h: int) -> str:
    base, cur = a["mix_base"]["shares"], a["mix_latest"]["shares"]
    labels = [f"{k + 1} day{'s' if k else ''} early" for k in range(len(base))]
    top_v = max(base + cur)
    left, bottom, top = 10, 44, 34
    gw = (w - left) / len(base)
    bw = gw * 0.32
    ph = h - top - bottom
    out = []
    for i in range(len(base)):
        gx = left + gw * i + gw * 0.15
        for j, (v, color) in enumerate(((base[i], ACCENT_LIGHT), (cur[i], ACCENT))):
            x = gx + j * (bw + 8)
            bh = ph * v / top_v
            y = top + ph - bh
            zero = v == 0
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(bh, 0):.1f}" rx="3" fill="{color}"/>')
            out.append(text(x + bw / 2, y - 8, pct(v), 17, NEG if zero else INK, weight=700 if zero else 500))
        out.append(text(gx + bw + 4, h - 12, labels[i], 17, MUTED))
    out.append(f'<line x1="0" x2="{w}" y1="{top + ph:.1f}" y2="{top + ph:.1f}" stroke="{LINE}"/>')
    return svg(w, h, "".join(out))


def slide_ach(F: dict) -> tuple[str, str]:
    a = F["ach"]
    wk = week_span(a["latest_week"])
    base_span = span(a["base_weeks"][0], (d(a["base_weeks"][1]) + dt.timedelta(days=6)).isoformat())
    lo, hi = a["band"]
    up = a["rate"] > a["median"]
    if a["outside"]:
        title = (f"Early pay {'rose' if up else 'fell'} to {pct(a['rate'])}, "
                 f"{'above' if up else 'below'} its {pct(lo)}–{pct(hi)} range for the prior eight weeks")
    else:
        title = f"Early pay held at {pct(a['rate'])}, inside its range for the prior eight weeks"
    baseline = (f"{pct(lo)}–{pct(hi)} range of the prior eight weeks" if a["outside"]
                else f"{pct(a['median'])} median of the prior eight weeks")
    lead = (f"<b>{wk}</b>: {num(a['latest']['early'])} of {num(a['latest']['deposits'])} direct deposits paid "
            f"early, against a median of {pct(a['median'])} for the prior eight weeks.")
    lw = 880
    rw = CONTENT_W - lw - 32
    legend = (f'<div style="display:flex;gap:24px;font-size:18px;color:{MUTED};margin-top:6px;">'
              f'<span><span style="display:inline-block;width:14px;height:14px;background:{ACCENT_LIGHT};'
              f'border-radius:3px;margin-right:8px;"></span>Prior 8 weeks ({base_span})</span>'
              f'<span><span style="display:inline-block;width:14px;height:14px;background:{ACCENT};'
              f'border-radius:3px;margin-right:8px;"></span>Week of {wk}</span></div>')
    diff = a["rate"] - a["median"]
    shifts = [cur - base for cur, base in zip(a["mix_latest"]["shares"], a["mix_base"]["shares"])]
    gain = max(range(len(shifts)), key=lambda k: shifts[k])
    gain_lbl = f"{gain + 1}-day-early" if gain else "one-day-early"
    body = (
        header("ACH direct deposits · early pay", title, lead)
        + row(card(ach_rate_chart(a, inner_w(lw), 310), lw, "Early-pay rate by week",
                   "Denominator: all direct deposits that settled that week"),
              card(ach_mix_chart(a, inner_w(rw), 280) + legend, rw, "Days early, mix",
                   "Denominator: early deposits only"), top=30)
        + callout(f"The mix tilted to {gain_lbl} ({pts(shifts[gain])}), but a mix shift cannot move the rate: "
                  f"{'more' if up else 'fewer'} deposits arrived early at all, {pts(diff)} on the prior median.",
                  24, "pos" if up else "neg", "Rate and mix are different denominators")
    )
    notes = (
        "Two exhibits, two denominators, both labelled. The rate is early deposits over all deposits; the mix is "
        "each bucket over early deposits only. Mixing them makes the slide irreconcilable. "
        f"The baseline is reported as a range because the week falls outside it; if it fell inside, the median "
        f"({pct(a['median'])}) would be the fairer single number. Every bucket is shown, including any at zero."
    )
    return frame(body), notes


def slide_reissue_mix(F: dict) -> tuple[str, str]:
    r = F["reissues"]
    cur_l, prev_l = span(*r["cur_span"]), span(*r["prev_span"])
    biggest = max(r["mix"], key=lambda x: abs(x["pp"]))
    sig = [x for x in r["mix"] if x["test"]["significant"]]
    prev_m = month_name(r["prev_span"][0])
    if not sig:
        title = (f"Reissue reasons held steady against early {prev_m}: none moved more than "
                 f"{abs(biggest['pp']):.1f} points")
    elif len(sig) == 1:
        x = sig[0]
        title = (f"{x['reason']} reissues {'rose' if x['pp'] > 0 else 'fell'} {abs(x['pp']):.1f} points; "
                 f"no other reason moved significantly")
    else:
        title = f"{word(len(sig)).capitalize()} reissue reasons moved significantly against early {prev_m}"
    ld_share = r["ld_total"] / r["n_cur"]
    lead = (f"{num(r['n_cur'])} cards reissued {cur_l} against {num(r['n_prev'])} in {prev_l}; "
            f"loss-driven reasons are {pct(ld_share)} of this month.")
    rows_, styles = [], []
    mx = max(max(x["cur_share"], x["prev_share"]) for x in r["mix"])
    for x in r["mix"]:
        bar = (f'<div style="display:inline-block;vertical-align:middle;width:{430 * x["cur_share"] / mx:.0f}px;'
               f'height:16px;background:{NEG if x["loss_driven"] else ACCENT_LIGHT};border-radius:3px;"></div>')
        change = f"{x['pp']:+.1f} pts".replace("-", MINUS).replace("+0.0", "±0.0").replace(MINUS + "0.0", "±0.0")
        sig_cell = (tag("Yes", INK, AMBER_T) if x["test"]["significant"]
                    else f'<span style="color:{MUTED};">No</span>')
        rows_.append([esc(x["reason"]) + (" " + tag("Loss-driven", NEG, NEG_T) if x["loss_driven"] else ""),
                      f"{pct(x['prev_share'])} ({num(x['prev'])})", f"{pct(x['cur_share'])} ({num(x['cur'])})",
                      change, sig_cell, bar])
        styles.append("")
    rows_.append(["All reissues", f"100% ({num(r['n_prev'])})", f"100% ({num(r['n_cur'])})", "", "", ""])
    styles.append(f"color:{MUTED};")
    tbl = table([("Reason", "left"), (prev_l, "right"), (cur_l, "right"), ("Change", "right"),
                 ("Significant", "left"), (f"{cur_l} share", "left")], rows_, 20, styles, 6)
    body = (
        header("Card reissues · reason mix", title, lead)
        + row(card(tbl, CONTENT_W, f"Share of reissued cards, {prev_l} vs {cur_l}",
                   "Shares of each window's reissues; counts in brackets; two-proportion z-test at 95%",
                   pad=24), top=30)
    )
    notes = (
        f"The comparison is month to date against the same elapsed days of last month ({prev_l}), never against a "
        "full month, which would make every current-month count look low. Changes are in percentage points of "
        "share, with raw counts beside them, and each reason's share is tested with a two-proportion z-test, "
        "so a reason is only called a move if the test says so. Loss-driven reasons are Lost, Stolen and the two "
        "fraud reasons; the next slide follows the members behind them."
    )
    return frame(body), notes


def slide_reissue_repeat(F: dict) -> tuple[str, str]:
    r = F["reissues"]
    cur_l = span(*r["cur_span"])
    days_mtd = (d(r["cur_span"][1]) - d(r["cur_span"][0])).days + 1
    window_lbl = f"{long_date(r['look_span'][0])} – {long_date(r['look_span'][1])}"
    title = (f"About one in {word(round(1 / r['repeat_share']))} members with a loss-driven reissue this month "
             f"had another within a year")
    lead = (f"<b>{num(r['repeat'])} of {num(r['cohort'])}</b> members ({pct(r['repeat_share'])}) have two or more "
            f"loss-driven cards in the 12 months to {long_date(r['look_span'][1])}, holding "
            f"{num(r['repeat_cards'])} of the cohort's {num(r['cohort_cards'])} cards "
            f"({pct(r['repeat_cards'] / r['cohort_cards'], 0)}).")
    lw = 640
    order = ("Lost", "Fraud (member reported)", "Stolen", "Fraud (system detected)")
    defs = "".join(
        f'<div style="display:flex;justify-content:space-between;font-size:23px;line-height:44px;'
        f'border-bottom:1px solid {LINE};{NUM}"><span>{esc(k)}</span><b>{num(r["ld_counts"][k])}</b></div>'
        for k in order)
    defs += (f'<div style="display:flex;justify-content:space-between;font-size:23px;line-height:48px;{NUM}">'
             f'<span style="color:{MUTED};">Loss-driven cards, {esc(cur_l)}</span><b>{num(r["ld_total"])}</b></div>'
             f'<div style="font-size:20px;line-height:29px;color:{MUTED};margin-top:14px;">'
             f'Held by {num(r["cohort"])} members. Within {esc(cur_l)} alone '
             f'{"none" if r["month_only_repeat"] == 0 else "only " + num(r["month_only_repeat"])} of them '
             f'show a second card: {days_mtd} days is too short to see a repeat, so the lookback is 12 months.</div>')
    rw = CONTENT_W - lw - 32
    W, H = inner_w(rw), 380
    keys = list(r["buckets"])
    vmax = max(r["buckets"].values())
    gw = W / len(keys)
    bw = gw * 0.55
    ph = H - 124
    out = []
    for i, k in enumerate(keys):
        v = r["buckets"][k]
        bh = ph * v / vmax
        x = i * gw + (gw - bw) / 2
        y = 68 + ph - bh
        color = "#c5cfd8" if k == "1" else NEG
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" fill="{color}"/>')
        out.append(text(x + bw / 2, y - 26, num(v), 22, INK, weight=700))
        out.append(text(x + bw / 2, y - 6, pct(v / r["cohort"]), 17, MUTED))
        out.append(text(x + bw / 2, H - 30, k, 22, INK, weight=600))
    out.append(text(W / 2, H - 4, "Loss-driven cards per member, trailing 12 months", 18, MUTED))
    out.append(f'<line x1="0" x2="{W}" y1="{68 + ph:.1f}" y2="{68 + ph:.1f}" stroke="{LINE}"/>')
    body = (
        header("Card reissues · repeat members", title, lead)
        + row(card(defs, lw, "Loss-driven, defined", f"Reissue reasons counted, {cur_l}"),
              card(svg(W, H, "".join(out)), rw, f"{num(r['cohort'])} members with a loss-driven reissue {cur_l}",
                   f"Grey: first loss-driven card in a year. Red: repeat. Window {window_lbl}"), top=30)
    )
    notes = (
        f"Start from the members with a loss-driven reissue in {cur_l}, then count every loss-driven card each "
        f"has had in the trailing 12 months ({long_date(r['look_span'][0])} to {long_date(r['look_span'][1])}). "
        f"The window is 12 months on purpose: in a {days_mtd}-day window almost everyone shows one card, so the "
        f"concentration is invisible. Over a year, {pct(r['repeat_share'])} of the cohort are repeats and they "
        f"hold {pct(r['repeat_cards'] / r['cohort_cards'], 0)} of its loss-driven cards: a short, specific list "
        "for fraud review rather than a card-production problem."
    )
    return frame(body), notes


SLIDES = [
    ("title", slide_title), ("checks-cover", slide_checks_cover), ("checks-funnel", slide_checks_funnel),
    ("checks-device", slide_checks_device), ("checks-target", slide_checks_target),
    ("checks-queues", slide_checks_queues),
    ("ach-cover", slide_ach_cover), ("ach-early", slide_ach),
    ("reissue-cover", slide_reissue_cover), ("reissue-mix", slide_reissue_mix),
    ("reissue-repeat", slide_reissue_repeat),
]

SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weekly Operations Performance Review · Northwind Bank</title>
<meta name="description" content="Portfolio demo: a weekly operations review deck built from synthetic data.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  body { margin: 0; background: #e6ece8; font-family: Inter, system-ui, sans-serif; color: #121c26; }
  .bar { position: sticky; top: 0; z-index: 2; background: #124532; color: #f3f8f5; padding: 12px 24px;
         display: flex; justify-content: space-between; align-items: center; font-size: 14px; }
  .bar a { color: #a8e0c0; text-decoration: none; }
  .deck { max-width: 1280px; margin: 0 auto; padding: 24px; }
  .slide { margin: 0 0 28px; }
  .label { font-size: 13px; color: #51606e; margin: 0 0 6px; }
  .frame { position: relative; width: 100%; aspect-ratio: 16 / 9; overflow: hidden; border-radius: 6px;
           box-shadow: 0 2px 10px rgba(18, 28, 38, 0.12); background: #f4f6f8; }
  .frame > div { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
  details { background: #fff; border-radius: 0 0 6px 6px; padding: 10px 16px; font-size: 14px; line-height: 1.55;
            color: #3a4652; border: 1px solid #d9e0e6; border-top: 0; }
  summary { cursor: pointer; font-weight: 600; color: #121c26; }
</style>
</head>
<body>
<div class="bar"><span>Weekly Operations Performance Review · Northwind Bank Banking Operations (illustrative data)</span>
<a href="../">Back to portfolio</a></div>
<div class="deck">
__SLIDES__
</div>
<script>
  function fit() {
    document.querySelectorAll('.frame').forEach(function (f) {
      f.firstElementChild.style.transform = 'scale(' + (f.clientWidth / 1920) + ')';
    });
  }
  window.addEventListener('resize', fit);
  fit();
</script>
</body>
</html>
"""


def main() -> None:
    F = compute()
    bad = [label for ok, label in reconcile(F) if not ok]
    if bad:
        raise SystemExit("Reconciliation failed: " + "; ".join(bad))
    parts = []
    for k, (sid, fn) in enumerate(SLIDES, 1):
        slide_html, notes = fn(F)
        parts.append(
            f'<section class="slide" id="{sid}"><p class="label">{k} · {sid}</p>'
            f'<div class="frame">{slide_html}</div>'
            f'<details><summary>Speaker notes</summary><p>{esc(notes)}</p></details></section>')
    OUT.write_text(SHELL.replace("__SLIDES__", "\n".join(parts)))
    print(f"Wrote {OUT} ({len(SLIDES)} slides)")


if __name__ == "__main__":
    main()
