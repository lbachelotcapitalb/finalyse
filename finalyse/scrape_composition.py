"""Récupération de la COMPOSITION d'une UC (allocation par classe d'actif) → à
passer à reconstruct.composition_to_basket pour un prior RÉALISTE (la vraie
allocation du fonds, pas une catégorie générique).

CONSTAT DE SOURCING (juillet 2026) :
- Web public peu fiable : Morningstar = WAF CloudFront (bloqué) ; Boursorama
  n'expose pas l'allocation par classe d'actif sur la page cours.
- Sources viables : (1) le DICI/KID/reporting du fonds (PDF) — contient
  l'allocation ; (2) Quantalys avec login (abonnement) — le plus riche.

Ce module fournit :
- `parse_composition(text)` : extrait {classe: poids} de N'IMPORTE QUEL texte
  (DICI/reporting collé, PDF océrisé, page rendue). Cœur réutilisable, testable,
  sans dépendance réseau. C'est le pont universel.
- `from_quantalys(isin, ...)` : scaffold Playwright + login (lecture seule),
  pour brancher la source licenciée quand le cadre le permet.
"""
import re

# libellés de composition → on garde le texte ; le mapping classe→facteur se fait
# ensuite dans reconstruct.composition_to_basket (ASSET_CLASS_TO_FACTOR).
_LABEL = r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ /'’&-]{2,42}?"


def parse_composition(text):
    """Extrait {classe_actif: poids∈]0,1]} d'un texte libre.
    Reconnaît « Libellé … NN,N % » et « NN % … Libellé ». Heuristique, à valider
    visuellement sur un nouveau format de reporting.
    """
    comp = {}
    for m in re.finditer(rf"({_LABEL})\s*[:\.]?\s*(\d{{1,3}}(?:[.,]\d)?)\s*%", text):
        lab, val = m.group(1).strip(" .:"), float(m.group(2).replace(",", "."))
        if 0 < val <= 100:
            comp.setdefault(lab.lower(), val / 100)
    for m in re.finditer(rf"(\d{{1,3}}(?:[.,]\d)?)\s*%\s*(?:en|de|d['’])?\s*({_LABEL})", text):
        val, lab = float(m.group(1).replace(",", ".")), m.group(2).strip(" .:")
        if 0 < val <= 100:
            comp.setdefault(lab.lower(), val / 100)
    return comp


def from_quantalys(isin, headless=True, timeout=30000):
    """Scaffold : composition depuis Quantalys (abonnement, lecture seule).

    Nécessite playwright-python (`pip install playwright && playwright install
    chromium`) et les identifiants Quantalys en ENV (QUANTALYS_USER /
    QUANTALYS_PASS, jamais en clair — via bw-get). Lecture seule : on ne fait que
    naviguer + lire. ⚠️ Cadre ToS/conformité à valider (flux sous licence pour un
    livrable de CGP régulé). Renvoie {classe: poids} via parse_composition.
    """
    import os
    from playwright.sync_api import sync_playwright  # import local : dépendance optionnelle
    user, pwd = os.environ.get("QUANTALYS_USER"), os.environ.get("QUANTALYS_PASS")
    if not (user and pwd):
        raise RuntimeError("QUANTALYS_USER / QUANTALYS_PASS absents de l'env (via bw-get).")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto("https://www.quantalys.com/Compte/Login", timeout=timeout)
            page.fill("input[type=email], #Email", user)
            page.fill("input[type=password], #Password", pwd)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle", timeout=timeout)
            page.goto(f"https://www.quantalys.com/Recherche?texte={isin}", timeout=timeout)
            page.wait_for_load_state("networkidle", timeout=timeout)
            # la page fiche → onglet composition/allocation (sélecteurs à ajuster au DOM réel)
            text = page.inner_text("body")
        finally:
            browser.close()
    return parse_composition(text)
