# Méthodes de calcul

Toutes les formules ci-dessous sont implémentées dans `core/`. Chaque fichier TXT ou fiche PDF exporté reprend la méthode et les limites de l'analyse concernée.

## Conventions

- Les dérivées sont p = ∂z/∂x vers l'est et q = ∂z/∂y vers le nord. Une courbure positive désigne une forme convexe, et son unité est 1/m.
- L'exposition est l'azimut de la plus grande pente descendante, en degrés depuis le nord. Une cellule plane reçoit -1.
- Les fenêtres sont saisies en mètres, puis converties en un nombre impair de cellules selon la résolution.
- Une valeur NoData en bordure de fenêtre est remplacée par la valeur valide la plus proche.

## Topographie

- Pente et exposition : Horn (1981), comme gdaldem.
- Ombrage : modèle lambertien.
- Ombrage multidirectionnel : quatre azimuts (225°, 270°, 315° et 360°), pondérés par sin²(exposition - azimut) (Mark 1992).
- Classes de pente FAO (2006) : 2, 5, 10, 15, 30 et 60 %. Les bornes sont modifiables.
- Courbe hypsométrique (Strahler 1952) et intégrale HI = (moyenne - min) / (max - min) (Pike & Wilson 1971).
- Relief relatif : max - min dans la fenêtre.
- Rugosité : max - min sur une fenêtre de 3 × 3.
- Ruptures de pente : |courbure de profil| supérieure à 2 × 1,4826 × MAD.

## Courbures et géomorphologie

- Les dérivées secondes viennent du polynôme d'Evans-Young (Florinsky 2016). Elles peuvent être calculées après lissage, à une échelle choisie.
- Formules des courbures :
  - générale : -(r + t) ;
  - de profil : -(p²r + 2pqs + q²t) / ((p² + q²)(1 + p² + q²)^1,5) ;
  - planaire : -(q²r - 2pqs + p²t) / (p² + q²)^1,5 ;
  - longitudinale et transversale : Wood (1996) ;
  - minimale et maximale : H ∓ √(H² - K).
- Seuil de planéité automatique : 0,5 × 1,4826 × MAD de la courbure. Une valeur fixe peut le remplacer.
- Formes de versant : courbure de profil × courbure planaire, en 9 classes (Dikau 1989).
- Éléments de Wood (1996) : plan, sommet, crête, col, talweg et dépression.
- Weiss (2001) : TPI standardisé à deux échelles (10 unités) ou à une échelle (6 positions de versant). Un replat est défini par une pente inférieure ou égale à 5°.
- Indice de convergence : Köthe & Lehmeier (1996).

## Indices morphométriques

- TPI : z - moyenne de l'anneau carré.
- TRI : Riley et al. (1999).
- VRM : Sappington et al. (2007).
- RSP fenêtrée : (z - min) / (max - min). Contrairement à la RSP de SAGA, elle n'utilise pas le réseau de crêtes et de talwegs.
- TWI = ln(a / tan β), SPI = ln(a × tan β) et LS = (a / 22,13)^0,4 × (sin β / 0,0896)^1,3 (Moore & Burch 1986). Ici, a est l'aire drainée spécifique en m²/m, et tan β est bornée à 0,001.

## Hydrologie

- Comblement : Priority-Flood (Barnes et al. 2014), appliqué au graphe des bassins de dépression. Le test `test_core.py` vérifie qu'il donne le même résultat que la version cellule par cellule.
- Comblement limité : une dépression qui demanderait plus que la profondeur maximale reste un puits, et les petites dépressions qu'elle contient s'y écoulent.
- Zones planes : elles sont drainées vers la sortie la plus proche par un parcours en largeur sur les cellules de même altitude.
- Routage : D8 (O'Callaghan & Mark 1984), MFD (Freeman 1991, exposant 1,1) et D-Infinity (Tarboton 1997). Les cumuls suivent un tri topologique de Kahn, qui conserve les volumes.
- Le réseau, les ordres de Strahler (1957) et de Shreve (1966), les bassins et les sous-bassins utilisent toujours le D8.
- Bassin : toutes les cellules dont l'écoulement D8 aboutit à l'exutoire. Le recalage, optionnel, place l'exutoire sur la cellule d'accumulation maximale dans le rayon choisi.
- Sous-bassins : chaque exutoire intermédiaire délimite sa zone propre. Le contrôle compare la somme des superficies à celle du bassin parent, puis vérifie les recouvrements, les zones non couvertes et la validité des géométries.

## Paramètres morphométriques

Chaque paramètre est marqué comme « mesuré », « dérivé » ou « estimé » dans la table « Définition des paramètres », avec sa formule et son unité.

- Forme :
  - Kc = P / (2√(πA)) ;
  - Rf = A / Lb² ;
  - Re = 2√(A/π) / Lb ;
  - Rc = 4πA / P².
- Relief :
  - H = z_max - z_min ;
  - Rh = H / Lb ;
  - relief relatif = H / P ;
  - indice de Melton = H / √A ;
  - ruggedness = H × Dd ;
  - HI.
- Réseau : Dd = L / A, Fs = ΣNu / A, rapport de bifurcation moyen, Strahler maximal et magnitude de Shreve.
- Longueurs :
  - Lb est la distance maximale entre l'exutoire et une cellule du bassin ;
  - le cours d'eau principal est le plus long chemin d'écoulement D8.
- Périmètre : contour du polygone simplifié avec une tolérance d'une cellule, pour atténuer l'effet d'escalier. Le périmètre brut est également fourni.
- Temps de concentration estimés :
  - Kirpich : 0,0195 L^0,77 S^-0,385, en minutes ;
  - Giandotti : (4√A + 1,5 L) / (0,8 √(z_moy - z_min)), en heures.

## Validation sur données réelles

Le MNT utilisé est le Copernicus GLO-30 reprojeté en UTM 29N, sur l'extrait de Wegnia (1579 × 1997 cellules). Avec un comblement complet et l'exutoire du lac, la délimitation donne les résultats suivants :

| Recalage | Superficie | Référence (thèse) | IoU |
|---|---|---|---|
| 200 m | 1149,21 km² | 1149,08 km² | 0,9991 |
| 90 m | 402,38 km² | 401,97 km² (sous-bassin du lac) | |
