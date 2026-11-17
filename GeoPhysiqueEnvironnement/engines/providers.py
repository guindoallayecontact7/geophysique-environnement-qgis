# -*- coding: utf-8 -*-
"""Détection des moteurs de calcul disponibles."""
import importlib


def python_modules():
    out = []
    for mod, label, role in (("numpy", "NumPy", "calcul matriciel (obligatoire)"),
                             ("scipy", "SciPy", "filtres et étiquetage (obligatoire)"),
                             ("matplotlib", "Matplotlib", "graphiques et profils"),
                             ("openpyxl", "openpyxl", "export Excel enrichi (sinon écriture XLSX minimale)")):
        try:
            m = importlib.import_module(mod)
            out.append((label, True, getattr(m, "__version__", ""), role))
        except ImportError:
            out.append((label, False, "", role))
    return out


PROVIDERS = [
    (("gdal",), "GDAL", "pente, ombrage, courbes, comblement NoData (Processing)"),
    (("grass", "grass7"), "GRASS GIS", "r.watershed, r.fill.dir, r.geomorphon"),
    (("sagang", "saga"), "SAGA GIS", "Fill Sinks (Wang & Liu), indices de terrain"),
    (("wbt",), "WhiteboxTools", "Breach Depressions, indices hydrologiques"),
]


def processing_providers():
    """(nom, disponible, identifiant, rôle) pour chaque moteur Processing connu."""
    try:
        from qgis.core import QgsApplication
        reg = QgsApplication.processingRegistry()
    except Exception:  # noqa: BLE001
        reg = None
    out = []
    for ids, label, role in PROVIDERS:
        found = None
        if reg is not None:
            for i in ids:
                p = reg.providerById(i)
                if p is not None and p.isActive():
                    found = i
                    break
        out.append((label, found is not None, found or "", role))
    return out


def algorithm_available(alg_id):
    try:
        from qgis.core import QgsApplication
        return QgsApplication.processingRegistry().algorithmById(alg_id) is not None
    except Exception:  # noqa: BLE001
        return False


# Raccourcis vers les algorithmes Processing (conservés de la version 0.1 et complétés)
SHORTCUTS = {
    "topographie": [("Calculer la pente (GDAL)", "gdal:slope"), ("Calculer l'exposition (GDAL)", "gdal:aspect"),
                    ("Créer un ombrage (GDAL)", "gdal:hillshade"),
                    ("Calculer les courbes de niveau (GDAL)", "gdal:contour")],
    "mnt": [("Combler les cellules NoData (GDAL)", "gdal:fillnodata"),
            ("Reprojeter / rééchantillonner (GDAL)", "gdal:warpreproject"),
            ("Découper par un masque (GDAL)", "gdal:cliprasterbymasklayer")],
    "hydrologie": [("Ouvrir GRASS r.watershed", "grass:r.watershed"),
                   ("GRASS r.fill.dir (comblement)", "grass:r.fill.dir"),
                   ("SAGA Fill Sinks (Wang & Liu)", "sagang:fillsinkswangliu"),
                   ("WhiteboxTools Breach Depressions (moindre coût)", "wbt:BreachDepressionsLeastCost")],
    "geomorphologie": [("GRASS r.geomorphon (géomorphons)", "grass:r.geomorphon"),
                       ("SAGA Morphometric Features", "sagang:morphometricfeatures")],
}


def resolve_algorithm(alg_id):
    """Identifiant réellement disponible (gère grass7:/grass: et saga:/sagang:), ou None."""
    candidates = [alg_id]
    prov, _, name = alg_id.partition(":")
    alt = {"grass": ["grass7"], "grass7": ["grass"], "sagang": ["saga"], "saga": ["sagang"]}.get(prov, [])
    candidates += ["{}:{}".format(a, name) for a in alt]
    for c in candidates:
        if algorithm_available(c):
            return c
    return None
