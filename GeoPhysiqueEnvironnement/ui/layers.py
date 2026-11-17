# -*- coding: utf-8 -*-
"""Ajout des couches produites au projet QGIS, rangées par groupes thématiques."""
import os

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from ..engines.styles import apply_style

ROOT_GROUP = "TERRA-MORPHO GIS"


def _group(parent, name):
    g = parent.findGroup(name)
    return g if g is not None else parent.insertGroup(0, name)


def make_layer(spec):
    if spec.kind == "vector":
        lyr = QgsVectorLayer(spec.uri, spec.name, "ogr")
    else:
        lyr = QgsRasterLayer(spec.path, spec.name, "gdal")
    if not lyr.isValid():
        return None
    apply_style(lyr, spec.style)
    return lyr


def add_result_layers(result, project=None):
    """Ajoute les couches d'un résultat ; renvoie {id(spec): layer}."""
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    top = _group(root, ROOT_GROUP)
    mod = _group(top, result.module_title)
    grp = mod.insertGroup(0, "{} ({})".format(result.title, result.created.strftime("%d/%m %H:%M")))
    added = {}
    # vecteurs au-dessus des rasters
    ordered = [s for s in result.layers if s.kind == "vector"] + [s for s in result.layers if s.kind != "vector"]
    for spec in ordered:
        if not spec.path or not os.path.exists(spec.path):
            continue
        lyr = make_layer(spec)
        if lyr is None:
            continue
        project.addMapLayer(lyr, False)
        node = grp.addLayer(lyr)
        node.setItemVisibilityChecked(bool(spec.visible))
        node.setExpanded(False)
        spec.layer_id = lyr.id()
        added[id(spec)] = lyr
    return added


def project_layer(spec, project=None):
    project = project or QgsProject.instance()
    lid = getattr(spec, "layer_id", None)
    if lid:
        lyr = project.mapLayer(lid)
        if lyr is not None:
            return lyr
    return None
