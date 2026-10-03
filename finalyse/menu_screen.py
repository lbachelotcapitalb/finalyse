"""Screening DIRECT du menu réel d'un contrat d'assurance-vie.

Pourquoi (audit du 03/10/2026). `run_contrats.py` croisait le menu du contrat
avec l'univers AV screené (`data/list_av.csv`). Or cet univers, reconstitué le
23/08, compte 32 fonds dont 23 fonds de pension britanniques (Aegon / Scottish
Equitable) qu'aucun contrat français ne distribue : l'intersection avec un vrai
menu tombait à quelques lignes, sous `--min-fonds`, et le contrat restait sans
allocation. On screene donc le menu LUI-MÊME, avec les critères du § C.8 :

  • historique couvrant la crise (série commençant avant `max_start`) ;
  • monétaires exclus (MaxDD ≈ 0 fausse le classement — piège n°1 du screening) ;
  • score composite en rangs-percentiles : rendement 22 % · Sharpe 24 % ·
    Calmar 24 % · CDaR 18 % · MaxDD 12 % (CDaR et MaxDD : plus bas = mieux) ;
  • classe d'actif déduite du libellé (le menu n'en porte pas).

Les rangs sont calculés DANS le menu : on compare les fonds que le client peut
réellement acheter, pas un palmarès extérieur. Biais assumé et signalé : le score
voit tout l'historique (même réserve que le screening générique).

`screen_menu` est pur (fetcher injectable) → testable hors-réseau.
"""
import re

import numpy as np

from . import metrics as m
from . import data as D

_WEIGHTS = {"cagr": 0.22, "sharpe": 0.24, "calmar": 0.24, "cdar95": 0.18, "max_drawdown": 0.12}
_LOWER_IS_BETTER = {"cdar95", "max_drawdown"}


def fund_classe(name):
    """Classe d'actif d'un fonds d'après son libellé. Du plus spécifique au plus
    générique ; 'monétaire' = à exclure."""
    n = (name or "").lower()
    if re.search(r"mon[ée]taire|money\s*market|tr[ée]sorerie|court\s*terme|short\s*term\s*money|"
                 r"\beonia\b|\bester\b|overnight|cash\b", n):
        return "monétaire"
    if re.search(r"\bscpi\b|\bopci\b|\bsci\b|immobili|real\s*estate|\breit|epra|property", n):
        return "immobilier"
    if re.search(r"\bgold\b|or\s+physique|mati[èe]res\s+premi[èe]res|commodit", n):
        return "or/matières"
    if re.search(r"patrimoine|flexible|allocation|diversifi|multi[\s-]?asset|multi[\s-]?actifs|"
                 r"prudent|[ée]quilibr|dynamique|mixte|balanced|absolute\s*return|rendement\s*absolu|"
                 r"global\s*macro|convertible", n):
        return "diversifié"
    if re.search(r"oblig|bond|cr[ée]dit|credit|fixed\s*income|high\s*yield|haut\s*rendement|"
                 r"\btaux\b|treasury|govt|government|souverain|aggregate|inflation", n):
        return "oblig"
    if re.search(r"emerging|[ée]mergent|china|chine|india|inde\b|asia|asie|latin|brazil|br[ée]sil", n):
        return "actions émergents"
    if re.search(r"japan|japon|topix|nikkei", n):
        return "actions Japon"
    if re.search(r"europe|\beuro\b|eurozone|zone\s*euro|emu|stoxx|\bcac\b|\bdax\b|france|french|"
                 r"allemagne|germany|uk\b|royaume", n):
        return "actions Europe"
    if re.search(r"s&p\s*500|nasdaq|dow\s*jones|\busa?\b|united\s*states|am[ée]rique|america", n):
        return "actions US"
    if re.search(r"world|monde|global|international|acwi", n):
        return "actions monde"
    return "actions/autre"


def _rank_pct(values, lower_is_better):
    v = np.asarray(values, float)
    order = (v if lower_is_better else -v).argsort().argsort()      # 0 = meilleur
    n = len(v)
    return 1.0 - order / max(n - 1, 1)                               # 1 = meilleur


def screen_menu(menu, fetcher, max_start="2008-03-31", min_weeks=260, verbose=False):
    """menu : liste de {isin, label}. fetcher(symbole EODHD) -> Series de cours.

    Renvoie (rows, rejets) : rows au format des listes screenées (isin, code,
    name, classe, exchange, years, score) prêtes pour `select_candidates` ;
    rejets = [{isin, motif}] — chaque fonds écarté dit pourquoi.
    """
    stats, rejets = [], []
    for item in menu:
        isin = (item.get("isin") or "").strip().upper()
        name = item.get("label") or isin
        classe = fund_classe(name)
        if classe == "monétaire":
            rejets.append({"isin": isin, "motif": "monétaire"})
            continue
        try:
            px = fetcher(f"{isin}.EUFUND")
        except Exception as e:  # noqa: BLE001
            rejets.append({"isin": isin, "motif": f"cours indisponibles ({str(e)[:40]})"})
            continue
        if px is None or len(px) < 60:
            rejets.append({"isin": isin, "motif": "cours indisponibles"})
            continue
        start = str(px.index.min().date())
        if max_start and start > max_start:
            rejets.append({"isin": isin, "motif": f"historique depuis {start} (> {max_start})"})
            continue
        r = D.to_weekly_returns(px.to_frame("p"))["p"].values
        if len(r) < min_weeks:
            rejets.append({"isin": isin, "motif": f"{len(r)} semaines (< {min_weeks})"})
            continue
        s = m.summary(r)
        if not all(np.isfinite(s[k]) for k in _WEIGHTS):
            rejets.append({"isin": isin, "motif": "métriques non calculables"})
            continue
        stats.append({"isin": isin, "name": name, "classe": classe,
                      "years": round(len(r) / 52.0, 2), **{k: s[k] for k in _WEIGHTS}})
    if stats:
        score = np.zeros(len(stats))
        for k, w in _WEIGHTS.items():
            score += w * _rank_pct([x[k] for x in stats], k in _LOWER_IS_BETTER)
        for x, sc in zip(stats, score):
            x["score"] = round(float(sc), 4)
    rows = [{"code": x["isin"], "isin": x["isin"], "name": x["name"], "classe": x["classe"],
             "exchange": "EUFUND", "years": x["years"], "score": x["score"]} for x in stats]
    if verbose:
        print(f"  menu screené : {len(rows)} retenus / {len(menu)} ({len(rejets)} écartés)")
    return rows, rejets
