"""Mémoire d'amélioration indexée du modèle.

Chaque exécution du moteur s'enregistre ici : configuration (source, univers,
params, fenêtre) + résultats-clés (métriques par profil, honnêteté walk-forward,
Monte-Carlo). But : comparer les itérations dans le temps et faire progresser le
modèle sur des faits, pas des impressions.

- `journal/experiments.jsonl` : log append-only, une ligne = un run (git-friendly).
- `journal/INDEX.md` : classement régénéré (leaderboard par Calmar équilibré).
- `journal/LEARNINGS.md` : enseignements curés (édité à la main / par l'IA).

Requêter : `python -m finalyse.journal top` (classement) ou `... show <id>`.
"""
import os
import json
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL_DIR = os.path.join(_ROOT, "journal")
JSONL = os.path.join(JOURNAL_DIR, "experiments.jsonl")
INDEX = os.path.join(JOURNAL_DIR, "INDEX.md")


def _ensure():
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    if not os.path.exists(JSONL):
        open(JSONL, "a").close()


def _extract(result, note, hypothesis):
    meta = result.get("meta", {})
    def ins(name):
        s = result.get("portefeuilles", {}).get(name, {}).get("in_sample", {})
        return {"cagr": s.get("cagr"), "maxdd": s.get("max_drawdown"),
                "calmar": s.get("calmar"), "sharpe": s.get("sharpe")} if s else {}
    wf = result.get("walk_forward", {})
    def oos(name):
        e = wf.get(name, {})
        o = e.get("oos", {})
        rec = {"cagr": o.get("cagr"), "maxdd": o.get("max_drawdown"), "calmar": o.get("calmar")}
        if "honnetete" in e and e["honnetete"]:
            rec["honnete_ratio"] = e["honnetete"].get("ratio_realise_sur_promesse")
        return rec
    mc = result.get("monte_carlo_equilibre", {})
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": meta.get("source", "?"),
        "note": note, "hypothesis": hypothesis,
        "window": {"start": meta.get("start"), "end": meta.get("end"),
                   "years": meta.get("years"), "n_assets": meta.get("n_assets")},
        "params": result.get("params", {}),
        "benchmark": {"cagr": result.get("benchmark", {}).get("in_sample", {}).get("cagr"),
                      "maxdd": result.get("benchmark", {}).get("in_sample", {}).get("max_drawdown")},
        "portfolios": {n: ins(n) for n in ("min_cdar", "hrp", "minvar_lw",
                                           "profil_prudent", "profil_equilibre", "profil_dynamique")},
        "walk_forward": {n: oos(n) for n in ("min_cdar", "cdar_budget")},
        "montecarlo_equilibre": {"p50_multiple": mc.get("multiple_terminal", {}).get("p50"),
                                 "p95_maxdd": mc.get("max_drawdown", {}).get("p95")},
    }


def log_run(result, note="", hypothesis=""):
    """Enregistre un run et régénère l'index. Renvoie l'id attribué."""
    _ensure()
    with open(JSONL) as f:
        n = sum(1 for _ in f)
    rec = {"id": n + 1, **_extract(result, note, hypothesis)}
    with open(JSONL, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    regenerate_index()
    return rec["id"]


def load_all():
    _ensure()
    with open(JSONL) as f:
        return [json.loads(l) for l in f if l.strip()]


def _pct(x):
    return f"{x*100:+.1f}%" if isinstance(x, (int, float)) else "—"


def regenerate_index():
    runs = load_all()
    def calmar_eq(r):
        return r.get("portfolios", {}).get("profil_equilibre", {}).get("calmar") or -1
    ranked = sorted(runs, key=calmar_eq, reverse=True)
    lines = [
        "# INDEX des expériences finalyse", "",
        "Classement par **Calmar de l'équilibré** (rendement/perte-max — le juge de paix).",
        "Régénéré automatiquement par `finalyse.journal`. Ne pas éditer à la main.", "",
        "| # | source | ans | équil. CAGR | équil. MaxDD | équil. Calmar | bench MaxDD | note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in ranked:
        eq = r.get("portfolios", {}).get("profil_equilibre", {})
        lines.append(
            f"| {r['id']} | {r['source'][:22]} | {r['window'].get('years','?')} | "
            f"{_pct(eq.get('cagr'))} | {_pct(eq.get('maxdd'))} | {eq.get('calmar','—')} | "
            f"{_pct(r.get('benchmark',{}).get('maxdd'))} | {r.get('note','')[:40]} |")
    lines += ["", f"_{len(runs)} run(s) journalisé(s). Détail : `journal/experiments.jsonl`._", ""]
    _ensure()
    with open(INDEX, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "top"
    if cmd == "top":
        regenerate_index()
        print(open(INDEX).read())
    elif cmd == "show" and len(sys.argv) > 2:
        rid = int(sys.argv[2])
        for r in load_all():
            if r["id"] == rid:
                print(json.dumps(r, ensure_ascii=False, indent=2)); break
    else:
        print("usage: python -m finalyse.journal [top | show <id>]")
