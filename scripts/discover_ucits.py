"""Découvre les symboles EODHD des ETF UCITS cibles (colonne UCITS_TARGET du socle).
Cherche par nom, garde les meilleurs candidats ETF avec leur profondeur d'histo.
Sortie à recopier dans universe.UCITS_SYMBOLS. Usage : EODHD_API_TOKEN=... python scripts/discover_ucits.py
"""
from finalyse import data_eodhd as DE

# clé socle -> requêtes de recherche (ETF UCITS distribuables EU)
QUERIES = {
    "US_LARGE":   ["iShares Core S&P 500 UCITS", "CSPX"],
    "US_SMALL":   ["iShares MSCI World Small Cap UCITS", "iShares MSCI USA Small Cap UCITS"],
    "DEV_EXUS":   ["iShares Core MSCI World UCITS", "IWDA"],
    "EMERGING":   ["iShares Core MSCI EM IMI UCITS", "EIMI"],
    "TREAS_LONG": ["iShares USD Treasury Bond 20+yr UCITS", "DTLA"],
    "TREAS_MID":  ["iShares USD Treasury Bond 7-10yr UCITS", "IDTM"],
    "CORP_IG":    ["iShares USD Corporate Bond UCITS", "LQDE"],
    "HIGH_YIELD": ["iShares USD High Yield Corp Bond UCITS", "IHYU"],
    "GOLD":       ["iShares Physical Gold ETC", "SGLN"],
    "COMMOD":     ["iShares Diversified Commodity Swap UCITS", "ICOM"],
    "REIT":       ["iShares Developed Markets Property Yield UCITS", "IWDP"],
    "TIPS":       ["iShares USD TIPS UCITS", "ITPS"],
}

print("Découverte des symboles UCITS (EODHD) :\n")
for key, queries in QUERIES.items():
    found = None
    for q in queries:
        try:
            hits = DE.search(q, limit=6)
        except Exception:
            continue
        etfs = [h for h in hits if str(h.get("Type", "")).upper() == "ETF"]
        # préfère les places EU (LSE, XETRA, Euronext, MI, AS, PA)
        pref = [h for h in etfs if h.get("Exchange") in ("LSE", "XETRA", "MI", "AS", "PA", "F", "SW")]
        cand = (pref or etfs or hits)
        if cand:
            found = cand[0]
            break
    if not found:
        print(f"  {key:<11} AUCUN candidat")
        continue
    sym = f"{found.get('Code')}.{found.get('Exchange')}"
    try:
        d = DE.history_depth(sym, start="1999-01-01")
        depth = f"{d['annees']} ans ({d['start']})"
    except Exception as e:
        depth = f"histo? {str(e)[:30]}"
    print(f"  {key:<11} \"{sym}\"  ISIN={found.get('ISIN') or '—':<14} {depth}  {str(found.get('Name',''))[:44]}")
