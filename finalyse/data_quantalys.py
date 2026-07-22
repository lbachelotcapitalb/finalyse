"""Source Quantalys — résolution ISIN→id, série longue (VL base 100) pour le
BACKTEST, et composition. Découvert et validé en live le 06/07/2026.

CONSTATS CLÉS (vérifiés) :
- Le mur JS/cookies de Quantalys (`redirect_…====`) est franchi par un VRAI
  navigateur, **headless compris**. `curl` seul échoue. Une fois le cookie posé,
  un `fetch` same-origin depuis la page passe → on scrape via des appels internes.
- **Catalogue complet SANS login** : `POST /Recherche/Produits` renvoie TOUT
  l'univers (~62 700 produits) en JSON `{sCodeISIN, sNom, ID_Produit}` — le
  typeahead filtre côté client. → résolveur ISIN→id local, une seule fois.
- **Série backtest SANS login** : `/Fonds/Historique/{id}` charge un amCharts dont
  `AmCharts.charts[*].dataProvider` porte les points en clair ; la série « serial »
  la plus longue = `{x, y_0=fonds, y_1=catégorie, y_2=benchmark}` base 100
  (~5 ans quotidiens en public). Le portail CGP (login, cf. scrape_composition.
  from_quantalys) donne le déclaratif + l'historique long des UC niche.

Chemins :
- `fetch_uc(isin)` : résout l'id (catalogue local) puis récupère la série. Automatisé
  (Playwright headless, aucun login). Alimente le cache via `data_store`.
- `refresh_catalog()` : (re)télécharge le catalogue ISIN→id.
- Sans Playwright : exécuter `QUANTALYS_HISTORY_JS` dans un navigateur ouvert sur
  /Fonds/Historique/{id} → CSV → `load_quantalys_csv`.

Donnée sous licence Quantalys — usage conforme aux CGU (compte de Léo).
"""
import csv
import io
import os

import pandas as pd

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CATALOG_PATH = os.path.join(_DIR, "quantalys_catalog.csv")
_HOME = "https://www.quantalys.com/"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# Extrait la série longue (base 100) de l'amCharts d'une page /Fonds/Historique/{id}.
QUANTALYS_HISTORY_JS = r"""
(() => {
  const cands = (window.AmCharts?.charts||[]).filter(c => c.type==='serial'
     && (c.dataProvider||[]).length && 'y_0' in (c.dataProvider[0]||{}));
  cands.sort((a,b)=> b.dataProvider.length - a.dataProvider.length);
  const dp = (cands[0]||{}).dataProvider || [];
  return 'date,base100\n' + dp.map(p => `${p.x},${p.y_0}`).join('\n');
})()
"""


# ---------------------------------------------------------------------------
# Session navigateur (franchit le mur une fois, puis fetch same-origin)
# ---------------------------------------------------------------------------
def _with_session(fn, headless=True, timeout=45000):
    """Lance chromium, franchit le mur en chargeant l'accueil, appelle fn(page)."""
    from playwright.sync_api import sync_playwright  # dépendance optionnelle
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=_UA, locale="fr-FR")
        page = ctx.new_page()
        try:
            page.goto(_HOME, wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_timeout(1200)               # laisser poser le cookie anti-bot
            return fn(page)
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Catalogue ISIN → id
# ---------------------------------------------------------------------------
def refresh_catalog(save_path=CATALOG_PATH, headless=True):
    """(Re)télécharge le catalogue complet ISIN→id (POST /Recherche/Produits) et
    l'écrit en CSV `isin,id,nom`. Renvoie le nombre d'entrées."""
    def _do(page):
        arr = page.evaluate(
            "async () => (await (await fetch('/Recherche/Produits',"
            "{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json())")
        return arr
    arr = _with_session(_do, headless=headless)
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = 0
    with open(save_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["isin", "id", "nom"])
        for p in arr:
            if p.get("sCodeISIN") and p.get("ID_Produit"):
                w.writerow([p["sCodeISIN"], p["ID_Produit"], p.get("sNom") or ""])
                n += 1
    return n


def _load_catalog(catalog_path=CATALOG_PATH):
    if not os.path.exists(catalog_path):
        raise FileNotFoundError(
            f"Catalogue Quantalys absent ({catalog_path}). Lancer refresh_catalog().")
    df = pd.read_csv(catalog_path, dtype={"isin": str, "id": "Int64"})
    return df


def resolve_fund_id(isin, catalog_path=CATALOG_PATH):
    """ISIN → id Quantalys via le catalogue local (fetch une fois). None si absent."""
    df = _load_catalog(catalog_path)
    hit = df.loc[df["isin"] == isin.strip().upper(), "id"]
    return int(hit.iloc[0]) if len(hit) else None


def catalog_name(isin, catalog_path=CATALOG_PATH):
    df = _load_catalog(catalog_path)
    hit = df.loc[df["isin"] == isin.strip().upper(), "nom"]
    return str(hit.iloc[0]) if len(hit) else None


# ---------------------------------------------------------------------------
# Série d'historique (base 100)
# ---------------------------------------------------------------------------
def parse_history_csv(text):
    """CSV « date,base100 » → Series base 100 indexée par date (quotidien
    calendaire, week-ends reportés)."""
    s = pd.read_csv(io.StringIO(text), parse_dates=["date"]).set_index("date")["base100"]
    return s[~s.index.duplicated(keep="last")].sort_index()


def to_weekly_returns(base100, freq="W-FRI"):
    """Base 100 → rendements à la fréquence du moteur (hebdo par défaut)."""
    return base100.resample(freq).last().pct_change(fill_method=None).dropna()


def load_quantalys_csv(path, freq="W-FRI"):
    with open(path, encoding="utf-8") as f:
        return to_weekly_returns(parse_history_csv(f.read()), freq)


def fetch_history(fund_id, headless=True, timeout=45000):
    """Série longue (base 100) d'un fonds par son id Quantalys. → Series."""
    def _do(page):
        page.goto(f"https://www.quantalys.com/Fonds/Historique/{fund_id}",
                  wait_until="networkidle", timeout=timeout)
        page.wait_for_timeout(2500)                   # amCharts peuple dataProvider
        return page.evaluate(QUANTALYS_HISTORY_JS)
    return parse_history_csv(_with_session(_do, headless=headless, timeout=timeout))


def fetch_uc(isin, headless=True):
    """ISIN → (base100: Series, meta). Résout l'id via le catalogue local puis
    récupère la série. C'est le point d'entrée « une UC demandée → scrape »."""
    fid = resolve_fund_id(isin)
    if fid is None:
        raise ValueError(f"ISIN {isin} introuvable au catalogue Quantalys (refresh_catalog ?).")
    base = fetch_history(fid, headless=headless)
    meta = {"source": "quantalys", "isin": isin.strip().upper(), "fund_id": fid,
            "nom": catalog_name(isin), "points": len(base),
            "from": str(base.index[0].date()) if len(base) else None,
            "to": str(base.index[-1].date()) if len(base) else None}
    return base, meta


# ---------------------------------------------------------------------------
# Portail CGP (login) — accès authentifié au REPORTING PDF officiel de toute UC
# ---------------------------------------------------------------------------
# Verdict live (06/07/2026) : le login CGP N'ALLONGE PAS l'historique (toujours
# ~5 ans quotidiens) et le déclaratif holdings reste souvent absent (« non calculé
# pour cette catégorie »). Sa vraie valeur = **télécharger le reporting mensuel
# officiel** de n'importe quelle UC (endpoint /Produit/Post/DownloadDocument),
# qu'on passe ensuite à scrape_composition.composition() pour la VRAIE allocation.
# Identifiants en ENV QUANTALYS_USER / QUANTALYS_PASS (via bw-get, jamais en clair).
_CGP = "https://cncgp.quantalys.com"


def _login_cgp(page, timeout=45000):
    user, pwd = os.environ.get("QUANTALYS_USER"), os.environ.get("QUANTALYS_PASS")
    if not (user and pwd):
        raise RuntimeError("QUANTALYS_USER / QUANTALYS_PASS absents de l'env (via bw-get).")
    page.goto(f"{_CGP}/login", wait_until="networkidle", timeout=timeout)
    page.fill("#sLogin", user)
    page.fill("#sPassword", pwd)
    page.click("button:has-text('Se connecter'), input[type=submit]")
    page.wait_for_load_state("networkidle", timeout=timeout)
    page.wait_for_timeout(1500)
    if "bachelot" not in page.inner_text("body").lower() and "/login" in page.url.lower():
        raise RuntimeError("Login CGP Quantalys échoué (identifiants ? 2FA ?).")


def fetch_reporting_pdf(fund_id, save_path=None, headless=True, timeout=45000):
    """Login CGP → télécharge le reporting PDF officiel du fonds → chemin du PDF.
    Nécessite QUANTALYS_USER/PASS en env. À passer à scrape_composition.composition()."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=_UA, locale="fr-FR")
        page = ctx.new_page()
        try:
            _login_cgp(page, timeout)
            page.goto(f"{_CGP}/Fonds/Composition/{fund_id}", wait_until="networkidle", timeout=timeout)
            page.wait_for_timeout(1500)
            rlink = page.evaluate(
                "() => { const a=[...document.querySelectorAll('a')].find(a=>/reporting/i.test(a.innerText||'')"
                "&&/DownloadDocument/i.test(a.getAttribute('href')||'')); return a?a.getAttribute('href'):null; }")
            if not rlink:
                raise RuntimeError(f"Aucun reporting PDF pour le fonds {fund_id} sur le portail CGP.")
            resp = ctx.request.get(_CGP + rlink, timeout=timeout)
            if not (resp.ok and resp.body()[:5].startswith(b"%PDF")):
                raise RuntimeError(f"Téléchargement reporting non-PDF (status {resp.status}).")
            data = resp.body()
        finally:
            browser.close()
    dest = save_path or os.path.join(_DIR, f"reporting_{fund_id}.pdf")
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def composition_via_quantalys(isin, headless=True):
    """ISIN → composition RÉELLE via le reporting officiel du portail CGP.
    (base de repli quand le reporting n'est pas trouvable côté société de gestion.)"""
    from .scrape_composition import composition
    fid = resolve_fund_id(isin)
    if fid is None:
        raise ValueError(f"ISIN {isin} introuvable au catalogue Quantalys.")
    pdf = fetch_reporting_pdf(fid, headless=headless)
    return composition(pdf)


# rétro-compat
from_quantalys_history = fetch_history
