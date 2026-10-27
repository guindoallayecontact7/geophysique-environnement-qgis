# GeoPhysique & Environnement — extension QGIS

Version : **0.1.3**.

**Auteur : Allaye GUINDO.** Cette extension ajoute un panneau QGIS et des raccourcis vers des algorithmes de terrain. Elle constitue un socle de développement, pas encore une suite hydrologique complète validée scientifiquement.

## Compatibilité
- QGIS 3.28 à 4.x (déclaré dans `metadata.txt`; tests requis sur la version exacte).
- Python et PyQt fournis avec QGIS. Ne pas installer un Python externe pour exécuter le plugin.
- Fournisseurs Processing GDAL et GRASS recommandés.

## Installation manuelle
1. Décompresser l'archive ZIP.
2. Copier le dossier `GeoPhysiqueEnvironnement` dans le répertoire des extensions QGIS du profil utilisateur.
3. Emplacement courant sous Windows : `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\GeoPhysiqueEnvironnement`.
4. Dans QGIS : **Extensions > Installer/Gérer les extensions**, activer **GeoPhysique & Environnement**.
5. Ouvrir **Extensions > GeoPhysique > GeoPhysique & Environnement** ou cliquer sur l'icône de la barre d'outils.

Si le dossier `plugins` n'existe pas, le créer. Le profil QGIS peut avoir un autre nom que `default`; utiliser alors le dossier du profil actif.

## Fonctionnalités
- Panneau latéral intégré à QGIS.
- Détection des couches raster valides dans le projet.
- Raccourcis vers pente, exposition, ombrage, courbes de niveau et algorithmes hydrologiques disponibles.
- Vérification de la disponibilité des fournisseurs et journal simple.

## Important : hydrologie
Le bouton « Combler les cellules NoData » ouvre `gdal:fillnodata`, un algorithme destiné au comblement des cellules NoData; il ne remplit pas les dépressions hydrologiques. Pour préparer un MNT à l'analyse hydrologique, choisir un outil adapté, par exemple GRASS `r.fill.dir` si le fournisseur GRASS est disponible. `r.watershed` permet ensuite de calculer des paramètres de drainage et des bassins selon ses paramètres. Vérifier la documentation de l'algorithme et le résultat sur un petit bassin connu avant une utilisation scientifique.

## Prochaines étapes de développement
1. Ajouter une interface dédiée au prétraitement MNT : reprojection, contrôle des unités, correction des dépressions et masque d'étude.
2. Développer un workflow hydrologique guidé : direction d'écoulement, accumulation, seuil de drainage, réseau hydrographique, exutoires et bassins versants.
3. Calculer les indicateurs morphométriques : aire, périmètre, longueur, largeur, rapport de forme, coefficient de compacité, densité de drainage et ordre des cours d'eau.
4. Générer un rapport HTML/PDF avec méthodes, paramètres, sources, cartes et limites.
5. Ajouter tests automatiques et jeux de données de référence.

## Dépannage
- Si l'extension n'apparaît pas, vérifier que le dossier du plugin contient directement `metadata.txt`, `__init__.py` et `plugin.py`.
- Si GRASS n'est pas disponible, activer son fournisseur dans **Traitements > Options > Fournisseurs** et vérifier l'installation GRASS de QGIS.
- Après une modification de code, désactiver/réactiver l'extension ou redémarrer QGIS.
