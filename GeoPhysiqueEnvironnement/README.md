# TGS - TerraGeo Science (extension QGIS)

**Version : 2.1.1** · **Auteur : Allaye GUINDO** · **Licence : GPL-2.0-or-later**

TGS (TerraGeo Science) regroupe des outils d'analyse topographique, morphométrique, géomorphologique et hydrologique à partir de modèles numériques de terrain (MNT). Il permet notamment de délimiter des bassins et sous-bassins versants, de produire des profils, des cartes et des statistiques exportables.

## Compatibilité

- Version minimale déclarée : **QGIS 3.34**.
- Le code conserve les adaptations Qt5/Qt6 présentes dans la version 2.0.4. La compatibilité QGIS 4 doit être confirmée par des essais dans une installation QGIS 4 réelle avant diffusion comme version certifiée.
- NumPy et SciPy, normalement fournis avec QGIS, sont requis pour les calculs natifs. Matplotlib est utilisé pour les graphiques ; openpyxl est facultatif (un export XLSX minimal est prévu en repli).
- GRASS, SAGA et WhiteboxTools sont facultatifs et dépendent de leur installation/configuration locale.

## Installation

Dans QGIS : **Extensions > Installer/Gérer les extensions > Installer depuis un ZIP**, puis sélectionner l'archive TGS. Le répertoire technique `GeoPhysiqueEnvironnement` est volontairement conservé afin de préserver l'identifiant historique du plugin et ses paramètres QSettings.

## Utilisation

Sélectionner le MNT en haut du panneau. Pour les calculs surfaciques, utiliser de préférence un SCR projeté en mètres ; la rubrique « Gestion des MNT » propose les outils de contrôle, reprojection et découpage. Les traitements sont exécutés en tâche de fond avec progression, journal et possibilité d'annulation. Les résultats sont ajoutés au projet dans le groupe **TGS - TerraGeo Science**.

| Rubrique | Contenu |
|---|---|
| Tableau de bord | Moteurs disponibles, analyses de la session, exportation globale |
| Acquisition de données | Zone d'étude, recherche et téléchargement de MNT, Landsat, Sentinel et ALOS PALSAR, découpe et reprojection ([détails](docs/ACQUISITION.md)) |
| Gestion des MNT | Contrôles SCR/unités/résolution/NoData, reprojection, découpage par masque |
| Analyse topographique | Hypsométrie, pentes, expositions, ombrages, courbes de niveau, relief relatif |
| Analyse morphométrique | TPI, TRI, VRM, RSP, TWI, SPI, LS et indices associés |
| Analyse géomorphologique | Courbures, formes de versant, éléments de Wood, unités de Weiss |
| Analyse hydrologique | Comblement, D8, MFD, D-Infinity, accumulation, réseau, Strahler et Shreve |
| Bassins versants | Exutoire par clic, coordonnées ou couche ; délimitation automatique |
| Sous-bassins versants | Confluences, ordre de Strahler, superficie minimale et points de contrôle |
| Profils topographiques | Profils tracés, lignes de couche et cours d'eau ; comparaison et export |
| Cartographie automatique | Cartes mises en page et atlas PDF |
| Statistiques | Tableaux, comparaison des bassins, exports TXT, CSV, Excel et PDF |
| Paramètres | Répertoire de sortie, formats et informations de réalisation |

## Sécurité et bonnes pratiques

- TGS n'a pas besoin d'un accès réseau pour effectuer ses calculs natifs.
- Installer uniquement des archives provenant d'une source de confiance et vérifier leur intégrité avant déploiement.
- Les chemins d'entrée/sortie doivent être accessibles à l'utilisateur ; éviter les dossiers système protégés.
- Les calculs hydrologiques et les résultats de délimitation dépendent de la résolution, du SCR, du traitement des dépressions et du positionnement de l'exutoire. Contrôler les résultats avant toute interprétation ou décision.
- Faire une copie du projet QGIS et des données avant les traitements importants.

## Limites de validation

La compilation syntaxique Python et les contrôles statiques ne remplacent pas les tests d'intégration dans QGIS. Avant publication, exécuter les principaux workflows sur QGIS 3.34+ et, séparément, sur chaque version majeure QGIS/Qt annoncée comme prise en charge.

Voir `docs/METHODES.md` et `docs/ARCHITECTURE.md` pour les méthodes et l'organisation technique.
