# LEARNINGS — finalyse

Enseignements curés au fil des itérations. Le classement chiffré vit dans
`INDEX.md` (auto) ; ici on garde le **pourquoi** — édité à la main / par l'IA.

## Modèle

- **Piloter par le CDaR, pas le MaxDD brut.** Le max drawdown est mono-trajectoire
  (une seule pire ligne réalisée) → sur-ajusté. Le CDaR (moyenne des pires
  drawdowns au-delà d'un quantile) est convexe et stable. Le MaxDD reste en
  reporting, jamais en objectif.
- **Overfitting du drawdown, confirmé sur données réelles.** La variante
  `cdar_budget` (rendement max sous budget DD, dépendant des μ) promet ~8 % de
  CDaR in-sample mais réalise jusqu'à **−40 % de MaxDD hors-échantillon** sur
  25 ans / 22 fenêtres. Le `min_cdar` (sans forecast de rendement) tient sa
  promesse (ratio réalisé/promis ≈ 1). Leçon : se méfier des portefeuilles qui
  s'appuient sur les rendements espérés ; privilégier le risk-based.
- **Les rendements espérés produisent des coins.** Le maximiseur de rendement
  tape les plafonds `wmax` sur 2-3 lignes. C'est la fragilité classique des μ →
  motive Black-Litterman / shrinkage en v2.
- **Biais de récence sur l'or.** 2000-2026 fut une période exceptionnelle pour
  l'or (faible corrélation + forte perf) → l'optimiseur le surpondère (15-35 %).
  Correct sur ces données mais à surveiller ; le walk-forward l'atténue.

## Données

- **EODHD « All World » (20 €/mois) suffit pour démarrer.** Coté par `TICKER.US`,
  or par `XAUUSD.FOREX`, fonds/UC par `ISIN.EUFUND`. `adjusted_close` = total
  return (règle le piège dividendes).
- **UC françaises classiques : couvertes avec VL profondes.** Carmignac
  Patrimoine (FR0010135103) remonte à **1995** (31 ans). Quantalys Pôle Data
  seulement pour d'éventuelles UC niche/assureur manquantes.
- **25 ans impossibles avec les ETF** (HYG né 2007 borne à ~19 ans). Résolu par
  des **proxys fonds indiciels longue histoire** (Vanguard VFINX/VWEHX… +
  or spot) → fenêtre commune **25,9 ans (2000-2026), dot-com incluse**.
- Yahoo/Stooq/FRED sont bloqués depuis cette machine (429 / anti-bot / timeout) ;
  EODHD passe. Ne pas dépendre du scraping live.

## Sourcing de la composition (prior réel des UC)

- **Le reporting mensuel, pas le DICI.** Le DICI/KID réglementaire ne porte que le
  SRI + scénarios ; c'est le **reporting/factsheet** mensuel qui détaille
  l'allocation par classe d'actif. Les sociétés de gestion le servent en **PDF
  direct** (DNCA `dnca-investments.com`, Carmignac `carmidoc.carmignac.com`…) —
  pas de mur anti-bot. C'est la source primaire de `composition_to_basket`.
- **Quantalys : le mur JS/cookies est franchi par un vrai navigateur, headless
  compris** (Playwright/MCP) ; `curl` seul échoue. CORRECTION du constat initial :
  beaucoup de data est exposée **SANS login** sur les pages publiques
  (`/Fonds/{id}`, `/Fonds/Composition/{id}`, `/Fonds/Historique/{id}`).
- **Série backtest gratuite via amCharts.** La page Historique charge un amCharts
  dont `AmCharts.charts[*].dataProvider` contient les points en clair : la série
  « serial » la plus longue a `{x, y_0=fonds, y_1=catégorie, y_2=benchmark}` en
  base 100. Profondeur publique ~5 ans quotidiens. Validé live sur DNCA Eurose
  (LU0284394235 / id 61840) : 1828 pts 2021-2026 → CDaR 0,071 · MaxDD −9,4 % ·
  Sharpe 0,91. Encapsulé dans `data_quantalys.py` (`fetch_uc`, `fetch_history`,
  `load_quantalys_csv`, snippet `QUANTALYS_HISTORY_JS`). Compo publique =
  **analyse de style** returns-based (ex. Act. Europe/Obl. Europe/Monétaire), pas
  le déclaratif — utilisable comme prior.
- **Catalogue complet ISIN→id, gratuit, une fois.** `POST /Recherche/Produits`
  renvoie TOUT l'univers (~62 700 produits) `{sCodeISIN, sNom, ID_Produit}` — le
  typeahead filtre côté client. Sauvé `data/quantalys_catalog.csv` (60 990 ISIN) →
  résolveur local `resolve_fund_id`. Store get-or-fetch `data_store.py` : chaque
  UC demandée est scrappée puis cachée (`data/uc/{ISIN}.csv`) → jamais deux fois.
- **Login CGP (Bitwarden) testé — ce qu'il apporte VRAIMENT.** Le portail
  `cncgp.quantalys.com` est une app SÉPARÉE du public. Il **n'allonge PAS**
  l'historique (toujours ~5 ans quotidiens) et le déclaratif holdings reste souvent
  « non calculé pour cette catégorie ». Sa vraie valeur = **télécharger le reporting
  mensuel officiel** de n'importe quelle UC (`/Produit/Post/DownloadDocument`) →
  passé à `scrape_composition.composition()` → vraie alloc (DNCA : BONDS 75/WORLD
  24/CASH 0,4, identique au PDF société de gestion). `fetch_reporting_pdf`,
  `composition_via_quantalys`. ⚠️ Data Quantalys **sous licence** → `data/`
  gitignoré (repo public), exposition partagée = décision ultérieure (MCP).
- **Extraction robuste = isoler le BLOC, pas parser tous les `%`.** Un reporting
  contient des dizaines de `%` concurrents (perfs, contributions signées,
  notation, pays, ratios) et parfois deux représentations de la même poche. On
  ancre sur l'en-tête « répartition par classe d'actifs » (en début de ligne, pas
  dans la prose), on borne à la section suivante, on ne prend que le **1er `%` non
  signé par ligne** (colonne de gauche = alloc, ignore la colonne devises accolée)
  et on filtre par lexique de classes + anti-sous-ventilation. Validé sur deux
  mises en page opposées : DNCA (centrée) et Carmignac (hiérarchique bi-colonne)
  → top-level correct, `fiable=true`. `meta['fiable']` (somme ≈ 100 %) signale les
  formats qui sur-captent. Poppler `pdftotext -layout` primaire, `pypdf`
  (`extraction_mode="layout"`) en repli. Régression : `test_composition.py`.

## Intégrer la data réelle d'UC (Quantalys) à la reconstruction

- **Ni remplacement strict, ni mix pondéré → BACKFILL CALIBRÉ** (`rc.couple_spliced`).
  Le réel Quantalys est capé à ~5 ans (sans crise) : le substituer effacerait le
  drawdown (le cœur du moteur). Le mixer jour-à-jour est ad hoc. La bonne réponse :
  la data réelle **calibre** le proxy — on estime (α, β, vol résiduelle) du fonds
  contre le proxy sur le recouvrement, on chaîne le RÉEL récent + la reconstruction
  calibrée sur le passé profond. Garde les vraies crises (proxy) ET le vrai
  comportement récent. `unsmooth=True` pour une VL d'expert lissée (OPCI/SCPI).
- **Le splice corrige la déformation du récent.** Démo DNCA Eurose : sur la fenêtre
  réelle, le proxy pur affiche MaxDD −15,7 % alors que le vrai fonds fait −9,4 % ;
  le splice = −9,4 % (la vérité), tout en gardant un backfill de crise (−13 % sur
  27 ans). **Mais** la qualité dépend du proxy : DNCA (fonds € credit) contre un
  proxy US treasuries+equity → r²=0,18, β=0,33, **confiance=18 (« prior »)** → le
  score de confiance signale honnêtement que ce proxy est mauvais. En prod : proxy
  EUR-natif (`EUR_FACTOR_SYMBOLS` : IBCX Euro corp, MSE.PA Europe) pour remonter le r².

## Méthode

- Toujours **walk-forward + contrôle d'honnêteté** avant de croire un backtest.
- Comparer les runs via `INDEX.md` (Calmar de l'équilibré) : même rendement +
  drawdown plus faible = mieux.
