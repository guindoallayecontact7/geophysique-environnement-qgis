# Architecture technique et feuille de route

## Structure
- `__init__.py` : point d'entrée requis par QGIS.
- `metadata.txt` : métadonnées et contraintes de compatibilité.
- `plugin.py` : cycle de vie de l'extension, interface et lancement Processing.
- `icons/` : icône de l'extension.
- `docs/` : architecture et documentation utilisateur.
- `tests/` : futurs tests unitaires et tests de régression.

## Architecture cible
1. `ui/` : panneaux et formulaires, sans logique de calcul.
2. `core/` : validation des entrées, CRS, unités, journal et configuration.
3. `hydrology/` : workflows MNT, drainage, exutoires et bassins versants.
4. `morphometry/` : indicateurs de bassin et métriques de réseau hydrographique.
5. `reporting/` : cartes, tableaux et rapports.
6. `tests/fixtures/` : rasters et vecteurs synthétiques documentés.

## Règles scientifiques
- Contrôler le CRS et utiliser une projection métrique appropriée pour les distances et superficies.
- Documenter la résolution du MNT, la méthode de correction des dépressions et le seuil d'extraction du réseau.
- Ne pas présenter une zone de contribution comme un bassin validé sans vérifier l'exutoire et la topologie du drainage.
- Conserver les entrées, paramètres et versions d'algorithmes pour assurer la reproductibilité.
- Vérifier les résultats sur un bassin de référence et par comparaison avec une source indépendante.
