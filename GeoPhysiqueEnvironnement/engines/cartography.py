# -*- coding: utf-8 -*-
"""TERRA-MORPHO Cartographic Engine.

Mises en page QGIS (A4 paysage) avec titre, carte, légende, échelle
graphique, flèche du nord, système de coordonnées, sources, résolution,
méthode, date et unités. Une carte par page ; plusieurs cartes peuvent être
réunies dans un atlas (une mise en page de plusieurs pages, un seul PDF).
Fil principal uniquement.
"""
import datetime
import os

from qgis.PyQt.QtGui import QFont, QColor
from qgis.core import (
    QgsApplication, QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
    QgsLayoutItemPicture, QgsLayoutItemScaleBar, QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout,
    QgsProject, QgsRectangle, QgsUnitTypes, QgsLayoutItemPage,
)

PAGE_W, PAGE_H = 297.0, 210.0
MARGIN = 8.0
MAP_X, MAP_Y, MAP_W, MAP_H = MARGIN, 22.0, 200.0, 150.0
SIDE_X = MAP_X + MAP_W + 6.0
SIDE_W = PAGE_W - SIDE_X - MARGIN

# Cartes thématiques proposées : clé → (titre, unités par défaut)
MAP_CATALOGUE = [
    ("localisation", "Carte de localisation du bassin versant"),
    ("hypsometrie", "Carte hypsométrique"),
    ("pentes", "Carte des pentes"),
    ("expositions", "Carte des expositions"),
    ("ombrage", "Carte d'ombrage"),
    ("reseau", "Carte du réseau hydrographique"),
    ("directions", "Carte des directions d'écoulement"),
    ("accumulation", "Carte d'accumulation des écoulements"),
    ("sous_bassins", "Carte des sous-bassins versants"),
    ("strahler", "Carte des ordres hydrographiques de Strahler"),
    ("shreve", "Carte des ordres hydrographiques de Shreve"),
    ("courbes", "Carte des courbes de niveau"),
    ("courbures", "Carte des courbures"),
    ("formes", "Carte des zones concaves et convexes"),
    ("twi", "Carte du TWI"),
    ("spi", "Carte du SPI"),
    ("concentration", "Carte du potentiel de concentration du ruissellement"),
    ("unites", "Carte des unités géomorphologiques"),
    ("classes_pente", "Carte des classes de pente"),
    ("parametres", "Carte de répartition des paramètres morphométriques"),
    # cartes complémentaires produites par les modules
    ("relief", "Carte du relief relatif"),
    ("tpi", "Carte du TPI"),
    ("tri", "Carte du TRI"),
    ("vrm", "Carte du VRM"),
    ("ls", "Carte du facteur LS"),
    ("convergence", "Carte des zones de convergence"),
    ("bassin", "Carte du bassin principal"),
    ("exutoires", "Carte des exutoires"),
    ("cretes", "Carte des crêtes et talwegs"),
    ("courbure_profil", "Carte des courbures de profil"),
    ("courbure_plan", "Carte des courbures planaires"),
]
MAP_TITLES = dict(MAP_CATALOGUE)


class MapSpec:
    """Carte à produire : couches (du dessus vers le dessous), titre et informations."""

    def __init__(self, key, title, layers, legend_layers=None, extent=None, info=None, subtitle=""):
        self.key = key
        self.title = title
        self.layers = layers
        self.legend_layers = legend_layers if legend_layers is not None else layers[:1]
        self.extent = extent
        self.info = info or {}
        self.subtitle = subtitle


def _distance_km():
    try:
        from qgis.core import Qgis
        return Qgis.DistanceUnit.Kilometers
    except AttributeError:
        return getattr(QgsUnitTypes, "DistanceKilometers")  # QGIS < 3.30


def _north_arrow_path():
    for base in QgsApplication.svgPaths():
        for name in ("arrows/NorthArrow_02.svg", "arrows/NorthArrow_04.svg", "arrows/NorthArrow_01.svg"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
    return ""


def _label(layout, text, x, y, w, h, size=9, bold=False, page=0, color="#222222"):
    lab = QgsLayoutItemLabel(layout)
    lab.setText(text)
    f = QFont("Arial")
    f.setPointSizeF(float(size))
    f.setBold(bold)
    try:
        from qgis.core import QgsTextFormat
        tf = QgsTextFormat()
        tf.setFont(f)
        tf.setSize(size)
        tf.setColor(QColor(color))
        lab.setTextFormat(tf)
    except (ImportError, AttributeError):
        lab.setFont(f)
        lab.setFontColor(QColor(color))
    layout.addLayoutItem(lab)
    lab.attemptMove(QgsLayoutPoint(x, y), page=page)
    lab.attemptResize(QgsLayoutSize(w, h))
    return lab


def _text_format(size, bold=False):
    from qgis.core import QgsTextFormat
    f = QFont("Arial")
    f.setPointSizeF(float(size))
    f.setBold(bold)
    tf = QgsTextFormat()
    tf.setFont(f)
    tf.setSize(size)
    return tf


def _style_legend(leg):
    try:
        from qgis.core import QgsLegendStyle
        for st, size, bold in ((QgsLegendStyle.Style.Title, 11, True), (QgsLegendStyle.Style.Group, 8.5, True),
                               (QgsLegendStyle.Style.Subgroup, 8.5, True), (QgsLegendStyle.Style.SymbolLabel, 8, False)):
            leg.rstyle(st).setTextFormat(_text_format(size, bold))
    except (ImportError, AttributeError):
        pass


def _add_page(layout, spec, page, project):
    # cadre de la carte
    m = QgsLayoutItemMap(layout)
    m.setFrameEnabled(True)
    layout.addLayoutItem(m)
    m.attemptMove(QgsLayoutPoint(MAP_X, MAP_Y), page=page)
    m.attemptResize(QgsLayoutSize(MAP_W, MAP_H))
    layers = [lyr for lyr in spec.layers if lyr is not None]
    m.setLayers(layers)
    m.setKeepLayerSet(True)
    if layers:
        m.setCrs(layers[0].crs())
    ext = spec.extent
    if ext is None:
        ext = QgsRectangle()
        for lyr in layers:
            e = lyr.extent()
            if not e.isEmpty():
                if ext.isEmpty():
                    ext = QgsRectangle(e)
                else:
                    ext.combineExtentWith(e)
    if ext is not None and not ext.isEmpty():
        e = QgsRectangle(ext)
        e.scale(1.05)
        m.zoomToExtent(e)
    # titre
    _label(layout, spec.title, MARGIN, 6, PAGE_W - 2 * MARGIN, 9, size=16, bold=True, page=page)
    if spec.subtitle:
        _label(layout, spec.subtitle, MARGIN, 14.5, PAGE_W - 2 * MARGIN, 6, size=9, page=page, color="#555555")
    # légende
    leg = QgsLayoutItemLegend(layout)
    leg.setTitle("Légende")
    leg.setLinkedMap(m)
    leg.setAutoUpdateModel(False)
    root = leg.model().rootGroup()
    root.removeAllChildren()
    for lyr in spec.legend_layers:
        if lyr is not None:
            root.addLayer(lyr)
    _style_legend(leg)
    layout.addLayoutItem(leg)
    leg.attemptMove(QgsLayoutPoint(SIDE_X, MAP_Y), page=page)
    try:
        leg.setResizeToContents(True)
    except AttributeError:
        pass
    n_items = 0
    for lyr in spec.legend_layers:
        if lyr is not None:
            try:
                n_items += len(lyr.renderer().legendSymbolItems())
            except Exception:  # noqa: BLE001 - rasters : pas de symboles vectoriels
                n_items += 6
    if n_items > 16:
        leg.setColumnCount(2 if n_items <= 40 else 3)
    leg.adjustBoxSize()
    # flèche du nord
    north = _north_arrow_path()
    if north:
        pic = QgsLayoutItemPicture(layout)
        pic.setPicturePath(north)
        pic.setLinkedMap(m)
        pic.setNorthMode(QgsLayoutItemPicture.NorthMode.GridNorth)
        layout.addLayoutItem(pic)
        pic.attemptMove(QgsLayoutPoint(MAP_X + MAP_W - 16, MAP_Y + 3), page=page)
        pic.attemptResize(QgsLayoutSize(12, 16))
    # échelle graphique
    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Single Box")
    sb.setLinkedMap(m)
    sb.setUnits(_distance_km())
    sb.setUnitLabel("km")
    try:
        sb.setTextFormat(_text_format(8))
    except AttributeError:
        pass
    sb.setNumberOfSegments(4)
    sb.setNumberOfSegmentsLeft(0)
    sb.applyDefaultSize(_distance_km())
    layout.addLayoutItem(sb)
    sb.attemptMove(QgsLayoutPoint(MAP_X + 4, MAP_Y + MAP_H - 14), page=page)
    try:
        sb.setBackgroundEnabled(True)
        sb.setBackgroundColor(QColor(255, 255, 255, 200))
    except AttributeError:
        pass
    # informations
    info = spec.info
    crs = layers[0].crs() if layers else None
    lines = []
    if crs is not None and crs.isValid():
        lines.append("Système de coordonnées : {} ({})".format(crs.description(), crs.authid()))
    for key, label in (("resolution", "Résolution du MNT"), ("unites", "Unités"),
                       ("methode", "Méthode"), ("source", "Sources des données")):
        if info.get(key):
            lines.append("{} : {}".format(label, info[key]))
    lines.append("Date de traitement : {}".format(info.get("date") or datetime.date.today().strftime("%d/%m/%Y")))
    lines.append("Réalisation : {}".format(info.get("auteur") or "TERRA-MORPHO GIS (Allaye GUINDO)"))
    if info.get("note"):
        lines.append(info["note"])
    _label(layout, "\n".join(lines), MAP_X, MAP_Y + MAP_H + 2, MAP_W, PAGE_H - (MAP_Y + MAP_H + 2) - 4,
           size=6.5, page=page, color="#333333")
    return m


def build_layout(specs, name, project=None):
    """Mise en page d'une ou plusieurs cartes (une par page)."""
    project = project or QgsProject.instance()
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(name)
    pc = layout.pageCollection()
    pc.page(0).setPageSize("A4", QgsLayoutItemPage.Orientation.Landscape)
    for i in range(1, len(specs)):
        page = QgsLayoutItemPage(layout)
        page.setPageSize("A4", QgsLayoutItemPage.Orientation.Landscape)
        pc.addPage(page)
    for i, spec in enumerate(specs):
        _add_page(layout, spec, i, project)
    return layout


def export_layout(layout, path, fmt="pdf", dpi=200):
    """Exporte la mise en page. PNG/SVG : un fichier par page (suffixe _N au-delà de la 1re)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    exp = QgsLayoutExporter(layout)
    if fmt == "pdf":
        s = QgsLayoutExporter.PdfExportSettings()
        s.dpi = dpi
        res = exp.exportToPdf(path, s)
    elif fmt == "svg":
        s = QgsLayoutExporter.SvgExportSettings()
        s.dpi = dpi
        res = exp.exportToSvg(path, s)
    else:
        s = QgsLayoutExporter.ImageExportSettings()
        s.dpi = dpi
        from osgeo import gdal
        # QGIS tente d'écrire le géoréférencement dans le PNG (non modifiable par GDAL) : message sans effet
        gdal.PushErrorHandler("CPLQuietErrorHandler")
        try:
            res = exp.exportToImage(path, s)
        finally:
            gdal.PopErrorHandler()
    if res != QgsLayoutExporter.ExportResult.Success:
        raise IOError("Échec de l'exportation de la carte ({}) : code {}".format(fmt, res))
    return path


def register_layout(layout, project=None):
    """Ajoute la mise en page au gestionnaire du projet (remplace une homonyme)."""
    project = project or QgsProject.instance()
    mgr = project.layoutManager()
    old = mgr.layoutByName(layout.name())
    if old is not None:
        mgr.removeLayout(old)
    mgr.addLayout(layout)
    return layout
