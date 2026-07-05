# finalyse — optimisation de portefeuille pilotée par le drawdown

Moteur d'optimisation façon Ploovers (le concurrent qu'on réplique), avec une
différenciation assumée : on **pilote par la perte maximale historique
(drawdown)**, pas par la variance. Univers liquide multi-classes → optimisation
rendement/risque sur longue histoire incluant les crises → validation
walk-forward → projection Monte-Carlo probabilisée.

Destiné à s'intégrer à **bWealthy** (front + MCP) pour simuler des allocations
sur **CTO, PEA et assurance-vie (unités de compte)**.

## Statut — validé sur vraie donnée

Moteur validé bout-en-bout (CDaR-LP, HRP, min-variance Ledoit-Wolf, frontière
drawdown-efficiente, walk-forward + contrôle d'honnêteté, Monte-Carlo bootstrap).
Branché sur **EODHD** (`adjusted_close` = total return) et testé sur :

| Univers | Fenêtre | Ce que ça montre |
|---|---|---|
| `--deep` (proxys fonds longue histoire) | **25,9 ans** (2000-2026, dot-com incluse) | run de référence, 3 crises |
| `--eodhd` (12 ETF US) | 19,2 ans (2007-2026) | socle coté ajusté dividendes |
| `--uc` (6 UC assurance-vie réelles) | 13,3 ans | allocation actionnable par ISIN |
| `--ucits` (11 ETF UCITS/PEA) | 7,3 ans | univers investable EU (fenêtre haussière → biais de récence) |
| `--synth` (panel synthétique) | — | repli hors-ligne, dé-risquage uniquement |

Résultat central (deep 25 ans) : l'**équilibré fait +8,4 %/an pour −18 % de perte
max**, contre +6,9 % / **−32 %** pour un 60/40 — même rendement, drawdown divisé
par ~2.

## Lancer

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Le token EODHD se passe par l'ENV, jamais en argument :
export EODHD_API_TOKEN=...        # (via un gestionnaire de secrets en prod)
python run.py --deep   --json result_deep.json    # backtest 25 ans (référence)
python run.py --uc     --note "alloc AV"          # UC assurance-vie
python run.py --ucits                             # univers UCITS/PEA
python run.py --synth                             # sans token, hors-ligne
python test_sanity.py                             # tests de correction
python -m finalyse.journal top                    # classement des expériences
```

## Architecture

```
finalyse/
  universe.py     socles : SOCLE (ETF US), DEEP_HISTORY (fonds 25 ans),
                  UCITS_SYMBOLS (PEA/CTO), UC_SOCLE (assurance-vie par ISIN)
  data_eodhd.py   ingestion prod EODHD (adjusted_close, search, coverage, depth)
  data.py         ingestion live Yahoo/Stooq (fallback) + nettoyage partagé
  synth.py        panel synthétique de secours (crises 2008/2020 + flight-to-quality)
  optimize.py     CDaR-LP (Chekhlov-Uryasev), HRP (López de Prado), min-var (Ledoit-Wolf)
  metrics.py      CAGR, vol, Sharpe, MaxDD, CDaR, Calmar
  backtest.py     walk-forward + contrôle d'honnêteté (DD réalisé OOS vs promesse IS)
  montecarlo.py   bootstrap stationnaire (Politis-Romano)
  journal.py      mémoire d'amélioration indexée (auto-log de chaque run)
  sync_supabase.py  sync incrémental EODHD → Supabase (cron quotidien)
  engine.py       orchestrateur → contrat JSON (front bWealthy + MCP)
db/schema.sql     schéma Supabase (instruments, prices, experiments, sync_log)
journal/          experiments.jsonl (log), INDEX.md (classement), LEARNINGS.md (curé)
scripts/          discover_ucits.py (résolution des symboles EODHD)
run.py            démo CLI
```

## Choix de modèle (verrouillés)

| Brique | Méthode | Pourquoi |
|---|---|---|
| Pilotage risque | **CDaR contraint** (LP) | perte en queue de drawdown, convexe, stable ; ≠ MaxDD brut (mono-trajectoire, sur-ajusté) |
| Objectif | rendement max **sous budget CDaR** → Calmar | le client raisonne en perte max, pas en variance |
| Covariance | **Ledoit-Wolf** shrinkage | Markowitz naïf instable |
| « Le plus décorrélé » | **HRP** en 2ᵉ avis systématique | clustering de corrélations, sans inversion ni forecast |
| Validation | walk-forward + **contrôle d'honnêteté** | rendre visible l'overfitting du drawdown |
| Projection | **bootstrap stationnaire** | préserve clustering de vol + queues épaisses (vs gaussien) |

## Les 3 pièges, traités explicitement

1. **Overfitting du drawdown** → CDaR (pas MaxDD), et le walk-forward compare le
   drawdown *réalisé* OOS à la promesse in-sample. Sur 25 ans, la variante
   agressive `cdar_budget` promet ~8 % et réalise **~40 % OOS** : chiffré, pas caché.
2. **Survivorship bias** → prod avec source *delisted* (EODHD en dispose).
3. **Rendements ajustés dividendes** → réglé : EODHD `adjusted_close` (total return).

## Données

- **EODHD « All World »** (~20 €/mois) : coté `TICKER.US`, or `XAUUSD.FOREX`,
  **fonds/UC `ISIN.EUFUND`**. Couvre les UC françaises classiques avec VL profondes
  (Carmignac Patrimoine depuis **1995**). Quantalys Pôle Data seulement pour d'éventuelles
  UC niche/assureur manquantes.
- **On ne scrape pas en live** : un cron alimente Supabase (`sync_supabase.py`),
  l'app lit la base. `db/schema.sql` = schéma dédié `finalyse` (à loger dans le
  projet Supabase bwealthy — plafond free = 2 projets/compte).

## Mémoire d'amélioration

Chaque run s'auto-enregistre dans `journal/experiments.jsonl` ; `INDEX.md` est un
classement régénéré (Calmar de l'équilibré) et `LEARNINGS.md` garde les
enseignements curés. But : faire progresser le modèle sur des faits, à force
d'itérations.

## Feuille de route → bWealthy

- Provisionner le schéma `finalyse` dans Supabase + cron quotidien `sync_supabase.py`.
- Basculer l'univers coté sur des équivalents UCITS/PEA à historique plus long si dispo.
- Couche « enveloppe » : éligibilité PEA, frais de gestion UC (~0,6-1 %/an), fiscalité
  (= cerveau fiscal bwealthy existant).
- Exposition : `engine.run()` renvoie déjà un dict JSON → endpoint API + outil MCP
  bwealthy `optimiser_portefeuille(profil, budget_dd)`.
- v2 : Black-Litterman (vues) pour tempérer la fragilité des μ ; Riskfolio-Lib pour
  CVaR/CDaR « officiels » et davantage de mesures de risque.
