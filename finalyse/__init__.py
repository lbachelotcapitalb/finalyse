"""finalyse — moteur d'optimisation de portefeuille piloté par le drawdown.

Réplique la logique du concurrent Ploovers (univers liquide, optimisation rendement/risque
sur longue histoire incluant les crises, backtest, projection Monte-Carlo) avec
une différenciation : le pilotage se fait par le DRAWDOWN (CDaR contraint), pas
par la variance.
"""
__all__ = ["universe", "data", "optimize", "metrics", "backtest", "montecarlo", "engine"]
