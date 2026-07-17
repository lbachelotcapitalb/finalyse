"""Récupération de la COMPOSITION d'une UC (allocation par classe d'actif) → à
passer à reconstruct.composition_to_basket pour un prior RÉALISTE (la vraie
allocation du fonds, pas une catégorie générique).

CONSTAT DE SOURCING (juillet 2026, vérifié) :
- Quantalys (public ET portail CGP) est derrière un mur JS/cookies (challenge
  `redirect_…====`) : `curl` ne passe pas, un vrai navigateur est requis. Le
  « scrape public sans login » n'existe donc pas → autant se loguer (data plus
  riche) via `from_quantalys` quand on veut le luxe.
- Le DICI/KID réglementaire ne porte PAS l'allocation (juste le SRI + scénarios).
- Le REPORTING mensuel (factsheet) du fonds, lui, détaille l'allocation par classe
  d'actif — et est servi en PDF direct par les sociétés de gestion (pas de mur).
  C'est la source primaire, propre et sans souci de licence.

Pipeline :
    reporting.pdf ──extract_text──▶ texte ──find_allocation_block──▶ bloc
        ──parse_composition──▶ {classe: poids} ──composition_to_basket──▶ prior

Le point dur d'un reporting est qu'il contient des dizaines de « % » concurrents
(perfs, contributions, notations, pays, ratios) et parfois DEUX représentations de
la même poche. Un parseur « tout label + % » double-compte. On isole donc le BLOC
« répartition par classe d'actifs » et on n'y capture que le 1er % NON signé par
ligne (les colonnes « contribution » sont signées `+…%`). Hors bloc, on filtre par
un lexique de classes d'actif + une liste d'exclusion.

API :
- `composition(source)`      : point d'entrée universel (URL | chemin PDF | texte).
- `composition_from_pdf(src)`: chemin/bytes PDF → (compo, meta).
- `composition_from_url(url)`: télécharge un reporting PDF puis parse.
- `parse_composition(text)`  : cœur réutilisable, testable, sans réseau.
- `find_allocation_block`    : isole la table d'allocation d'un reporting.
- `from_quantalys(query)`    : portail CGP Quantalys (Playwright, sous licence).
"""
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")


# ---------------------------------------------------------------------------
# 1. Extraction texte d'un PDF (poppler `pdftotext -layout`, repli pypdf)
# ---------------------------------------------------------------------------
def extract_text(source):
    """source = chemin PDF | bytes PDF | texte déjà extrait → renvoie du texte.

    `pdftotext -layout` (poppler, `brew install poppler`) préserve les colonnes —
    essentiel pour aligner libellé et pourcentage. Repli sur pypdf si poppler
    absent. Si `source` est déjà du texte (pas un fichier/PDF), renvoyé tel quel.
    """
    if isinstance(source, (bytes, bytearray)):
        return _pdf_bytes_to_text(bytes(source))
    s = str(source)
    if os.path.isfile(s) and s.lower().endswith(".pdf"):
        return _pdf_file_to_text(s)
    return s


def _pdf_file_to_text(path):
    try:
        out = subprocess.run(["pdftotext", "-layout", "-q", path, "-"],
                             capture_output=True, timeout=60)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.decode("utf-8", "replace")
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    try:
        from pypdf import PdfReader
        pages = PdfReader(path).pages
        try:                                   # mode layout (pypdf ≥4) : préserve les colonnes
            return "\n".join((pg.extract_text(extraction_mode="layout") or "") for pg in pages)
        except TypeError:                      # pypdf ancien : extraction simple (dégradée)
            return "\n".join((pg.extract_text() or "") for pg in pages)
    except Exception as e:
        raise RuntimeError(
            f"Extraction PDF impossible ({path}) : installez poppler "
            f"(`brew install poppler`) ou pypdf (`pip install pypdf`). [{e}]")


def _pdf_bytes_to_text(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        return _pdf_file_to_text(tmp)
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# 2. Isolement du BLOC d'allocation (anti double-comptage)
# ---------------------------------------------------------------------------
# En-têtes qui OUVRENT le bloc « répartition par classe d'actifs ».
_ALLOC_HEADING = re.compile(
    r"r[ée]partition\s+par\s+(?:classe|type|grande?\s+classe)s?\s+d.?actif"
    r"|allocation\s+(?:d.?actifs?|par\s+classe|globale|strat[ée]gique)"
    r"|r[ée]partition\s+par\s+actif"
    r"|structure\s+du\s+portefeuille"
    r"|asset\s+allocation"
    r"|composition\s+(?:du\s+portefeuille|de\s+l.?actif|de\s+l.?actif\s+net)",
    re.I)
# En-têtes d'AUTRES sections → bornent la FIN du bloc.
_OTHER_HEADING = re.compile(
    r"r[ée]partition\s+(?:sectorielle|g[ée]ographique|par\s+(?:notation|maturit[ée]|devise|secteur|pays|zone))"
    r"|principales?\s+(?:positions|lignes|contributions?)"
    r"|composition\s+et\s+indicateurs"
    r"|contribution\s+[àa]\s+la\s+performance"
    r"|top\s*\d+|encours|caract[ée]ristiques|indicateurs\s+de\s+risque",
    re.I)


def find_allocation_block(text, max_lines=60):
    """Renvoie le texte du bloc « répartition par classe d'actifs » (de son
    en-tête jusqu'à la section suivante), ou None si aucun en-tête reconnu.
    """
    lines = text.splitlines()
    # ancrage EN DÉBUT DE LIGNE (un vrai titre), pas au milieu d'une phrase de prose
    # (« …vise à optimiser l'allocation d'actifs… » ne doit pas déclencher le bloc).
    start = next((i for i, l in enumerate(lines) if _ALLOC_HEADING.match(l.strip())), None)
    if start is None:
        return None
    block = []
    for l in lines[start + 1: start + 1 + max_lines]:
        if _ALLOC_HEADING.match(l.strip()):  # nouvelle occurrence (bloc en 2 colonnes) → on continue
            continue
        if _OTHER_HEADING.search(l):          # section suivante (n'importe quelle colonne) → fin du bloc
            break
        block.append(l)
    return "\n".join(block)


# ---------------------------------------------------------------------------
# 3. Parsing d'une composition depuis du texte
# ---------------------------------------------------------------------------
# Un libellé est une CLASSE D'ACTIF candidate seulement s'il contient un de ces
# mots (filtre le bruit quand on parse hors d'un bloc propre).
_CLASS_HINT = re.compile(
    r"action|equity|obligation|oblig\b|cr[ée]dit|dette|\bbond|taux\s+(?:fixe|variable)"
    r"|mon[ée]taire|liquidit|tr[ée]sorerie|\bcash|immobil|foncier|reit|scpi|opci"
    r"|infrastructure|convertible|[ée]mergent|emerging|\bor\b|gold|m[ée]taux|mati[èe]res"
    r"|commodit|diversifi|multi.?asset|alternati|private\s+equity|non\s+cot[ée]|opcvm",
    re.I)
# Libellés à EXCLURE même s'ils contiennent un mot de classe :
#  - ratios / perf / caractéristiques (bruit),
#  - SOUS-ventilations géo/devise d'une poche (emprunts d'État, « pays … », devises)
#    qui, dans un reporting bi-colonne, se retrouvent dans la même bande que
#    l'allocation top-level et la double-compteraient.
_EXCLUDE = re.compile(
    r"exposition|sensibilit|couverture|actuariel|rendement|yield|duration|maturit"
    r"|notation|nombre|[ée]metteur|contribution|perform|volatil|\bratio|encours|sharpe"
    r"|tracking|valeur\s+liquidative|capitalisation|\bfrais|\bter\b|s[rc]ri|objectif"
    r"|emprunt|\bpays\s|\bbloc\s|amérique|afrique|moyen.?orient|\blatam|\beema"
    r"|franc\s+suisse|dollar|sterling|\byen\b|devise",
    re.I)

# « Libellé … NN,N% » (1er % NON signé de la ligne) et « NN,N% … Libellé ».
_PCT_AFTER = re.compile(
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 '’/&()\-]{2,44}?)\s+(\d{1,3}(?:[.,]\d{1,2})?)\s*%")
_PCT_BEFORE = re.compile(
    r"(?<![+\-\d.,%])(\d{1,3}(?:[.,]\d{1,2})?)\s*%\s+(?:en|de|d['’])?\s*"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ '’/&\-]{2,44})")


_STOPWORD_START = re.compile(
    r"(?:dont|dans|des|de|du|en|et|le|la|les|un|une|ou|au|aux|par|pour|sur|avec|ce|ces|son|ses|leur)\b",
    re.I)


def _num(s):
    return float(s.replace(",", "."))


def _add(comp, label, val, require_class):
    lab = re.sub(r"\s+", " ", str(label).strip(" .:-")).lower()
    if not lab or not (0 < val <= 100):
        return
    if _EXCLUDE.search(lab):
        return
    if require_class:                        # hors bloc : filtre classe + anti-prose
        if not _CLASS_HINT.search(lab):
            return
        if len(lab.split()) > 4 or len(lab) > 32:   # un libellé de classe est court ; > = fragment de phrase
            return
        if _STOPWORD_START.match(lab):       # commence par un mot-outil → fragment de phrase
            return
    comp.setdefault(lab, val / 100)          # 1re occurrence gagne


def parse_composition(text, scope_block=True, require_class=None):
    """{classe: poids ∈ ]0,1]} depuis un texte (reporting extrait/collé).

    scope_block   : si un bloc « répartition par classe d'actifs » est présent, ne
                    parser QUE ce bloc (évite le double-comptage avec les tables de
                    notation/secteur/pays). Sinon parse tout le texte.
    require_class : ne garder que les libellés ressemblant à une classe d'actif
                    (lexique + anti-prose + anti-sous-ventilation). Défaut True — les
                    vraies classes top-level (Actions/Obligations/Monétaire/Immobilier…)
                    portent toutes un mot-clé de classe ; ça filtre devises, géographies
                    et sous-poches qui, en bloc bi-colonne, double-compteraient.

    Heuristique — à valider visuellement sur un nouveau format via `--dump`. Les
    tables d'allocation PLATES (cas courant des reportings patrimoniaux) sortent
    fiables ; une ventilation hiérarchique multi-colonnes très riche peut sur-capter
    → `meta['fiable']` le signale (somme ≠ ~100 %).
    """
    block = find_allocation_block(text) if scope_block else None
    scoped = block is not None
    src = block if scoped else text
    if require_class is None:
        require_class = True
    comp = {}
    for line in src.splitlines():
        # 1er « label % » de la ligne = colonne de GAUCHE (l'allocation). Les colonnes
        # accolées (devises, contributions signées) sont ainsi naturellement ignorées.
        m = _PCT_AFTER.search(line)
        if m:
            _add(comp, m.group(1), _num(m.group(2)), require_class)
            continue
        m = _PCT_BEFORE.search(line)
        if m:
            _add(comp, m.group(2), _num(m.group(1)), require_class)
    return comp


def composition_quality(comp):
    """Diagnostic de fiabilité : somme des poids ~100 % = probablement une vraie
    allocation isolée ; loin de 100 % = table mal isolée (à valider / coller le
    tableau précis).
    """
    s = sum(comp.values())
    # une vraie allocation a ≥2 classes ET somme ~100 %. Un seul « 100 % » capté
    # dans de la prose (DICI) ne doit pas passer pour fiable.
    return {"n": len(comp), "somme": round(s, 4), "fiable": len(comp) >= 2 and 0.85 <= s <= 1.12}


# ---------------------------------------------------------------------------
# 4. Points d'entrée réseau / universels
# ---------------------------------------------------------------------------
def fetch_pdf(url, dest=None, timeout=60):
    """Télécharge un reporting PDF (UA navigateur). Vérifie l'en-tête %PDF pour
    détecter une page HTML / un mur anti-bot renvoyé à la place du fichier.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    data = urllib.request.urlopen(req, timeout=timeout).read()
    if not data[:5].startswith(b"%PDF"):
        raise RuntimeError(f"Pas un PDF — l'URL renvoie {data[:80]!r}… (HTML/anti-bot ?)")
    if dest:
        with open(dest, "wb") as f:
            f.write(data)
    return data


def composition_from_pdf(source, **kw):
    """chemin/bytes PDF → (composition, meta). meta inclut la fiabilité et si un
    bloc d'allocation a été isolé.
    """
    text = extract_text(source)
    comp = parse_composition(text, **kw)
    meta = composition_quality(comp)
    meta["bloc_isole"] = find_allocation_block(text) is not None
    return comp, meta


def composition_from_url(url, **kw):
    """Télécharge un reporting PDF puis parse. → (composition, meta)."""
    return composition_from_pdf(fetch_pdf(url), **kw)


def composition(source, **kw):
    """Point d'entrée UNIVERSEL. `source` = URL http(s) (reporting PDF) | chemin
    PDF local | texte collé. Renvoie (composition, meta).
    """
    s = str(source)
    if s.startswith(("http://", "https://")):
        return composition_from_url(s, **kw)
    if os.path.isfile(s):
        return composition_from_pdf(s, **kw)
    comp = parse_composition(s, **kw)
    return comp, composition_quality(comp)


# ---------------------------------------------------------------------------
# 5. Quantalys — portail CGP (abonnement, lecture seule, sous licence)
# ---------------------------------------------------------------------------
def _comp_from_json(obj, out=None):
    """Aplatit un JSON de fiche Quantalys en {libellé: poids}. Best-effort :
    cherche récursivement des objets {nom-ish, poids-ish}. Robuste aux schémas."""
    out = {} if out is None else out
    if isinstance(obj, dict):
        low = {k.lower(): k for k in obj if isinstance(k, str)}
        nk = next((low[k] for k in low if k in
                   ("libelle", "libellé", "label", "nom", "name", "classe", "categorie", "category")), None)
        wk = next((low[k] for k in low if k in
                   ("poids", "weight", "pct", "pourcentage", "percent", "valeur", "value", "part")), None)
        if nk and wk and isinstance(obj.get(wk), (int, float)):
            v = float(obj[wk])
            v = v / 100 if v > 1.5 else v
            if 0 < v <= 1.001:
                out.setdefault(str(obj[nk]).strip().lower(), v)
        for v in obj.values():
            _comp_from_json(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _comp_from_json(v, out)
    return out


def from_quantalys(query, headless=False, timeout=45000, capture_json=True):
    """Composition depuis le portail CGP Quantalys (abonnement, lecture seule).

    query : ISIN ou nom de fonds. Identifiants en ENV QUANTALYS_USER /
    QUANTALYS_PASS (jamais en clair — via bw-get). Le portail est derrière un mur
    JS/cookies ; Playwright (vrai navigateur) le franchit — `headless=False`
    conseillé pour la 1re validation (headless souvent détecté). Stratégie robuste :
    CAPTURE de la réponse JSON interne de la fiche (répartition), repli sur le texte
    rendu → parse_composition.

    ⚠️ Flux sous licence : usage conforme aux CGU Quantalys (compte CGP de Léo),
    livrable interne. Sélecteurs à confirmer lors de la 1re passe live (portail
    susceptible d'évoluer). Renvoie (composition, meta).

    Pré-requis : `pip install playwright && playwright install chromium`.
    """
    from playwright.sync_api import sync_playwright  # dépendance optionnelle
    user, pwd = os.environ.get("QUANTALYS_USER"), os.environ.get("QUANTALYS_PASS")
    if not (user and pwd):
        raise RuntimeError("QUANTALYS_USER / QUANTALYS_PASS absents de l'env (via bw-get, jamais en clair).")
    captured, text = [], ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=_UA, locale="fr-FR")
        page = ctx.new_page()
        if capture_json:
            def _on_resp(r):
                u = r.url.lower()
                if any(k in u for k in ("compos", "allocation", "repartition", "répartition")):
                    try:
                        captured.append(r.json())
                    except Exception:
                        pass
            page.on("response", _on_resp)
        try:
            page.goto("https://cncgp.quantalys.com/login", wait_until="networkidle", timeout=timeout)
            page.fill("input[type=email], input[name*='mail' i], #Login, #Email", user)
            page.fill("input[type=password], #Password", pwd)
            page.click("button[type=submit], input[type=submit]")
            page.wait_for_load_state("networkidle", timeout=timeout)
            page.goto(f"https://cncgp.quantalys.com/Recherche?texte={urllib.parse.quote(query)}",
                      wait_until="networkidle", timeout=timeout)
            link = page.query_selector("a[href*='/Fonds/'], a[href*='/fonds/']")
            if link:
                link.click()
                page.wait_for_load_state("networkidle", timeout=timeout)
            for sel in ("text=Composition", "text=Allocation", "text=Répartition"):
                el = page.query_selector(sel)
                if el:
                    try:
                        el.click()
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                    break
            text = page.inner_text("body")
        finally:
            browser.close()
    for js in captured:                                  # 1) JSON interne (robuste)
        comp = _comp_from_json(js)
        if comp:
            return comp, {**composition_quality(comp), "source": "quantalys-json"}
    comp = parse_composition(text)                       # 2) repli texte rendu
    return comp, {**composition_quality(comp), "source": "quantalys-dom"}


# ---------------------------------------------------------------------------
# CLI :  python -m finalyse.scrape_composition <pdf|url|texte> [--dump] [--basket]
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import sys
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not pos:
        print("usage: python -m finalyse.scrape_composition <pdf|url|texte> [--dump] [--basket]")
        raise SystemExit(1)
    src = pos[0]
    if "--dump" in sys.argv:
        blk = find_allocation_block(extract_text(src))
        print("--- bloc d'allocation isolé ---")
        print(blk if blk else "(aucun bloc reconnu ; parsing sur le texte entier)")
        print("--- fin bloc ---\n")
    comp, meta = composition(src)
    print(json.dumps({"composition": comp, "meta": meta}, ensure_ascii=False, indent=2))
    if "--basket" in sys.argv:
        from finalyse.reconstruct import composition_to_basket
        print("panier facteurs:", json.dumps(composition_to_basket(comp), ensure_ascii=False))
