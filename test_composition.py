"""Régression du sourcing composition (offline, sans PDF ni réseau).

Fixture = extrait RÉEL d'un reporting mensuel DNCA Eurose (texte `pdftotext
-layout`), avec le bruit qui piège un parseur naïf : colonnes « contribution »
signées, table de notation qui redonne la poche obligataire, expositions, pays.
On vérifie que l'extraction ISOLE le bloc d'allocation et ignore le reste.
"""
from finalyse.scrape_composition import (
    parse_composition, find_allocation_block, composition, composition_quality)

# --- extrait réel (tronqué) d'un reporting, colonnes préservées -------------
REPORTING = """\
Exposition action brute                            23,7%
Exposition action nette                            23,7%
Taux actuariel moyen                               3,55%
Répartition par classe d'actifs                                                 Contribution à la performance du mois
 Obligations crédit                                              54,9%              Obligations crédit                    +0,40%
            Actions                        23,1%                                    Actions                               +0,70%
 Obligations d'état                    16,4%                                        Obligations d'état                    +0,15%
            OPCVM             5,3%                                                   OPCVM                                 +0,02%
         CDS Index        0,0%                                                      CDS Index                             0%
Liquidités et autres      0,4%                                                     Liquidités et autres                   +0,08%
Répartition sectorielle (ICB)                                                   Répartition géographique
       Produits et services         2,2%                                           France        45,0%
Répartition par notation
Obligations taux fixe                              59,40%
Obligations convertibles                           4,00%
Taux de couverture                                 92,1%
"""


def test_block_isolated():
    blk = find_allocation_block(REPORTING)
    assert blk is not None
    assert "Obligations crédit" in blk
    assert "Répartition sectorielle" not in blk      # le bloc s'arrête à la section suivante
    assert "Obligations taux fixe" not in blk        # la table de notation est HORS bloc


def test_allocation_parsed_clean():
    comp = parse_composition(REPORTING)
    # les 4 classes réelles sont là, aux bons poids
    assert abs(comp["obligations crédit"] - 0.549) < 1e-6
    assert abs(comp["actions"] - 0.231) < 1e-6
    assert abs(comp["obligations d'état"] - 0.164) < 1e-6
    assert abs(comp["liquidités et autres"] - 0.004) < 1e-6
    # bruit exclu : expositions, taux actuariel, contributions signées, notation, pays
    keys = " ".join(comp)
    assert "exposition" not in keys
    assert "actuariel" not in keys
    assert "couverture" not in keys
    assert 0.40 not in comp.values() and 0.70 not in comp.values()  # contributions non captées comme poids
    # CDS à 0 % ignoré ; pas de double-comptage de la poche oblig (notation hors bloc)
    assert comp.get("cds index") is None
    assert "obligations taux fixe" not in comp
    q = composition_quality(comp)
    assert q["fiable"] and 0.9 <= q["somme"] <= 1.05


# extrait réel d'un reporting Carmignac Patrimoine : mise en page BI-COLONNE
# (classes à gauche, exposition devise accolée au milieu) + sous-ventilation
# géographique indentée. Le parseur doit ne garder que le top-level.
REPORTING_2COL = """\
ALLOCATION D'ACTIFS                                        EXPOSITION NETTE PAR DEVISE
Actions                             43,8%                  Euro              58,9%       Forme juridique : FCP
  Pays développés                   32,4%                  Franc suisse       1,9%
  Amérique du Nord                  24,4%                  Dollar US         17,9%
  Europe                             6,8%                  Livre Sterling    -0,8%
  Pays émergents                    11,4%                  Yen                7,6%
Obligations                         46,2%                  Bloc LATAM         5,7%
  Emprunts d'Etat pays développés   15,9%
  Emprunts privés pays émergents     4,8%
Monétaire                            4,0%
RÉPARTITION SECTORIELLE                                    RÉPARTITION PAR NOTATION
"""


def test_bicolonne_top_level_only():
    comp, meta = composition(REPORTING_2COL)
    assert set(comp) == {"actions", "obligations", "monétaire"}   # top-level seulement
    assert abs(comp["actions"] - 0.438) < 1e-6
    assert abs(comp["obligations"] - 0.462) < 1e-6
    # ni devises, ni sous-poches géo, ni notation
    for junk in ("euro", "dollar us", "pays développés", "europe", "pays émergents",
                 "emprunts d'etat pays développés", "bloc latam"):
        assert junk not in comp
    assert meta["fiable"] and 0.85 <= meta["somme"] <= 1.0


def test_prose_not_reliable():
    # un texte de DICI (prose, pas de table) ne doit pas passer pour une alloc fiable
    prose = ("Le fonds investit jusqu'à 100% en obligations et jusqu'à 35% en actions "
             "de la zone euro, avec une poche de liquidités.")
    comp, meta = composition(prose)
    assert not meta["fiable"]                         # pas de faux positif « fiable »


def test_basket_mapping():
    from finalyse.reconstruct import composition_to_basket
    b = composition_to_basket(parse_composition(REPORTING))
    assert b["BONDS"] > b["WORLD"] > b["CASH"]        # 71% oblig > 23% action > 0.4% cash
    assert abs(sum(b.values()) - 1.0) < 1e-6          # normalisé


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("tous les tests composition passent")
