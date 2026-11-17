# Architecture technique

```
GeoPhysiqueEnvironnement/
├── __init__.py, plugin.py      cycle de vie (menu, icône, panneau, À propos)
├── core/                       calcul pur NumPy/SciPy/GDAL, sans QGIS ni Qt
│   ├── grid.py                 lecture/écriture GeoTIFF, contrôles du MNT, reprojection, découpage
│   ├── terrain.py              pente, exposition, ombrages, fenêtres focales, TPI, TRI, VRM, classes
│   ├── geomorph.py             courbures, Weiss, Wood, formes de versant, convergence
│   ├── hydrology.py            comblement, D8, MFD, D-Infinity, réseau, bassins, sous-bassins
│   ├── morphometry.py          paramètres de bassin (FIELDS documente chaque champ)
│   ├── profile.py              échantillonnage et analyse des profils
│   └── vector_io.py            GeoPackage (points, lignes, polygones, courbes de niveau)
├── analyses/                   chaînes de traitement par module, exécutées en tâche de fond
│   ├── common.py               contexte de session, cache du MNT et de l'état hydrologique
│   └── topography.py, morphometry_indices.py, geomorphology.py, hydrology.py, basins.py, profiles.py
├── engines/                    moteurs communs à tous les modules
│   ├── results.py              AnalysisResult, Table, LayerSpec, registre de session
│   ├── statistics.py           Statistics Engine : statistiques, TXT, CSV, XLSX
│   ├── charts.py               graphiques Matplotlib (Agg)
│   ├── styles.py               styles décrits en dict, appliqués aux couches QGIS
│   ├── cartography.py          Cartographic Engine : mises en page, export, atlas
│   ├── report.py               fiches PDF
│   └── providers.py            détection GDAL, GRASS, SAGA, WhiteboxTools et raccourcis
├── ui/                         interface (Qt5/Qt6)
│   ├── dock.py                 panneau, MNT actif, tâches, journal, actions d'exportation
│   ├── pages.py                12 rubriques
│   ├── widgets.py, maptools.py, layers.py, mapping.py, tasks.py, profile_dialog.py
└── tests/                      test_core.py, test_workflows.py, test_gui.py
```

Les dépendances vont dans un seul sens, `ui → analyses → core` et `ui/analyses → engines`, sans dépendance circulaire. `core` et `analyses` ne touchent à aucune couche QGIS : les calculs tournent dans une `QgsTask`, et les couches, styles et mises en page sont créés dans le fil principal à la fin de la tâche.

Chaque analyse renvoie un `AnalysisResult`. Les exportations TXT, CSV, Excel et PDF, les cartes et l'exportation globale ne lisent que cet objet, ce qui évite d'avoir un système d'exportation par module.
