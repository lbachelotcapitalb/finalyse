"""Optimiseurs de portefeuille.

Cœur : minimisation / contrainte de CDaR posée en PROGRAMME LINÉAIRE
(Chekhlov, Uryasev, Zabarankin 2005), résolue par scipy.linprog (HiGHS).
Second avis systématique : HRP (López de Prado 2016). Filet : min-variance
sur covariance Ledoit-Wolf (2004).

Convention : returns = matrice (T, n) de rendements SIMPLES hebdo, colonnes =
actifs. Les poids sont long-only, somme = 1, plafond wmax par ligne.

Le CDaR de l'optimiseur porte sur le cumul NON composé y_k = Σ_{t<=k} w·r_t
(espace linéaire, indispensable pour rester en LP). Le drawdown composé "vrai"
est reporté séparément par metrics.py — écart faible en hebdo, honnêteté totale.
"""
import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf


# ----------------------------------------------------------------------------
# Blocs LP communs pour le CDaR
# ----------------------------------------------------------------------------
def _cdar_blocks(returns, alpha, wmax):
    """Assemble les contraintes structurelles CDaR (indépendantes de l'objectif).

    Variables x = [ w(n) | u(T) | zeta(1) | z(T) ]  → N = n + 2T + 1
      w    : poids
      u_k  : plus-haut courant du cumul (peak), >= 0
      zeta : seuil type VaR sur le drawdown (libre)
      z_k  : excès de drawdown au-delà de zeta, >= 0

    Renvoie (A_ub, b_ub, A_eq, b_eq, bounds, idx, coef, C)
    où coef = 1/((1-alpha)·T) et C = cumul des rendements (T, n).
    """
    R = np.asarray(returns, float)
    T, n = R.shape
    C = np.cumsum(R, axis=0)                    # y_k = C[k] · w
    N = n + 2 * T + 1
    iw = slice(0, n)
    iu = slice(n, n + T)
    iz0 = n + T                                 # index zeta
    iz = slice(n + T + 1, n + 2 * T + 1)
    coef = 1.0 / ((1.0 - alpha) * T)

    rows, data, cols, b = [], [], [], []
    r = 0

    # (a) peak >= cumul :  C[k]·w - u_k <= 0
    for k in range(T):
        for j in range(n):
            rows.append(r); cols.append(j); data.append(C[k, j])
        rows.append(r); cols.append(n + k); data.append(-1.0)
        b.append(0.0); r += 1

    # (b) peak monotone :  u_{k-1} - u_k <= 0
    for k in range(1, T):
        rows.append(r); cols.append(n + k - 1); data.append(1.0)
        rows.append(r); cols.append(n + k); data.append(-1.0)
        b.append(0.0); r += 1

    # (c) excès :  -z_k + u_k - C[k]·w - zeta <= 0
    for k in range(T):
        rows.append(r); cols.append(n + T + 1 + k); data.append(-1.0)   # -z_k
        rows.append(r); cols.append(n + k); data.append(1.0)            # +u_k
        rows.append(r); cols.append(iz0); data.append(-1.0)             # -zeta
        for j in range(n):
            rows.append(r); cols.append(j); data.append(-C[k, j])       # -C[k]·w
        b.append(0.0); r += 1

    A_ub = sp.csr_matrix((data, (rows, cols)), shape=(r, N))
    b_ub = np.array(b, float)

    # égalité : Σ w = 1
    A_eq = sp.csr_matrix((np.ones(n), (np.zeros(n, int), np.arange(n))), shape=(1, N))
    b_eq = np.array([1.0])

    bounds = [(0.0, wmax)] * n + [(0.0, None)] * T + [(None, None)] + [(0.0, None)] * T
    idx = {"w": iw, "u": iu, "zeta": iz0, "z": iz, "n": n, "T": T}
    return A_ub, b_ub, A_eq, b_eq, bounds, idx, coef, C


def _solve(c, A_ub, b_ub, A_eq, b_eq, bounds):
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"linprog: {res.message}")
    return res


def min_cdar(returns, alpha=0.95, wmax=0.35):
    """Portefeuille de drawdown minimal (aucune estimation de rendement)."""
    A_ub, b_ub, A_eq, b_eq, bounds, idx, coef, _ = _cdar_blocks(returns, alpha, wmax)
    N = A_ub.shape[1]
    c = np.zeros(N)
    c[idx["zeta"]] = 1.0
    c[idx["z"]] = coef                          # objectif = zeta + coef·Σz = CDaR
    res = _solve(c, A_ub, b_ub, A_eq, b_eq, bounds)
    w = np.clip(res.x[idx["w"]], 0, None)
    return w / w.sum(), float(res.fun)


def max_return_under_cdar(returns, cdar_budget, mu=None, alpha=0.95, wmax=0.35):
    """Rendement max sous contrainte CDaR <= budget. Le pilotage par le drawdown.

    mu : rendements espérés (hebdo). Si None -> moyenne historique (fragile,
    volontairement assumé ; la robustesse vient de la contrainte DD, pas du mu).
    Renvoie (w, cdar_atteint) ou (None, None) si infaisable.
    """
    R = np.asarray(returns, float)
    if mu is None:
        mu = R.mean(axis=0)
    A_ub, b_ub, A_eq, b_eq, bounds, idx, coef, _ = _cdar_blocks(returns, alpha, wmax)
    N = A_ub.shape[1]

    # ligne budget CDaR :  zeta + coef·Σz <= cdar_budget
    row = np.zeros(N)
    row[idx["zeta"]] = 1.0
    row[idx["z"]] = coef
    A_ub = sp.vstack([A_ub, sp.csr_matrix(row)]).tocsr()
    b_ub = np.append(b_ub, cdar_budget)

    c = np.zeros(N)
    c[idx["w"]] = -mu                           # min(-mu·w) = max rendement
    try:
        res = _solve(c, A_ub, b_ub, A_eq, b_eq, bounds)
    except RuntimeError:
        return None, None                        # budget trop serré = infaisable
    w = np.clip(res.x[idx["w"]], 0, None)
    w = w / w.sum()
    cdar_hit = float(res.x[idx["zeta"]] + coef * res.x[idx["z"]].sum())
    return w, cdar_hit


def drawdown_frontier(returns, mu=None, alpha=0.95, wmax=0.35, n_points=12):
    """Trace la frontière drawdown-efficiente : rendement max pour une grille de
    budgets CDaR entre le min atteignable et le CDaR du portefeuille tout-rendement.
    Renvoie liste de dicts {cdar_budget, weights, cdar_hit}.
    """
    w_min, cdar_min = min_cdar(returns, alpha, wmax)
    # borne haute : CDaR quand on ne contraint presque pas (budget large)
    _, cdar_hi = max_return_under_cdar(returns, cdar_budget=10.0, mu=mu, alpha=alpha, wmax=wmax)
    lo, hi = cdar_min, max(cdar_hi or cdar_min, cdar_min * 1.05)
    grid = np.linspace(lo, hi, n_points)
    out = []
    for bgt in grid:
        w, hit = max_return_under_cdar(returns, bgt, mu=mu, alpha=alpha, wmax=wmax)
        if w is not None:
            out.append({"cdar_budget": float(bgt), "weights": w, "cdar_hit": hit})
    return out


# ----------------------------------------------------------------------------
# Second avis : HRP (López de Prado 2016)
# ----------------------------------------------------------------------------
def _ivp(cov):
    ivp = 1.0 / np.diag(cov)
    return ivp / ivp.sum()


def _cluster_var(cov, items):
    c = cov[np.ix_(items, items)]
    w = _ivp(c).reshape(-1, 1)
    return float((w.T @ c @ w).item())


def hrp(returns, wmax=None):
    """Hierarchical Risk Parity : allocation par clustering de corrélations.
    Aucun rendement espéré, aucune inversion de matrice → robuste au bruit.
    C'est la lecture 'le plus décorrélé' du portefeuille.
    """
    R = np.asarray(returns, float)
    cov = np.cov(R, rowvar=False)
    corr = np.corrcoef(R, rowvar=False)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0, None))
    link = linkage(squareform(dist, checks=False), method="single")
    order = list(leaves_list(link))

    w = np.ones(R.shape[1])
    clusters = [order]
    while clusters:
        nxt = []
        for cl in clusters:
            if len(cl) <= 1:
                continue
            half = len(cl) // 2
            left, right = cl[:half], cl[half:]
            var_l, var_r = _cluster_var(cov, left), _cluster_var(cov, right)
            a = 1.0 - var_l / (var_l + var_r)    # poids sur le cluster gauche
            for i in left:
                w[i] *= a
            for i in right:
                w[i] *= (1.0 - a)
            nxt += [left, right]
        clusters = nxt
    w = w / w.sum()
    if wmax:
        w = cap_weights(w, wmax)
    return w


def cap_weights(w, cap):
    """Plafonne chaque poids à `cap` en redistribuant l'excédent aux lignes
    non plafonnées, au prorata de leur poids. Un simple min()+renormalisation
    refait dépasser le plafond (la renormalisation regonfle tout le monde)."""
    w = np.asarray(w, float).copy()
    w = w / w.sum()
    cap = max(cap, 1.0 / len(w))                 # plafond infaisable sinon
    for _ in range(len(w) + 1):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        free = w < cap - 1e-12
        if not free.any() or w[free].sum() <= 0:
            break
        w[free] += excess * w[free] / w[free].sum()
    return w


# ----------------------------------------------------------------------------
# Filet : min-variance Ledoit-Wolf (covariance shrinkée)
# ----------------------------------------------------------------------------
def min_variance_lw(returns, wmax=0.35):
    """Min-variance long-only plafonnée sur covariance Ledoit-Wolf : le vrai QP
    (SLSQP), pas la projection de la solution non contrainte — une projection
    n'est pas l'optimum du problème contraint. Repère 'variance' face au
    pilotage drawdown.
    """
    from scipy.optimize import minimize
    R = np.asarray(returns, float)
    lw = LedoitWolf().fit(R)
    cov = lw.covariance_
    n = cov.shape[0]
    cap = max(wmax, 1.0 / n)
    w0 = np.full(n, 1.0 / n)
    res = minimize(lambda w: w @ cov @ w, w0, jac=lambda w: 2 * cov @ w,
                   bounds=[(0.0, cap)] * n,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                   method="SLSQP", options={"ftol": 1e-12, "maxiter": 500})
    w = res.x if res.success else _project_capped_simplex(w0, cap)
    w = np.clip(w, 0, None)
    return w / w.sum(), float(lw.shrinkage_)


def _project_capped_simplex(v, cap):
    """Projection sur {w >= 0, w <= cap, Σw = 1} (tri + eau qui monte)."""
    n = len(v)
    cap = max(cap, 1.0 / n)
    w = np.clip(v, 0, cap)
    for _ in range(100):
        s = w.sum()
        if abs(s - 1.0) < 1e-9:
            break
        free = (w > 0) & (w < cap)
        if not free.any():
            w = np.clip(w + (1.0 - s) / n, 0, cap)
            continue
        w[free] += (1.0 - s) / free.sum()
        w = np.clip(w, 0, cap)
    return w / w.sum()


# ----------------------------------------------------------------------------
# Profil : le point de frontière qui tient une perte max cible
# ----------------------------------------------------------------------------
def profile_on_frontier(returns, target_maxdd, alpha=0.95, wmax=0.35, n_points=14,
                        frontier=None):
    """Parmi les points de la frontière dont le max drawdown (composé) reste
    ≤ `target_maxdd`, prend le plus rentable. Même règle in-sample et dans
    chaque pli du walk-forward — c'est ce qui rend le profil testable.

    Renvoie (w, atteignable, maxdd). Si AUCUN point ne tient la cible, on rend
    le portefeuille de drawdown minimal avec atteignable=False : le repli est
    signalé, jamais muet.
    """
    from . import metrics as m
    R = np.asarray(returns, float)
    pts = frontier if frontier is not None else drawdown_frontier(
        R, alpha=alpha, wmax=wmax, n_points=n_points)
    best = None
    for p in pts:
        r = R @ p["weights"]
        mdd, cg = m.max_drawdown(r), m.cagr(r)
        if mdd <= target_maxdd and (best is None or cg > best[1]):
            best = (p["weights"], cg, mdd)
    if best is not None:
        return best[0], True, best[2]
    w, _ = min_cdar(R, alpha, wmax)
    return w, False, m.max_drawdown(R @ w)


# ----------------------------------------------------------------------------
# Profil SANS prévision de rendement : mélange HRP (défensif) ↔ 1/N (offensif)
# ----------------------------------------------------------------------------
def profile_blend(returns, target_maxdd, marge=1.0, wmax=0.35, step=0.05):
    """w = λ·HRP + (1−λ)·1/N. On prend le λ le plus PETIT (le plus de 1/N, le
    plus rentable hors-échantillon sur nos runs) tel que perte max historique ×
    marge ≤ cible. Aucun rendement espéré n'entre dans le choix — c'est ce qui
    rendait les profils de frontière fragiles (moyenne historique = surajustement).

    Renvoie (w, atteignable, maxdd_in_sample, lam). Si même 100 % HRP dépasse
    la cible, atteignable=False (le profil n'est pas proposé).
    """
    from . import metrics as m
    R = np.asarray(returns, float)
    n = R.shape[1]
    w_def = hrp(R, wmax=wmax)
    w_off = np.full(n, 1.0 / n)
    last = None
    for lam in np.arange(0.0, 1.0 + 1e-9, step):
        w = lam * w_def + (1.0 - lam) * w_off
        mdd = m.max_drawdown(R @ w)
        last = (w, mdd, float(lam))
        if mdd * marge <= target_maxdd:
            return w, True, mdd, float(lam)
    return last[0], False, last[1], last[2]
