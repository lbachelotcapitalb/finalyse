"""Génère un dashboard HTML autonome (façon Quantalys) à partir d'un result JSON.
SVG rendu côté Python + fine couche JS embarquée pour l'interactivité (tooltips
de survol sur les courbes, aucune dépendance externe, offline).

Usage : python frontend/build_dashboard.py result_deep.json frontend/dashboard.html
"""
import sys
import json

# couleurs des séries (courbes / scatter)
SERIES = {
    "Benchmark": "#94a3b8",
    "Min-drawdown": "#0ea5e9",
    "Profil prudent": "#10b981",
    "Profil equilibre": "#6366f1",
    "Profil dynamique": "#f59e0b",
}
ACCENT = "#0d9488"
# palette stable par actif (même actif → même couleur partout)
ASSET_COLORS = ["#0d9488", "#0ea5e9", "#6366f1", "#f59e0b", "#10b981", "#ec4899",
                "#8b5cf6", "#ef4444", "#14b8a6", "#f97316", "#3b82f6", "#a855f7",
                "#84cc16", "#06b6d4", "#e11d48", "#64748b"]


def pct(x, d=1):
    return f"{x*100:+.{d}f}%" if isinstance(x, (int, float)) else "—"


def _sy(v, lo, hi, top, bot):
    return (top + bot) / 2 if hi == lo else bot - (v - lo) / (hi - lo) * (bot - top)


# ---------------------------------------------------------------------------
# Courbes interactives : renvoie (svg, jsdata) — jsdata pilote les tooltips JS
# ---------------------------------------------------------------------------
def line_chart(courbes, field, W=560, H=260, zero_line=False):
    padL, padR, padT, padB = 44, 12, 12, 26
    names = list(courbes.keys())
    series = {n: [x * 100 for x in courbes[n][field]] for n in names}
    allv = [x for s in series.values() for x in s]
    lo, hi = min(allv), max(allv)
    if zero_line:
        hi, lo = max(hi, 0), min(lo, 0)
    span = (hi - lo) or 1
    lo -= span * 0.05
    hi += span * 0.05
    n = len(next(iter(series.values())))
    xs = [padL + i / max(n - 1, 1) * (W - padL - padR) for i in range(n)]
    dates = courbes[names[0]]["dates"]
    plotB = H - padB
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,sans-serif">']
    for k in range(5):
        yv = lo + (hi - lo) * k / 4
        y = _sy(yv, lo, hi, padT, plotB)
        p.append(f'<line x1="{padL}" y1="{y:.1f}" x2="{W-padR}" y2="{y:.1f}" stroke="#eef2f7"/>')
        p.append(f'<text x="{padL-6}" y="{y+3:.1f}" font-size="9" fill="#94a3b8" text-anchor="end">{yv:.0f}</text>')
    if zero_line:
        y0 = _sy(0, lo, hi, padT, plotB)
        p.append(f'<line x1="{padL}" y1="{y0:.1f}" x2="{W-padR}" y2="{y0:.1f}" stroke="#cbd5e1" stroke-dasharray="2 2"/>')
    anchors = {0: "start", n // 2: "middle", n - 1: "end"}
    for i in (0, n // 2, n - 1):
        p.append(f'<text x="{xs[i]:.0f}" y="{H-8}" font-size="9" fill="#94a3b8" text-anchor="{anchors[i]}">{dates[i][:7]}</text>')
    js_series = []
    for name in names:
        ys = [_sy(series[name][i], lo, hi, padT, plotB) for i in range(n)]
        pts = " ".join(f"{xs[i]:.1f},{ys[i]:.1f}" for i in range(n))
        col = SERIES.get(name, "#64748b")
        if field == "drawdown":
            area = f"{xs[0]:.1f},{_sy(0,lo,hi,padT,plotB):.1f} " + pts + f" {xs[-1]:.1f},{_sy(0,lo,hi,padT,plotB):.1f}"
            p.append(f'<polygon points="{area}" fill="{col}" opacity="0.12"/>')
        p.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8"/>')
        js_series.append({"name": name, "color": col,
                          "ys": [round(y, 1) for y in ys],
                          "vals": [round(series[name][i], 1) for i in range(n)]})
    p.append('<g class="crosshair"></g></svg>')
    jsdata = {"W": W, "H": H, "plotT": padT, "plotB": plotB, "dates": dates,
              "xs": [round(x, 1) for x in xs], "series": js_series,
              "unit": "%" if field == "drawdown" else "idx"}
    return "".join(p), jsdata


def scatter_risk_return(result, W=560, H=260):
    padL, padR, padT, padB = 44, 14, 14, 30
    pts = [("Benchmark", result["benchmark"]["in_sample"]["max_drawdown"], result["benchmark"]["in_sample"]["cagr"])]
    lbl = {"min_cdar": "Min-drawdown", "profil_prudent": "Prudent",
           "profil_equilibre": "Équilibré", "profil_dynamique": "Dynamique"}
    for k, p in result["portefeuilles"].items():
        if k in lbl:
            pts.append((lbl[k], p["in_sample"]["max_drawdown"], p["in_sample"]["cagr"]))
    merged = {}
    for name, dd, cg in pts:
        key = (round(dd, 3), round(cg, 3))
        merged[key] = (f"{merged[key][0]} = {name}" if key in merged else name, dd, cg)
    pts = list(merged.values())
    xhi = max(p[1] for p in pts) * 1.15
    ylo, yhi = min(0, min(p[2] for p in pts)), max(p[2] for p in pts) * 1.2
    X = lambda v: padL + v / (xhi or 1) * (W - padL - padR)
    Y = lambda v: _sy(v, ylo, yhi, padT, H - padB)
    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,sans-serif">']
    for k in range(5):
        xv, yv = xhi * k / 4, ylo + (yhi - ylo) * k / 4
        o.append(f'<text x="{X(xv):.0f}" y="{H-10}" font-size="9" fill="#94a3b8" text-anchor="middle">{xv*100:.0f}%</text>')
        o.append(f'<line x1="{padL}" y1="{Y(yv):.1f}" x2="{W-padR}" y2="{Y(yv):.1f}" stroke="#eef2f7"/>')
        o.append(f'<text x="{padL-6}" y="{Y(yv)+3:.1f}" font-size="9" fill="#94a3b8" text-anchor="end">{yv*100:.0f}%</text>')
    cmap = {"Benchmark": "#94a3b8", "Min-drawdown": "#0ea5e9", "Prudent": "#10b981",
            "Équilibré": "#6366f1", "Dynamique": "#f59e0b"}
    for name, dd, cg in pts:
        col = next((c for kk, c in cmap.items() if kk in name), "#64748b")
        o.append(f'<circle cx="{X(dd):.1f}" cy="{Y(cg):.1f}" r="6" fill="{col}"/>')
        o.append(f'<text x="{X(dd)+9:.1f}" y="{Y(cg)+3:.1f}" font-size="9.5" fill="#334155">{name}</text>')
    o.append("</svg>")
    return "".join(o)


def frontier_chart(result, W=560, H=230):
    fr = result.get("frontiere", [])
    if not fr:
        return "<p>—</p>"
    padL, padR, padT, padB = 44, 14, 12, 26
    xs, ys = [f["cdar_budget"] for f in fr], [f["cagr"] for f in fr]
    xlo, xhi, ylo, yhi = min(xs), max(xs), min(ys), max(ys)
    X = lambda v: padL + (v - xlo) / ((xhi - xlo) or 1) * (W - padL - padR)
    Y = lambda v: _sy(v, ylo - (yhi - ylo) * .1, yhi + (yhi - ylo) * .1, padT, H - padB)
    o = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,sans-serif">']
    for k in range(5):
        yv, xv = ylo + (yhi - ylo) * k / 4, xlo + (xhi - xlo) * k / 4
        o.append(f'<line x1="{padL}" y1="{Y(yv):.1f}" x2="{W-padR}" y2="{Y(yv):.1f}" stroke="#eef2f7"/>')
        o.append(f'<text x="{padL-6}" y="{Y(yv)+3:.1f}" font-size="9" fill="#94a3b8" text-anchor="end">{yv*100:.0f}%</text>')
        o.append(f'<text x="{X(xv):.0f}" y="{H-8}" font-size="9" fill="#94a3b8" text-anchor="middle">{xv*100:.0f}%</text>')
    o.append(f'<polyline points="{" ".join(f"{X(x):.1f},{Y(y):.1f}" for x,y in zip(xs,ys))}" fill="none" stroke="{ACCENT}" stroke-width="2"/>')
    for x, y in zip(xs, ys):
        o.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.5" fill="{ACCENT}"/>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------------------
# Allocations précises comparées (couleurs stables + barres + tableau)
# ---------------------------------------------------------------------------
def _asset_colors(result):
    order = []
    for pk in ("profil_prudent", "profil_equilibre", "profil_dynamique", "min_cdar", "hrp"):
        for a in result["portefeuilles"].get(pk, {}).get("poids", {}):
            if a not in order:
                order.append(a)
    return {a: ASSET_COLORS[i % len(ASSET_COLORS)] for i, a in enumerate(order)}


def alloc_compare(result):
    colors = _asset_colors(result)
    labels = result.get("univers", {})
    profiles = [("profil_prudent", "Prudent"), ("profil_equilibre", "Équilibré"),
                ("profil_dynamique", "Dynamique")]
    # union d'actifs, triée par poids max décroissant
    assets = list(colors.keys())
    def maxw(a):
        return max(result["portefeuilles"].get(pk, {}).get("poids", {}).get(a, 0) for pk, _ in profiles)
    assets = [a for a in assets if maxw(a) > 0]
    assets.sort(key=maxw, reverse=True)

    # barres empilées par profil (couleurs stables)
    bars = ""
    for pk, name in profiles:
        p = result["portefeuilles"].get(pk, {})
        poids = p.get("poids", {})
        segs = "".join(
            f'<div title="{labels.get(a,a)} {poids[a]*100:.1f}%" style="width:{poids[a]*100:.2f}%;background:{colors[a]}"></div>'
            for a in assets if poids.get(a, 0) > 0)
        s = p.get("in_sample", {})
        bars += (f'<div class="al-row"><div class="al-h">{name}'
                 f'<span>{pct(s.get("cagr"))}/an · perte max {pct(s.get("max_drawdown"))}</span></div>'
                 f'<div class="al-bar">{segs}</div></div>')

    # tableau comparatif : actif × profil
    head = "".join(f"<th>{name}</th>" for _, name in profiles)
    rows = ""
    for a in assets:
        cells = ""
        for pk, _ in profiles:
            w = result["portefeuilles"].get(pk, {}).get("poids", {}).get(a, 0)
            cells += f'<td>{w*100:.1f}%</td>' if w > 0 else '<td class="z">—</td>'
        rows += (f'<tr><td class="al-name"><i style="background:{colors[a]}"></i>'
                 f'{labels.get(a, a)}</td>{cells}</tr>')
    table = (f'<table class="al-tab"><thead><tr><th>Actif</th>{head}</tr></thead>'
             f'<tbody>{rows}</tbody></table>')
    return bars + table


def metrics_table(result):
    cols = [("cagr", "Rendt/an"), ("vol", "Volatilité"), ("sharpe", "Sharpe"),
            ("max_drawdown", "Perte max"), ("cdar95", "CDaR 95"), ("calmar", "Calmar")]
    order = [("benchmark", "Benchmark 60/40", result["benchmark"]["in_sample"])]
    names = {"min_cdar": "Min-drawdown", "hrp": "HRP", "minvar_lw": "Min-variance",
             "profil_prudent": "Prudent", "profil_equilibre": "Équilibré", "profil_dynamique": "Dynamique"}
    for k, l in names.items():
        if k in result["portefeuilles"]:
            order.append((k, l, result["portefeuilles"][k]["in_sample"]))
    head = "".join(f"<th>{h}</th>" for _, h in cols)
    body = ""
    for key, l, s in order:
        cls = "hl" if key == "profil_equilibre" else ("bm" if key == "benchmark" else "")
        tds = "".join((f"<td>{s.get(c) if s.get(c) is not None else '—'}</td>" if c in ("sharpe", "calmar")
                       else f"<td>{pct(s.get(c))}</td>") for c, _ in cols)
        body += f'<tr class="{cls}"><td class="nm">{l}</td>{tds}</tr>'
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
            f'<div><b>{pct(mc["proba_perte_capital"])}</b><span>proba de perte à 10 ans</span></div></div>')


def build(result):
    meta = result["meta"]
    courbes = result.get("courbes", {})
    charts = {}
    if courbes:
        perf_svg, charts["perf"] = line_chart(courbes, "equity")
        under_svg, charts["under"] = line_chart(
            {k: v for k, v in courbes.items() if k in ("Benchmark", "Profil equilibre")},
            "drawdown", H=190, zero_line=True)
    else:
        perf_svg = under_svg = "<p>(pas de courbes)</p>"
    legend = "".join(f'<span class="lg"><i style="background:{SERIES.get(n,"#64748b")}"></i>{n}</span>' for n in courbes)

    body = HTML_BODY.replace("{{source}}", str(meta.get("source", "?"))) \
        .replace("{{start}}", str(meta.get("start"))).replace("{{end}}", str(meta.get("end"))) \
        .replace("{{years}}", str(meta.get("years"))).replace("{{n}}", str(meta.get("n_assets"))) \
        .replace("{{bench}}", result["benchmark"]["definition"]) \
        .replace("{{perf}}", perf_svg).replace("{{under}}", under_svg).replace("{{legend}}", legend) \
        .replace("{{scatter}}", scatter_risk_return(result)).replace("{{frontier}}", frontier_chart(result)) \
        .replace("{{alloc}}", alloc_compare(result)).replace("{{metrics}}", metrics_table(result)) \
        .replace("{{mc}}", mc_block(result))
    script = "<script>const CHARTS=" + json.dumps(charts, ensure_ascii=False) + ";\n" + HOVER_JS + "</script>"
    return "<!doctype html><html lang=fr><head><meta charset=utf-8>" \
           "<meta name=viewport content='width=device-width,initial-scale=1'>" \
           "<title>finalyse — dashboard</title><style>" + CSS + "</style></head><body>" + body + script + "</body></html>"


CSS = """
:root{--accent:#0d9488}*{box-sizing:border-box}
body{margin:0;background:#f6f8fa;color:#0f172a;font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-variant-numeric:tabular-nums}
header{background:#fff;border-bottom:1px solid #e5e9f0;padding:18px 28px;display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
header h1{margin:0;font-size:20px;letter-spacing:-.02em}header h1 b{color:var(--accent)}
header .meta{color:#64748b;font-size:13px}
.wrap{max-width:1180px;margin:22px auto;padding:0 20px;display:grid;grid-template-columns:1fr 1fr;gap:18px}
.card{background:#fff;border:1px solid #e9edf3;border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px rgba(15,23,42,.03)}
.card.wide{grid-column:1/3}
.card h2{margin:0 0 10px;font-size:13px;font-weight:600;color:#334155;text-transform:uppercase;letter-spacing:.04em}
.card h2 small{font-weight:400;text-transform:none;letter-spacing:0;color:#94a3b8}
.chart{position:relative}
.chart svg{display:block;cursor:crosshair}
.tip{position:absolute;display:none;pointer-events:none;background:#0f172a;color:#fff;border-radius:8px;padding:8px 10px;font-size:11.5px;min-width:150px;box-shadow:0 6px 18px rgba(2,6,23,.25);z-index:5}
.tip-date{font-weight:600;margin-bottom:5px;color:#cbd5e1}
.tip-row{display:flex;align-items:center;gap:6px;line-height:1.7}
.tip-row i{width:9px;height:9px;border-radius:2px;display:inline-block}
.tip-row b{margin-left:auto;font-variant-numeric:tabular-nums}
.legend{margin-top:8px;display:flex;flex-wrap:wrap;gap:14px}
.lg{font-size:12px;color:#475569;display:flex;align-items:center;gap:6px}.lg i{width:11px;height:11px;border-radius:3px;display:inline-block}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 8px;text-align:right}th{color:#94a3b8;font-weight:500;font-size:11px}
td.nm,th:first-child{text-align:left}tbody tr{border-top:1px solid #f1f5f9}
tr.hl{background:#eef2ff}tr.hl td{font-weight:600}tr.bm td{color:#64748b}
.al-row{margin:10px 0}
.al-h{font-size:13px;font-weight:600;margin-bottom:5px;display:flex;justify-content:space-between}
.al-h span{font-weight:400;color:#94a3b8;font-size:12px}
.al-bar{display:flex;height:18px;border-radius:5px;overflow:hidden;background:#f1f5f9}.al-bar div{height:100%}
.al-tab{margin-top:14px}.al-tab td,.al-tab th{text-align:right}
.al-name{text-align:left!important;display:flex;align-items:center;gap:7px}
.al-name i{width:10px;height:10px;border-radius:3px;flex:0 0 auto}
.al-tab td.z{color:#cbd5e1}
.mc-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.mc-grid div{background:#f8fafc;border-radius:10px;padding:12px 14px}
.mc-grid b{display:block;font-size:22px;color:var(--accent)}.mc-grid span{font-size:12px;color:#64748b}
.note{grid-column:1/3;color:#94a3b8;font-size:12px;text-align:center;padding:4px}
"""

HTML_BODY = """
<header><h1><b>finalyse</b> · dashboard</h1>
<div class=meta>Source : {{source}} · Fenêtre {{start}} → {{end}} ({{years}} ans, {{n}} actifs) · Benchmark : {{bench}}</div></header>
<div class=wrap>
  <div class="card wide"><h2>Performance <small>(base 100 — survole la courbe)</small></h2>
    <div class="chart" data-chart="perf">{{perf}}<div class="tip"></div></div>
    <div class="legend">{{legend}}</div></div>
  <div class="card"><h2>Rendement vs perte max <small>chaque point = un portefeuille</small></h2>{{scatter}}</div>
  <div class="card"><h2>Frontière drawdown-efficiente</h2>{{frontier}}</div>
  <div class="card wide"><h2>Sous l'eau <small>(drawdown — survole)</small></h2>
    <div class="chart" data-chart="under">{{under}}<div class="tip"></div></div></div>
  <div class="card"><h2>Allocations précises comparées</h2>{{alloc}}</div>
  <div class="card"><h2>Projection Monte-Carlo <small>(équilibré, 10 ans)</small></h2>{{mc}}</div>
  <div class="card wide"><h2>Métriques (in-sample)</h2>{{metrics}}</div>
  <div class="note">finalyse — prototype de test. Données EODHD (total return). Chiffres in-sample, non contractuels.</div>
</div>"""

HOVER_JS = """
function fmt(v,u){return u==='%'?(v>=0?'+':'')+v.toFixed(1)+'%':Math.round(v).toLocaleString('fr-FR');}
document.querySelectorAll('.chart[data-chart]').forEach(function(el){
  var cfg=CHARTS[el.dataset.chart]; if(!cfg)return;
  var svg=el.querySelector('svg'), tip=el.querySelector('.tip'), cross=svg.querySelector('.crosshair');
  function move(e){
    var r=svg.getBoundingClientRect();
    var cx=(e.touches?e.touches[0].clientX:e.clientX)-r.left;
    var vbX=cx/r.width*cfg.W, i=0, best=1e9;
    for(var k=0;k<cfg.xs.length;k++){var d=Math.abs(cfg.xs[k]-vbX);if(d<best){best=d;i=k;}}
    var x=cfg.xs[i], g='<line x1="'+x+'" y1="'+cfg.plotT+'" x2="'+x+'" y2="'+cfg.plotB+'" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 3"/>';
    var html='<div class="tip-date">'+cfg.dates[i]+'</div>';
    cfg.series.forEach(function(s){
      g+='<circle cx="'+x+'" cy="'+s.ys[i]+'" r="3.5" fill="'+s.color+'" stroke="#fff" stroke-width="1"/>';
      html+='<div class="tip-row"><i style="background:'+s.color+'"></i>'+s.name+'<b>'+fmt(s.vals[i],cfg.unit)+'</b></div>';
    });
    cross.innerHTML=g; tip.innerHTML=html; tip.style.display='block';
    var px=x/cfg.W*r.width; tip.style.left=Math.min(px+14,r.width-168)+'px'; tip.style.top='6px';
  }
  svg.addEventListener('mousemove',move);
  svg.addEventListener('touchmove',function(e){move(e);e.preventDefault();},{passive:false});
  svg.addEventListener('mouseleave',function(){cross.innerHTML='';tip.style.display='none';});
});
"""


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "result_deep.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "frontend/dashboard.html"
    result = json.load(open(src))
    html = build(result)
    with open(dst, "w") as f:
        f.write(html)
    print(f"Dashboard écrit : {dst} ({len(html)//1024} Ko)")
