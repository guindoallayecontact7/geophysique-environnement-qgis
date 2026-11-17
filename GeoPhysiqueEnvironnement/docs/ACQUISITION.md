# Acquisition de données (rubrique « Acquisition de données »)

La rubrique recherche des MNT et des images satellitaires qui couvrent la zone d'étude, puis les télécharge, les découpe et les reprojette. Les résultats arrivent dans le groupe « TGS - Acquisition » du projet, et un MNT téléchargé peut devenir directement le MNT actif des autres rubriques.

## 1. Zone d'étude

Six façons de la définir, en WGS 84 en interne :

- un fichier vectoriel (Shapefile, GeoPackage, GeoJSON, KML…) : union de ses entités ;
- une couche du projet, entière ou réduite aux entités sélectionnées ;
- un rectangle tiré à la souris sur la carte ;
- l'emprise visible de la carte ;
- l'emprise du MNT actif ;
- des coordonnées GPS : Nord, Sud, Est et Ouest en degrés décimaux.

La zone s'affiche en rouge sur la carte, avec sa surface et son fuseau UTM.

## 2. Sources

| Type | Source | Résolution | Catalogue | Compte |
|---|---|---|---|---|
| MNT | Copernicus DEM GLO-30 et GLO-90 | 30 et 90 m | Planetary Computer, Earth Search | non |
| MNT | NASADEM (SRTM retraité) | 30 m | Planetary Computer | non |
| MNT | ALOS World 3D AW3D30 | 30 m | Planetary Computer | non |
| MNT | SRTM GL1 v3, ASTER GDEM v3 | 30 m | NASA Earthdata (LP DAAC) | Earthdata |
| Optique | Sentinel-2 L2A | 10 m | Planetary Computer, Earth Search | non |
| Optique | Sentinel-2 L2A, produit SAFE | 10 m | Copernicus Data Space | Copernicus |
| Optique | Landsat 4-5, 7, 8-9 Collection 2 niveau 2 | 30 m | Planetary Computer | non |
| Optique | Landsat 4-5, 7, 8-9, archive complète | 30 m | USGS EarthExplorer (M2M) | USGS |
| Optique | Sentinel-3 OLCI L2 terres (NetCDF) | 300 m | Planetary Computer | non |
| Radar | Sentinel-1 RTC et GRD | 10 m | Planetary Computer | non |
| Radar | Sentinel-1 GRD, produit SAFE | 10 m | Copernicus Data Space | Copernicus |
| Radar | ALOS PALSAR mosaïque annuelle | 25 m | Planetary Computer | non |
| Radar | ALOS PALSAR RTC 12,5 m et niveau 1.5 | 12,5 m | ASF Vertex | Earthdata |

Les catalogues sont interrogés par leurs API officielles : STAC (Planetary Computer, Earth Search, Copernicus Data Space), API de recherche ASF, CMR de la NASA et API M2M de l'USGS. Pour ajouter un catalogue, on écrit une classe avec `search()` et `resolve()` dans `acquisition/catalogs.py`, puis on déclare ses sources dans `SOURCES`.

## 3. Recherche

Filtres disponibles :

- la période d'acquisition (date de début et date de fin) ;
- la couverture nuageuse maximale (images optiques) ;
- la part minimale de la zone couverte par la scène (100 % pour une couverture intégrale) ;
- le type de données et la résolution ;
- le nombre de scènes par source.

Les MNT ne sont pas datés : la période ne les filtre pas, pas plus que les mosaïques ALOS PALSAR.

Les scènes trouvées sont triées par date, la plus récente en premier. Leurs emprises sont ajoutées à la carte (couche « Emprises des scènes trouvées »), et une scène sélectionnée dans le tableau l'est aussi sur la carte. Un double-clic affiche ses métadonnées.

## 4. Téléchargement

- **Zone d'étude seulement** : pour les sources en COG (Cloud Optimized GeoTIFF), GDAL ne lit à distance que la partie utile. Le MNT Copernicus d'un bassin de 1 000 km² arrive en quelques secondes.
- **Fichiers complets** : la scène entière est téléchargée. Une copie découpée (`*_zone.tif`) est créée quand le fichier est lisible par GDAL. Les produits SAFE et les archives Landsat restent tels quels.
- **Reprojection** : vers le SCR du projet, vers la zone UTM du centre de la zone d'étude, ou aucune. Les analyses de TGS demandent un SCR projeté en mètres.
- **MNT en plusieurs dalles** : elles sont assemblées en un seul fichier découpé (`MNT_<source>_<date>.tif`).

Un téléchargement interrompu reprend où il s'était arrêté : le fichier `.part` est complété avec une requête HTTP Range. Les coupures réseau sont réessayées automatiquement, et une source en erreur n'arrête pas les autres.

Rangement : `<dossier>/<source>/<date>_<scène>/` contient les fichiers et `metadonnees.json`. Un `journal_acquisition_<date>.txt` liste la zone, les scènes, les fichiers produits et les erreurs.

## 5. Comptes

Copernicus Data Space, NASA Earthdata et USGS demandent un compte gratuit. Les identifiants sont enregistrés dans le gestionnaire d'authentification de QGIS (configuration « Basic »), qui les chiffre. L'extension ne les écrit jamais ailleurs.

- **Copernicus Data Space** : identifiant (courriel) et mot de passe du compte dataspace.copernicus.eu.
- **NASA Earthdata** : dans le champ mot de passe, un jeton créé sur urs.earthdata.nasa.gov (« Generate Token »). Il sert pour ASF et LP DAAC.
- **USGS** : identifiant USGS et jeton d'application M2M. L'accès M2M se demande une fois sur ers.cr.usgs.gov.

Seuls les catalogues publics ont été essayés en téléchargement réel lors du développement. Les téléchargements avec compte (Copernicus Data Space, Earthdata, USGS) suivent la documentation des API, mais n'ont pas été essayés faute de compte de test.
