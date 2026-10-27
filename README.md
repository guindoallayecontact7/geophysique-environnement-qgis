# GeoPhysique & Environnement (extension QGIS)

Extension QGIS d'Allaye GUINDO pour la géographie physique, l'hydrologie et la morphométrie. Elle ajoute un panneau latéral qui détecte les rasters du projet et ouvre sur le MNT choisi les algorithmes de pente, d'exposition, d'ombrage, de courbes de niveau (GDAL) et d'hydrologie (GDAL `fillnodata`, GRASS `r.watershed`).

L'extension est expérimentale. Contrôlez les résultats avant toute interprétation scientifique.

## Installation

Depuis QGIS : **Extensions > Installer/Gérer les extensions**, cocher « Afficher les extensions expérimentales » dans les paramètres, puis chercher « GeoPhysique ».

Installation manuelle : télécharger le zip de la dernière version dans l'onglet *Releases*, puis **Extensions > Installer depuis un ZIP**.

QGIS 3.28 ou plus récent est requis. Les fournisseurs Processing GDAL et GRASS doivent être activés.

## Contenu du dépôt

- `GeoPhysiqueEnvironnement/` : le code de l'extension, tel qu'il est installé dans QGIS. Son [README](GeoPhysiqueEnvironnement/README.md) détaille l'utilisation et les limites hydrologiques.
- `empaqueter.py` : produit le zip à envoyer sur plugins.qgis.org, dans `dist/`.

## Construire le zip

```bash
python empaqueter.py
```

## Signaler un problème

Ouvrir un ticket dans l'onglet *Issues* de ce dépôt.

## Licence

GPL-2.0 ou ultérieure, voir [LICENSE](LICENSE).
