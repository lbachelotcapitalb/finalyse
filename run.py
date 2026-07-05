"""Démo bout-en-bout. Usage : python run.py [--eodhd|--deep|--synth] [--json out.json] [--note "..."]"""
import json
import sys
from finalyse import engine, journal


def fmt_pct(x):
    return f"{x*100:+.1f}%" if isinstance(x, (int, float)) else str(x)


def main():
    source = ("supabase_uc" if "--sb-uc" in sys.argv else
              "supabase_ucits" if "--sb-ucits" in sys.argv else
              "supabase" if "--supabase" in sys.argv else
              "eodhd_uc" if "--uc" in sys.argv else
              "eodhd_ucits" if "--ucits" in sys.argv else
              "eodhd_deep" if "--deep" in sys.argv else
              "eodhd" if "--eodhd" in sys.argv else
              "synthetic" if "--synth" in sys.argv else "auto")
    res = engine.run(verbose=True, source=source)
    src = res["meta"].get("source", "live (Stooq)")
    print(f"\n>>> SOURCE DE DONNÉES : {src}")

    print("\n" + "=" * 74)
    print("PORTEFEUILLES (in-sample) — CAGR / vol / Sharpe / MaxDD / CDaR95 / Calmar")
    print("=" * 74)
    b = res["benchmark"]["in_sample"]
    print(f"{'BENCHMARK 60/40':<26} {fmt_pct(b['cagr']):>8} {fmt_pct(b['vol']):>8} "
          f"{b['sharpe']:>6} {fmt_pct(b['max_drawdown']):>8} {fmt_pct(b['cdar95']):>8} {b['calmar']:>6}")
    print("-" * 74)
    for key, p in res["portefeuilles"].items():
        s = p["in_sample"]
        print(f"{key:<26} {fmt_pct(s['cagr']):>8} {fmt_pct(s['vol']):>8} "
              f"{s['sharpe']:>6} {fmt_pct(s['max_drawdown']):>8} {fmt_pct(s['cdar95']):>8} {s['calmar']:>6}")

    print("\nPOIDS par portefeuille :")
    for key, p in res["portefeuilles"].items():
        poids = "  ".join(f"{k}:{v*100:.0f}%" for k, v in sorted(p["poids"].items(), key=lambda x: -x[1]))
        print(f"  {key:<20} {poids}")

    print("\n" + "=" * 74)
    print("WALK-FORWARD (out-of-sample, 5a train / 1a test glissant)")
    print("=" * 74)
    for method, w in res["walk_forward"].items():
        s = w.get("oos", {})
        line = (f"{method:<14} folds={w['n_folds']:>2}  "
                f"CAGR {fmt_pct(s.get('cagr', float('nan'))):>7}  "
                f"MaxDD {fmt_pct(s.get('max_drawdown', float('nan'))):>7}  "
                f"Calmar {s.get('calmar', '—')}")
        if "honnetete" in w and w["honnetete"]:
            h = w["honnetete"]
            line += (f"   | honnêteté: CDaR_IS {fmt_pct(h['insample_cdar_moy'])} "
                     f"→ MaxDD_OOS {fmt_pct(h['oos_maxdd_moy'])} "
                     f"(x{h['ratio_realise_sur_promesse']})")
        print(line)

    print("\n" + "=" * 74)
    print("MONTE-CARLO — profil équilibré, 10 ans, 2000 sims (bootstrap stationnaire)")
    print("=" * 74)
    mc = res["monte_carlo_equilibre"]
    print(f"  Multiple capital   p5 {mc['multiple_terminal']['p5']}x | "
          f"médian {mc['multiple_terminal']['p50']}x | p95 {mc['multiple_terminal']['p95']}x")
    print(f"  Rendement annuel   p5 {fmt_pct(mc['rendement_annualise']['p5'])} | "
          f"médian {fmt_pct(mc['rendement_annualise']['p50'])} | p95 {fmt_pct(mc['rendement_annualise']['p95'])}")
    print(f"  Max drawdown       médian {fmt_pct(mc['max_drawdown']['p50'])} | "
          f"p95 {fmt_pct(mc['max_drawdown']['p95'])} | p99 {fmt_pct(mc['max_drawdown']['p99'])}")
    print(f"  Proba perte capital à 10 ans : {fmt_pct(mc['proba_perte_capital'])}")

    if "--json" in sys.argv:
        path = sys.argv[sys.argv.index("--json") + 1]
        with open(path, "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\nJSON écrit : {path}")

    # Journalisation automatique dans la mémoire d'amélioration indexée
    note = sys.argv[sys.argv.index("--note") + 1] if "--note" in sys.argv else ""
    rid = journal.log_run(res, note=note)
    print(f"Run journalisé #{rid} → journal/experiments.jsonl (voir journal/INDEX.md)")


if __name__ == "__main__":
    main()
