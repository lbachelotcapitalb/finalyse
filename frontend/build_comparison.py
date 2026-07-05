"""Dashboard de COMPARAISON « contrat actuel vs allocation optimale ».
Générique (schéma comparison JSON) — les données client restent hors repo.

Usage : python frontend/build_comparison.py result_contrat.json frontend/contrat.html
"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_dashboard as bd   # réutilise line_chart, pct, CSS, HOVER_JS, palette


def euros(n):
    return f"{n:,.0f} €".replace(",", " ")


def ddfmt(x):
    return f"−{abs(x)*100:.1f} %".replace(".", ",")   # perte affichée négative (doc client)


def alloc_bars(result):
    ports = result["portefeuilles"]
    names = list(ports.keys())
    assets = []
    for p in ports.values():
        for a in p["poids"]:
            if a not in assets:
                assets.append(a)
    colors = {a: bd.ASSET_COLORS[i % len(bd.ASSET_COLORS)] for i, a in enumerate(assets)}
    out = ""
    for nm in names:
        p = ports[nm]
        poids = sorted(p["poids"].items(), key=lambda x: -x[1])
        segs = "".join(f'<div title="{a} {w*100:.1f}%" style="width:{w*100:.2f}%;background:{colors[a]}"></div>'
                       for a, w in poids)
        s = p["in_sample"]
        out += (f'<div class="al-row"><div class="al-h" style="color:{p.get("color","#334155")}">{nm}'
                f'<span>{bd.pct(s["cagr"])}/an · perte max {ddfmt(s["max_drawdown"])}</span></div>'
                f'<div class="al-bar">{segs}</div></div>')
    # légende
    leg = "".join(f'<span class="lg"><i style="background:{colors[a]}"></i>{a}</span>' for a in assets)
    return out + f'<div class="legend" style="margin-top:10px">{leg}</div>'


def metrics_table(result):
    cols = [("cagr", "Rendt/an"), ("vol", "Volatilité"), ("max_drawdown", "Perte max"),
            ("cdar95", "CDaR 95"), ("sharpe", "Sharpe"), ("calmar", "Calmar")]
    head = "".join(f"<th>{h}</th>" for _, h in cols)
    body = ""
    for nm, p in result["portefeuilles"].items():
        s = p["in_sample"]
        tds = "".join((f"<td>{s.get(c)}</td>" if c in ("sharpe", "calmar")
                       else f"<td>{ddfmt(s.get(c))}</td>" if c == "max_drawdown"
                       else f"<td>{bd.pct(s.get(c))}</td>") for c, _ in cols)
        dot = f'<span style="color:{p.get("color","#334155")}">●</span> '
        body += f'<tr><td class="nm">{dot}{nm}</td>{tds}</tr>'
    return f'<table><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>'


def mc_block(result):
    out = ""
    for nm, p in result["portefeuilles"].items():
        mc = result["monte_carlo"][nm]
        out += (f'<div class="mccard"><div class="mct" style="color:{p.get("color")}">{nm}</div>'
                f'<div class="mcg"><div><b>{mc["multiple_terminal"]["p50"]}×</b><span>capital médian 10 ans</span></div>'
                f'<div><b>{ddfmt(mc["max_drawdown"]["p95"])}</b><span>perte max p95</span></div></div></div>')
    return out


def build(result):
    meta = result["meta"]
    courbes = result["courbes"]
    bd.SERIES["Contrat actuel"] = result["portefeuilles"]["Contrat actuel"]["color"]
    bd.SERIES["Allocation optimale"] = result["portefeuilles"]["Allocation optimale"]["color"]
    perf_svg, perf_js = bd.line_chart(courbes, "equity", W=720, H=300)
    under_svg, under_js = bd.line_chart(courbes, "drawdown", W=720, H=220, zero_line=True)
    rv = result["reveal"]; op = result["opportunite"]

    body = BODY.replace("{{titre}}", meta["titre"]).replace("{{encours}}", euros(meta["encours"])) \
        .replace("{{adhesion}}", meta.get("adhesion", "")).replace("{{start}}", meta["start"]) \
        .replace("{{end}}", meta["end"]).replace("{{years}}", str(meta["years"])).replace("{{note}}", meta["note"]) \
        .replace("{{dd_reel}}", ddfmt(rv["drawdown_reel"])).replace("{{dd_releve}}", ddfmt(rv["drawdown_releve"])) \
        .replace("{{pts}}", f"+{op['pts_an']}").replace("{{euros}}", euros(op["euros_10ans"])) \
        .replace("{{perf}}", perf_svg).replace("{{under}}", under_svg) \
        .replace("{{metrics}}", metrics_table(result)).replace("{{alloc}}", alloc_bars(result)) \
        .replace("{{mc}}", mc_block(result))
    charts = {"perf": perf_js, "under": under_js}
    script = "<script>const CHARTS=" + json.dumps(charts, ensure_ascii=False) + ";\n" + bd.HOVER_JS + "</script>"
    return ("<!doctype html><html lang=fr><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>finalyse — analyse de contrat</title><style>" + bd.CSS + EXTRA_CSS + "</style></head><body>"
            + body + script + "</body></html>")


EXTRA_CSS = """
.hl-row{grid-column:1/3;display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px}
.hl{background:#fff;border:1px solid #e9edf3;border-radius:14px;padding:16px 18px;text-align:center}
.hl b{display:block;font-size:26px;letter-spacing:-.02em}
.hl .sub{font-size:12px;color:#64748b;margin-top:2px}
.hl.bad b{color:#D33B4D}.hl.good b{color:#15924E}
.hl .cmp{font-size:12px;color:#94a3b8;margin-top:6px}
.mccard{margin-top:6px}.mct{font-size:12px;font-weight:600;margin-bottom:6px}
.mcg{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.mcg div{background:#f8fafc;border-radius:10px;padding:10px 12px}
.mcg b{display:block;font-size:20px;color:#0d9488}.mcg span{font-size:11.5px;color:#64748b}
"""

BODY = """
<header><h1><b>finalyse</b> · analyse de contrat</h1>
<div class=meta>{{titre}} · {{encours}} · adhésion {{adhesion}} · reconstruit {{start}} → {{end}} ({{years}} ans)</div></header>
<div class=wrap>
  <div class="hl-row">
    <div class="hl bad"><b>{{dd_reel}}</b><div class="sub">vrai risque de perte (reconstruit)</div><div class="cmp">le relevé affichait « {{dd_releve}} » (lissé)</div></div>
    <div class="hl good"><b>{{pts}} pts/an</b><div class="sub">manque à gagner à risque égal</div><div class="cmp">optimal vs contrat actuel</div></div>
    <div class="hl good"><b>{{euros}}</b><div class="sub">écart projeté sur 10 ans</div><div class="cmp">sur l'encours actuel</div></div>
  </div>
  <div class="card wide"><h2>Performance <small>(base 100 — survole la courbe)</small></h2>
    <div class="chart" data-chart="perf">{{perf}}<div class="tip"></div></div></div>
  <div class="card wide"><h2>Sous l'eau <small>(perte depuis le plus haut — survole)</small></h2>
    <div class="chart" data-chart="under">{{under}}<div class="tip"></div></div></div>
  <div class="card wide"><h2>Métriques — contrat actuel vs optimal</h2>{{metrics}}</div>
  <div class="card wide"><h2>Allocations comparées</h2>{{alloc}}</div>
  <div class="card wide"><h2>Projection Monte-Carlo <small>(10 ans, 2000 scénarios)</small></h2>{{mc}}</div>
  <div class="note">{{note}} — Chiffres non contractuels, à visée pédagogique.</div>
</div>"""


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "result_contrat.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "frontend/contrat.html"
    result = json.load(open(src))
    with open(dst, "w") as f:
        f.write(build(result))
    print(f"Dashboard écrit : {dst}")
