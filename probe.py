"""Sonde EODHD : (1) couverture des UC françaises classiques, (2) profondeur
d'historique (objectif 25 ans). Token lu dans EODHD_API_TOKEN.
Usage : EODHD_API_TOKEN=... python probe.py
"""
from finalyse import data_eodhd as DE
from finalyse import universe as U

print("=" * 78)
print("1) COUVERTURE UC FRANÇAISES CLASSIQUES (recherche par nom dans EODHD)")
print("=" * 78)
funds = [
    "Carmignac Patrimoine", "Carmignac Investissement",
    "DNCA Eurose", "DNCA Evolutif",
    "R-co Valor", "Comgest Monde", "Moneta Multi Caps",
    "Echiquier Agressor", "Sextant PEA Europe", "Edmond de Rothschild",
    "Tikehau Income Cross Assets", "Sycomore Sélection Responsable",
]
for q in funds:
    try:
        hits = DE.search(q, limit=6)
    except Exception as e:  # noqa: BLE001
        print(f"\n• {q:<32} ERREUR {e}")
        continue
    # garde les fonds (Type 'FUND' / 'ETF') avec ISIN
    fh = [h for h in hits if str(h.get("Type", "")).upper() in ("FUND", "ETF", "MUTUAL FUND")]
    show = fh or hits
    print(f"\n• {q}")
    if not show:
        print("    (aucun résultat)")
    for h in show[:3]:
        print(f"    {h.get('Code','?')}.{h.get('Exchange','?'):<8} "
              f"ISIN={h.get('ISIN') or '—':<14} {str(h.get('Type','')):<6} "
              f"{h.get('Country','')}/{h.get('Currency','')}  {str(h.get('Name',''))[:46]}")

print("\n" + "=" * 78)
print("2) PROFONDEUR D'HISTORIQUE — objectif 25 ans")
print("=" * 78)

print("\n(a) ETF actuels de l'univers (depuis 1999) — le plus jeune borne la fenêtre commune :")
starts = {}
for key, tick in U.TICKERS.items():
    sym = tick.upper()
    try:
        d = DE.history_depth(sym, start="1999-01-01")
        starts[key] = d["start"]
        print(f"    {key:<11} {sym:<8} {d['annees']:>5} ans  {d['start']} → {d['end']}")
    except Exception as e:  # noqa: BLE001
        print(f"    {key:<11} {sym:<8} ERREUR {str(e)[:50]}")
if starts:
    binding = max(starts.items(), key=lambda kv: kv[1])
    print(f"    → fenêtre commune bornée par {binding[0]} ({binding[1]}) ≈ "
          f"{2026 - int(binding[1][:4])} ans max avec les 12 ETF.")

print("\n(b) Proxys fonds longue histoire (mêmes expositions, VL depuis les années 80-90) :")
proxies = {
    "VFINX": "US large (Vanguard 500)", "NAESX": "US small",
    "VGTSX": "Dev ex-US", "VEIEX": "Émergents",
    "VUSTX": "Souverain long", "VFITX": "Souverain moyen",
    "VWESX": "Crédit IG", "VWEHX": "High yield",
    "VGSIX": "REIT", "VIPSX": "TIPS",
}
for sym, lbl in proxies.items():
    try:
        d = DE.history_depth(f"{sym}.US", start="1980-01-01")
        print(f"    {sym:<7} {lbl:<20} {d['annees']:>5} ans  {d['start']} → {d['end']}")
    except Exception as e:  # noqa: BLE001
        print(f"    {sym:<7} {lbl:<20} ERREUR {str(e)[:45]}")
for gsym in ("XAUUSD.FOREX", "GLD.US"):
    try:
        d = DE.history_depth(gsym, start="1980-01-01")
        print(f"    {gsym:<13} Or                {d['annees']:>5} ans  {d['start']} → {d['end']}")
        break
    except Exception:  # noqa: BLE001
        continue
