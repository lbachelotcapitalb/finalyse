"""Génère un dashboard HTML autonome (façon Quantalys) à partir d'un result JSON
du moteur. SVG rendu côté Python → aucune dépendance, aucun serveur, offline.

Usage : python frontend/build_dashboard.py result_deep.json frontend/dashboard.html
"""
import sys
import json

PALETTE = {
    "Benchmark": "#94a3b8",
    "Min-drawdown": "#0ea5e9",
    "Profil prudent": "#10b981",
    "Profil equilibre": "#6366f1",
    "Profil dynamique": "#f59e0b",
}
ACCENT = "#0d9488"


def pct(x, s=1):
    return f"{x*100:+.{s}f}%" if isinstance(x, (int, float)) else "—"


def _sy(v, lo, hi, top, bot):
    if hi == lo:
        return (top + bot) / 2
    return bot - (v - lo) / (hi - lo) * (bot - top)


def line_chart(courbes, field, W=560, H=260, rebase=True, zero_line=False):
    """Courbes multiples partageant le même axe x (dates)."""
    pad_l, pad_r, pad_t, pad_b = 44, 12, 12, 26
    names = list(courbes.keys())
    series = {}
    for n in names:
        v = courbes[n][field]
        series[n] = [x * 100 for x in v] if rebase and field == "equity" else \
                    [x * 100 for x in v]  # tout en %
    allv = [x for s in series.values() for x in s]
    lo, hi = min(allv), max(allv)
    if zero_line:
        hi = max(hi, 0)
        lo = min(lo, 0)
    span = (hi - lo) or 1
    lo -= span * 0.05
    hi += span * 0.05
    n = len(next(iter(series.values())))
    xs = [pad_l + i / max(n - 1, 1) * (W - pad_l - pad_r) for i in range(n)]
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,sans-serif">']
    # gridlines Y + labels
    for k in range(5):
        yv = lo + (hi - lo) * k / 4
        y = _sy(yv, lo, hi, pad_t, H - pad_b)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W-pad_r}" y2="{y:.1f}" stroke="#eef2f7"/>')
        parts.append(f'<text x="{pad_l-6}" y="{y+3:.1f}" font-size="9" fill="#94a3b8" text-anchor="end">{yv:.0f}</text>')
    if zero_line:
        y0 = _sy(0, lo, hi, pad_t, H - pad_b)
        parts.append(f'<line x1="{pad_l}" y1="{y0:.1f}" x2="{W-pad_r}" y2="{y0:.1f}" stroke="#cbd5e1" stroke-dasharray="2 2"/>')
    # dates (3 repères) — ancrage bord pour ne pas rogner le dernier
    dates = courbes[names[0]]["dates"]
    anchors = {0: "start", n // 2: "middle", n - 1: "end"}
    for i in (0, n // 2, n - 1):
        parts.append(f'<text x="{xs[i]:.0f}" y="{H-8}" font-size="9" fill="#94a3b8" text-anchor="{anchors[i]}">{dates[i][:7]}</text>')
    # lignes
    for name in names:
        pts = " ".join(f"{xs[i]:.1f},{_sy(series[name][i], lo, hi, pad_t, H-pad_b):.1f}" for i in range(n))
        col = PALETTE.get(name, "#64748b")
        fill = field == "drawdown"
        if fill:
            area = f"{xs[0]:.1f},{_sy(0,lo,hi,pad_t,H-pad_b):.1f} " + pts + f" {xs[-1]:.1f},{_sy(0,lo,hi,pad_t,H-pad_b):.1f}"
            parts.append(f'<polygon points="{area}" fill="{col}" opacity="0.12"/>')
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8"/>')
    parts.append("</svg>")
    return "".join(parts)


def scatter_risk_return(result, W=560, H=260):
    pad_l, pad_r, pad_t, pad_b = 44, 14, 14, 30
    pts = []
    b = result["benchmark"]["in_sample"]
    pts.append(("Benchmark", b["max_drawdown"], b["cagr"]))
    for k, p in result["portefeuilles"].items():
        s = p["in_sample"]
        label = {"min_cdar": "Min-drawdown", "profil_prudent": "Prudent",
                 "profil_equilibre": "Équilibré", "profil_dynamique": "Dynamique"}.get(k)
        if label:
            pts.append((label, s["max_drawdown"], s["cagr"]))
    # fusionne les points coïncidents (ex. Prudent == Min-drawdown)
    merged = {}
    for name, dd, cg in pts:
        k = (round(dd, 3), round(cg, 3))
        merged[k] = (f"{merged[k][0]} = {name}" if k in merged else name, dd, cg)
    pts = list(merged.values())
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    xlo, xhi = 0, max(xs) * 1.15
    ylo, yhi = min(0, min(ys)), max(ys) * 1.2
    def X(v): return pad_l + (v - xlo) / ((xhi - xlo) or 1) * (W - pad_l - pad_r)
    def Y(v): return _sy(v, ylo, yhi, pad_t, H - pad_b)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,sans-serif">']
    for k in range(5):
        xv = xlo + (xhi - xlo) * k / 4
        out.append(f'<text x="{X(xv):.0f}" y="{H-10}" font-size="9" fill="#94a3b8" text-anchor="middle">{xv*100:.0f}%</text>')
        yv = ylo + (yhi - ylo) * k / 4
        out.append(f'<line x1="{pad_l}" y1="{Y(yv):.1f}" x2="{W-pad_r}" y2="{Y(yv):.1f}" stroke="#eef2f7"/>')
        out.append(f'<text x="{pad_l-6}" y="{Y(yv)+3:.1f}" font-size="9" fill="#94a3b8" text-anchor="end">{yv*100:.0f}%</text>')
    cmap = {"Benchmark": "#94a3b8", "Min-drawdown": "#0ea5e9", "Prudent": "#10b981",
            "Équilibré": "#6366f1", "Dynamique": "#f59e0b"}
    for name, dd, cg in pts:
        col = next((c for k, c in cmap.items() if k in name), "#64748b")
        out.append(f'<circle cx="{X(dd):.1f}" cy="{Y(cg):.1f}" r="6" fill="{col}"/>')
        out.append(f'<text x="{X(dd)+9:.1f}" y="{Y(cg)+3:.1f}" font-size="9.5" fill="#334155">{name}</text>')
    out.append("</svg>")
    return "".join(out)


def frontier_chart(result, W=560, H=230):
    fr = result.get("frontiere", [])
    if not fr:
        return "<p>—</p>"
    pad_l, pad_r, pad_t, pad_b = 44, 14, 12, 26
    xs = [f["cdar_budget"] for f in fr]
    ys = [f["cagr"] for f in fr]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    def X(v): return pad_l + (v - xlo) / ((xhi - xlo) or 1) * (W - pad_l - pad_r)
    def Y(v): return _sy(v, ylo - (yhi-ylo)*.1, yhi + (yhi-ylo)*.1, pad_t, H - pad_b)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,sans-serif">']
    for k in range(5):
        yv = ylo + (yhi - ylo) * k / 4
        out.append(f'<line x1="{pad_l}" y1="{Y(yv):.1f}" x2="{W-pad_r}" y2="{Y(yv):.1f}" stroke="#eef2f7"/>')
        out.append(f'<text x="{pad_l-6}" y="{Y(yv)+3:.1f}" font-size="9" fill="#94a3b8" text-anchor="end">{yv*100:.0f}%</text>')
        xv = xlo + (xhi - xlo) * k / 4
        out.append(f'<text x="{X(xv):.0f}" y="{H-8}" font-size="9" fill="#94a3b8" text-anchor="middle">{xv*100:.0f}%</text>')
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{ACCENT}" stroke-width="2"/>')
    for x, y in zip(xs, ys):
        out.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.5" fill="{ACCENT}"/>')
    out.append(f'<text x="{(W)/2:.0f}" y="{H-1}" font-size="9" fill="#64748b" text-anchor="middle">budget CDaR (perte max autorisée) →</text>')
    out.append("</svg>")
    return "".join(out)


def alloc_bars(result):
    rows = []
    order = ["profil_prudent", "profil_equilibre", "profil_dynamique"]
    labels = {"profil_prudent": "Prudent", "profil_equilibre": "Équilibré", "profil_dynamique": "Dynamique"}
    palette = ["#0d9488", "#0ea5e9", "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
               "#10b981", "#ef4444", "#64748b", "#14b8a6", "#a855f7"]
    for k in order:
        p = result["portefeuilles"].get(k, {})
        poids = sorted(p.get("poids", {}).items(), key=lambda x: -x[1])
        seg = []
        x = 0
        for i, (asset, w) in enumerate(poids):
            col = palette[i % len(palette)]
            seg.append(f'<div title="{asset} {w*100:.0f}%" style="width:{w*100:.1f}%;background:{col}"></div>')
        rows.append(f'<div class="alloc-row"><div class="alloc-name">{labels[k]}<span>MaxDD {pct(p["in_sample"]["max_drawdown"])} · {pct(p["in_sample"]["cagr"])}/an</span></div>'
                    f'<div class="alloc-bar">{"".join(seg)}</div></div>')
    # légende compacte (union des actifs)
    return "".join(rows)


def metrics_table(result):
    cols = [("cagr", "Rendt/an"), ("vol", "Volatilité"), ("sharpe", "Sharpe"),
            ("max_drawdown", "Perte max"), ("cdar95", "CDaR 95"), ("calmar", "Calmar")]
    order = [("benchmark", "Benchmark 60/40", result["benchmark"]["in_sample"])]
    names = {"min_cdar": "Min-drawdown", "hrp": "HRP", "minvar_lw": "Min-variance",
             "profil_prudent": "Prudent", "profil_equilibre": "Équilibré", "profil_dynamique": "Dynamique"}
    for k, lbl in names.items():
        if k in result["portefeuilles"]:
            order.append((k, lbl, result["portefeuilles"][k]["in_sample"]))
    head = "".join(f"<th>{h}</th>" for _, h in cols)
    body = ""
    for key, lbl, s in order:
        cls = "hl" if key == "profil_equilibre" else ("bm" if key == "benchmark" else "")
        tds = ""
        for c, _ in cols:
            v = s.get(c)
            if c in ("sharpe", "calmar"):
                tds += f"<td>{v if v is not None else '—'}</td>"
            else:
                tds += f"<td>{pct(v)}</td>"
        body += f'<tr class="{cls}"><td class="nm">{lbl}</td>{tds}</tr>'
    return f'<table><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>'


def mc_block(result):
    mc = result.get("monte_carlo_equilibre", {})
    if not mc:
        return "—"
    mt, dd = mc["multiple_terminal"], mc["max_drawdown"]
    return (f'<div class="mc-grid">'
            f'<div><b>{mt["p50"]}×</b><span>capital médian à 10 ans</span></div>'
            f'<div><b>{mt["p5"]}× – {mt["p95"]}×</b><span>fourchette p5–p95</span></div>'
            f'<div><b>{pct(dd["p95"])}</b><span>perte max (p95)</span></div>'
            f'<div><b>{pct(mc["proba_perte_capital"])}</b><span>proba de perte à 10 ans</span></div>'
            f'</div>')


def build(result):
    meta = result["meta"]
    courbes = result.get("courbes", {})
    perf = line_chart(courbes, "equity", rebase=True) if courbes else "<p>(pas de courbes)</p>"
    under = line_chart({k: v for k, v in courbes.items() if k in ("Benchmark", "Profil equilibre")},
                       "drawdown", H=170, zero_line=True) if courbes else ""
    legend = "".join(f'<span class="lg"><i style="background:{PALETTE.get(n,"#64748b")}"></i>{n}</span>' for n in courbes)
    return TEMPLATE.format(
        source=meta.get("source", "?"), start=meta.get("start"), end=meta.get("end"),
        years=meta.get("years"), n=meta.get("n_assets"),
        perf=perf, legend=legend, under=under,
        scatter=scatter_risk_return(result), frontier=frontier_chart(result),
        alloc=alloc_bars(result), metrics=metrics_table(result), mc=mc_block(result),
        bench_def=result["benchmark"]["definition"])


TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>finalyse — dashboard de test</title>
<style>
:root{{--accent:#0d9488}}
*{{box-sizing:border-box}}
body{{margin:0;background:#f6f8fa;color:#0f172a;font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-variant-numeric:tabular-nums}}
header{{background:#fff;border-bottom:1px solid #e5e9f0;padding:18px 28px;display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}}
header h1{{margin:0;font-size:20px;letter-spacing:-.02em}}
header h1 b{{color:var(--accent)}}
header .meta{{color:#64748b;font-size:13px}}
.wrap{{max-width:1180px;margin:22px auto;padding:0 20px;display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.card{{background:#fff;border:1px solid #e9edf3;border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px rgba(15,23,42,.03)}}
.card.wide{{grid-column:1/3}}
.card h2{{margin:0 0 10px;font-size:13px;font-weight:600;color:#334155;text-transform:uppercase;letter-spacing:.04em}}
.card h2 small{{font-weight:400;text-transform:none;letter-spacing:0;color:#94a3b8}}
.legend{{margin-top:8px;display:flex;flex-wrap:wrap;gap:14px}}
.lg{{font-size:12px;color:#475569;display:flex;align-items:center;gap:6px}}
.lg i{{width:11px;height:11px;border-radius:3px;display:inline-block}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:7px 8px;text-align:right}}
th{{color:#94a3b8;font-weight:500;font-size:11px}}
td.nm,th:first-child{{text-align:left}}
tbody tr{{border-top:1px solid #f1f5f9}}
tr.hl{{background:#eef2ff}}tr.hl td{{font-weight:600}}
tr.bm td{{color:#64748b}}
.alloc-row{{margin:12px 0}}
.alloc-name{{font-size:13px;font-weight:600;margin-bottom:5px;display:flex;justify-content:space-between}}
.alloc-name span{{font-weight:400;color:#94a3b8;font-size:12px}}
.alloc-bar{{display:flex;height:20px;border-radius:5px;overflow:hidden}}
.alloc-bar div{{height:100%}}
.mc-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.mc-grid div{{background:#f8fafc;border-radius:10px;padding:12px 14px}}
.mc-grid b{{display:block;font-size:22px;color:var(--accent)}}
.mc-grid span{{font-size:12px;color:#64748b}}
.note{{grid-column:1/3;color:#94a3b8;font-size:12px;text-align:center;padding:4px}}
</style></head><body>
<header>
  <h1><b>finalyse</b> · dashboard de test</h1>
  <div class="meta">Source : {source} · Fenêtre {start} → {end} ({years} ans, {n} actifs) · Benchmark : {bench_def}</div>
</header>
<div class="wrap">
  <div class="card wide"><h2>Performance <small>(base 100, réinvestie)</small></h2>{perf}<div class="legend">{legend}</div></div>
  <div class="card"><h2>Rendement vs perte max <small>chaque point = un portefeuille</small></h2>{scatter}</div>
  <div class="card"><h2>Frontière drawdown-efficiente</h2>{frontier}</div>
  <div class="card wide"><h2>Sous l'eau <small>(drawdown — Benchmark vs Équilibré)</small></h2>{under}</div>
  <div class="card"><h2>Allocations par profil</h2>{alloc}</div>
  <div class="card"><h2>Projection Monte-Carlo <small>(équilibré, 10 ans)</small></h2>{mc}</div>
  <div class="card wide"><h2>Métriques (in-sample)</h2>{metrics}</div>
  <div class="note">finalyse — prototype de test. Données EODHD (total return). Chiffres in-sample, non contractuels.</div>
</div></body></html>"""


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "result_deep.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "frontend/dashboard.html"
    result = json.load(open(src))
    html = build(result)
    with open(dst, "w") as f:
        f.write(html)
    print(f"Dashboard écrit : {dst} ({len(html)//1024} Ko)")
