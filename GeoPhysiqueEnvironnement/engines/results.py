# -*- coding: utf-8 -*-
"""Objet résultat commun à tous les modules et registre de session.

Un AnalysisResult décrit une analyse terminée : entrées, paramètres, méthode,
limites, résumé, tableaux statistiques, couches raster et vecteur produites,
graphiques. Les moteurs de statistiques, de cartographie et d'exportation ne
travaillent qu'avec cet objet : un seul système d'exportation pour tous les modules.
"""
import datetime
import os
import re
import unicodedata

MODULES = [
    ("topographie", "Analyse topographique", "01_Topographie"),
    ("morphometrie", "Analyse morphométrique", "02_Morphometrie"),
    ("geomorphologie", "Analyse géomorphologique", "03_Geomorphologie"),
    ("hydrologie", "Analyse hydrologique", "04_Hydrologie"),
    ("bassins", "Bassins versants", "05_Bassins_Versants"),
    ("sous_bassins", "Sous-bassins versants", "06_Sous_Bassins"),
    ("profils", "Profils topographiques", "07_Profils"),
]
MODULE_TITLES = {k: t for k, t, _ in MODULES}
MODULE_DIRS = {k: d for k, _, d in MODULES}
MODULE_DIRS.update({"cartes": "08_Cartes", "statistiques": "09_Statistiques", "rapports": "10_Rapports"})


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")
    return t or "resultat"


class Table:
    def __init__(self, title, headers, rows, units=None, note=""):
        self.title = title
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.units = list(units) if units else [""] * len(self.headers)
        self.note = note


class LayerSpec:
    """Couche produite : chemin, nom, style et métadonnées de carte."""

    def __init__(self, path, name, kind="raster", layer=None, style=None, map_key=None,
                 map_title=None, units="", group=None, visible=True):
        self.path = path
        self.name = name
        self.kind = kind            # "raster" ou "vector"
        self.layer = layer          # nom de couche dans le GeoPackage
        self.style = style or {}    # description du style (voir engines/styles.py)
        self.map_key = map_key      # identifiant de carte thématique
        self.map_title = map_title or name
        self.units = units
        self.group = group
        self.visible = visible

    @property
    def uri(self):
        if self.kind == "vector" and self.layer:
            return "{}|layername={}".format(self.path, self.layer)
        return self.path


class AnalysisResult:
    def __init__(self, module, title, dem_source="", crs="", resolution=""):
        self.module = module
        self.title = title
        self.created = datetime.datetime.now()
        self.dem_source = dem_source
        self.crs = crs
        self.resolution = resolution
        self.inputs = []      # (libellé, valeur)
        self.params = []      # (libellé, valeur, unité)
        self.summary = []     # (libellé, valeur, unité)
        self.tables = []      # Table
        self.layers = []      # LayerSpec
        self.charts = []      # chemins PNG / SVG
        self.method = ""
        self.limits = ""
        self.folder = ""
        self.exports = []     # fichiers exportés
        self.warnings = []
        self.extra = {}       # données propres au module (non exportées)

    @property
    def slug(self):
        return slugify(self.title)

    @property
    def module_title(self):
        return MODULE_TITLES.get(self.module, self.module)

    def add_param(self, label, value, unit=""):
        self.params.append((label, value, unit))

    def add_summary(self, label, value, unit=""):
        self.summary.append((label, value, unit))

    def add_table(self, table):
        self.tables.append(table)
        return table

    def add_layer(self, spec):
        self.layers.append(spec)
        return spec

    def files(self):
        out = []
        for spec in self.layers:
            if spec.path and spec.path not in out:
                out.append(spec.path)
        out.extend(p for p in self.charts if p not in out)
        out.extend(p for p in self.exports if p not in out)
        return [p for p in out if p and os.path.exists(p)]


class ResultRegistry:
    """Résultats de la session, par module, dans l'ordre d'exécution."""

    def __init__(self):
        self._items = []
        self.listeners = []

    def add(self, result):
        self._items.append(result)
        for cb in list(self.listeners):
            try:
                cb(result)
            except Exception:  # noqa: BLE001 - un écouteur défaillant ne doit pas bloquer
                pass

    def all(self):
        return list(self._items)

    def by_module(self, module):
        return [r for r in self._items if r.module == module]

    def latest(self, module):
        items = self.by_module(module)
        return items[-1] if items else None

    def clear(self):
        self._items = []
