# -*- coding: utf-8 -*-
"""Rubriques du panneau TGS - TerraGeo Science."""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget, QGridLayout,
)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeatureRequest, QgsPointXY,
                       QgsProject, QgsMapLayerProxyModel, QgsWkbTypes)
from qgis.gui import QgsMapLayerComboBox, QgsProjectionSelectionWidget, QgsFileWidget

from ..analyses import (topography, morphometry_indices, geomorphology, hydrology, basins, profiles)
from ..analyses.common import km2_to_cells, cells_to_km2, suggest_threshold_cells
from ..core import geomorph as GM, terrain as T
from ..core.morphometry import FIELDS as MORPHO_FIELDS
from ..engines import providers as P, statistics as ST, cartography as C
from ..engines.results import MODULES
from .widgets import (Form, ChecksGroup, ResultsBox, TableView, spin, ispin, combo, check, note, title)


def _filter(name):
    """Filtre de QgsMapLayerComboBox compatible QGIS 3.34+ / 4."""
    try:
        from qgis.core import Qgis
        return getattr(Qgis.LayerFilter, name)
    except AttributeError:
        return getattr(QgsMapLayerProxyModel.Filter, name, getattr(QgsMapLayerProxyModel, name, None))


class Page(QWidget):
    key = ""
    caption = ""
    module = None

    def __init__(self, dock):
        super().__init__()
        self.dock = dock
        self.lay = QVBoxLayout(self)
        self.lay.addWidget(title(self.caption))
        self.results = None
        self.build()
        if self.module:
            self.results = ResultsBox(dock, self.module)
            self.lay.addWidget(self.results)
        self.lay.addStretch(1)
        for b in self.findChildren(QPushButton):
            b.setMinimumWidth(b.sizeHint().width())

    def build(self):
        pass

    def run_button(self, text, slot):
        b = QPushButton(text)
        b.setStyleSheet("QPushButton{background:#1f3b57;color:white;font-weight:bold;padding:6px;}"
                        "QPushButton:disabled{background:#9aa9b7;}")
        b.clicked.connect(slot)
        self.dock.run_buttons.append(b)
        self.lay.addWidget(b)
        return b

    def shortcuts(self, group_key, caption="Algorithmes Processing (GDAL, GRASS, SAGA, WhiteboxTools)"):
        box = QGroupBox(caption)
        grid = QGridLayout(box)
        for i, (label, alg) in enumerate(P.SHORTCUTS.get(group_key, [])):
            b = QPushButton(label)
            real = P.resolve_algorithm(alg)
            b.setEnabled(real is not None)
            b.setToolTip(real or "Indisponible : activez le fournisseur dans Traitements > Options > Fournisseurs.")
            b.clicked.connect(lambda checked=False, a=alg: self.dock.launch_algorithm(a))
            grid.addWidget(b, i // 2, i % 2)
        self.lay.addWidget(box)
        return box

    def on_dem_changed(self):
        pass

    def refresh(self):
        if self.results is not None:
            self.results.refresh()


# ==========================================================================
class DashboardPage(Page):
    key, caption = "dashboard", "Tableau de bord"

    def build(self):
        from ..plugin import plugin_version
        self.lay.addWidget(note(
            "TGS - TerraGeo Science {} - Allaye GUINDO. Analyses topographiques, morphométriques, "
            "géomorphologiques et hydrologiques à partir d'un MNT projeté en mètres. Sélectionnez le MNT en haut "
            "du panneau, puis une rubrique.".format(plugin_version()), "#333"))
        eng = QGroupBox("Moteurs de calcul disponibles")
        v = QVBoxLayout(eng)
        self.engines = QLabel()
        self.engines.setWordWrap(True)
        self.engines.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.engines)
        self.lay.addWidget(eng)
        box = QGroupBox("Analyses de la session")
        v = QVBoxLayout(box)
        self.table = TableView()
        self.table.setMinimumHeight(170)
        v.addWidget(self.table)
        h = QHBoxLayout()
        b = QPushButton("Afficher les statistiques")
        b.clicked.connect(self.show_selected)
        h.addWidget(b)
        b = QPushButton("Charger un MNT de démonstration")
        b.setToolTip("Ouvre un fichier GeoTIFF et l'ajoute au projet")
        b.clicked.connect(self.dock.open_dem_file)
        h.addWidget(b)
        v.addLayout(h)
        self.lay.addWidget(box)
        big = QPushButton("EXPORTER TOUTES LES ANALYSES")
        big.setStyleSheet("QPushButton{background:#b35806;color:white;font-weight:bold;padding:8px;font-size:10.5pt;}")
        big.setToolTip("Regroupe couches, statistiques (TXT, CSV, Excel), fiches PDF, graphiques et cartes dans "
                       "GeoPhysique_Export/, un dossier par module exécuté.")
        big.clicked.connect(self.dock.export_everything)
        self.lay.addWidget(big)
        self.maps_too = check("Inclure un atlas PDF de toutes les cartes disponibles", False)
        self.lay.addWidget(self.maps_too)
        self.refresh()

    def refresh(self):
        lines = []
        for label, ok, ver, role in P.python_modules():
            lines.append("{} <b>{}</b> {} - {}".format("✔" if ok else "✘", label, ver, role))
        for label, ok, pid, role in P.processing_providers():
            lines.append("{} <b>{}</b>{} - {}".format("✔" if ok else "✘", label, " ({})".format(pid) if pid else
                                                       " (non activé)", role))
        lines.append("✔ <b>Moteur natif TGS</b> - comblement, D8, MFD, D-Infinity, réseau, bassins")
        self.engines.setText("<br/>".join(lines))
        from ..engines.results import Table
        rows = [[r.module_title, r.title, r.created.strftime("%H:%M:%S"), len(r.layers), len(r.tables)]
                for r in self.dock.registry.all()]
        self.table.set_table(Table("", ["Module", "Analyse", "Heure", "Couches", "Tableaux"], rows))

    def show_selected(self):
        items = self.dock.registry.all()
        row = self.table.currentRow()
        if 0 <= row < len(items):
            self.dock.show_stats(items[row])


# ==========================================================================
class DemPage(Page):
    key, caption = "mnt", "Gestion des MNT"

    def build(self):
        self.lay.addWidget(note("Le MNT actif se choisit en haut du panneau. Les calculs exigent un système de "
                                "coordonnées projeté en mètres ; les altitudes sont supposées en mètres."))
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.lay.addWidget(self.info)
        b = QPushButton("Vérifier le MNT (SCR, unités, résolution, NoData, dimensions, altitudes)")
        b.clicked.connect(self.validate)
        self.lay.addWidget(b)
        self.checks = TableView()
        self.checks.setMinimumHeight(170)
        self.lay.addWidget(self.checks)
        f = Form("Préparation du MNT")
        b = QPushButton("Reprojeter en UTM (WGS 84, zone du centre du MNT)")
        b.setToolTip("Rééchantillonnage bilinéaire à une résolution métrique équivalente ; le résultat devient le MNT actif.")
        b.clicked.connect(self.reproject)
        f.full(b)
        self.mask = QgsMapLayerComboBox()
        self.mask.setFilters(_filter("PolygonLayer"))
        f.row("Masque d'étude", self.mask, "Couche polygonale (zone d'étude, bassin) utilisée pour découper le MNT")
        b = QPushButton("Découper le MNT par le masque")
        b.clicked.connect(self.clip)
        f.full(b)
        self.lay.addWidget(f)
        self.shortcuts("mnt", "Outils Processing de préparation (GDAL)")

    def on_dem_changed(self):
        lyr = self.dock.dem_layer()
        if lyr is None:
            self.info.setText("Aucun MNT sélectionné.")
            return
        e = lyr.extent()
        self.info.setText("<b>{}</b><br/>{}<br/>SCR : {} - {} × {} cellules - résolution {:g} × {:g}<br/>"
                          "Emprise : {:.1f}, {:.1f} - {:.1f}, {:.1f}".format(
                              lyr.name(), lyr.source(), lyr.crs().authid(), lyr.width(), lyr.height(),
                              lyr.rasterUnitsPerPixelX(), lyr.rasterUnitsPerPixelY(),
                              e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()))

    def validate(self):
        from ..core import grid as G
        from ..engines.results import Table
        p = self.dock.dem_params()
        if not p:
            return
        g = self.dock.ctx.grid(p["dem_path"], p["band"])
        rows = [[c["niveau"], c["controle"], c["message"]] for c in G.validate_dem(g)]
        self.checks.set_table(Table("", ["Niveau", "Contrôle", "Message"], rows))
        self.dock.log("Vérification du MNT : {} erreur(s), {} avertissement(s).".format(
            sum(r[0] == "erreur" for r in rows), sum(r[0] == "avertissement" for r in rows)))

    def reproject(self):
        p = self.dock.dem_params(require_projected=False)
        if not p:
            return
        from ..core import grid as G
        out = os.path.join(self.dock.ctx.workspace, "00_MNT")
        os.makedirs(out, exist_ok=True)
        dst = os.path.join(out, os.path.splitext(os.path.basename(p["dem_path"]))[0] + "_utm.tif")

        def job(params, ctx, fb):
            return G.reproject_to_utm(params["dem_path"], dst, params["band"])

        self.dock.run_raw("Reprojection du MNT", job, p, lambda r: self.dock.add_dem(r[0], "MNT UTM (EPSG:{})".format(r[1])))

    def clip(self):
        p = self.dock.dem_params(require_projected=False)
        lyr = self.mask.currentLayer()
        if not p or lyr is None:
            self.dock.warn("Choisissez un MNT et une couche de masque.")
            return
        from ..core import grid as G
        src = lyr.source().split("|")[0]
        layer_name = None
        if "layername=" in lyr.source():
            layer_name = lyr.source().split("layername=")[1].split("|")[0]
        out = os.path.join(self.dock.ctx.workspace, "00_MNT")
        os.makedirs(out, exist_ok=True)
        dst = os.path.join(out, os.path.splitext(os.path.basename(p["dem_path"]))[0] + "_decoupe.tif")

        def job(params, ctx, fb):
            return G.clip_to_polygon(params["dem_path"], dst, src, layer_name)

        self.dock.run_raw("Découpage du MNT", job, p, lambda r: self.dock.add_dem(r, "MNT découpé"))


# ==========================================================================
class TopographyPage(Page):
    key, caption, module = "topo", "Analyse topographique", "topographie"

    def build(self):
        self.prods = ChecksGroup("Produits", [
            ("stats", "Statistiques altimétriques", True, "Min, max, moyenne, médiane, écart-type, variance, dénivelé"),
            ("hypso", "Carte hypsométrique et classes", True, ""),
            ("slope_deg", "Pente (degrés)", True, ""), ("slope_pct", "Pente (%)", True, ""),
            ("slope_classes", "Classes de pente", True, "Classes FAO par défaut, modifiables ci-dessous"),
            ("slope_zones", "Zones de fortes / faibles pentes", True, ""),
            ("aspect", "Expositions", True, ""), ("hillshade", "Ombrage", True, ""),
            ("multihillshade", "Ombrage multidirectionnel", True, ""),
            ("contours", "Courbes de niveau et maîtresses", True, ""),
            ("relief", "Relief relatif", True, ""), ("roughness", "Rugosité", True, ""),
            ("breaks", "Ruptures de pente", True, ""),
        ])
        self.lay.addWidget(self.prods)
        f = Form("Paramètres")
        self.zf = f.row("Facteur Z", spin(1.0, 0.0001, 100000, 0.1, 4), "Multiplie les altitudes (unités verticales ≠ horizontales)")
        self.hn = f.row("Nombre de classes altimétriques", ispin(8, 2, 30))
        self.hm = f.row("Découpage des classes", combo([("Amplitudes égales", "equal"), ("Effectifs égaux (quantiles)", "quantile")]))
        self.az = f.row("Azimut de l'éclairage", spin(315, 0, 360, 15, 0, "°"))
        self.alt = f.row("Hauteur de l'éclairage", spin(45, 1, 90, 5, 0, "°"))
        self.ci = f.row("Équidistance des courbes", spin(0, 0, 10000, 5, 2, "m"),
                        "0 = automatique (environ 20 à 50 courbes sur le dénivelé)")
        self.cm = f.row("Courbe maîtresse toutes les", ispin(5, 1, 50, "courbes"))
        self.rw = f.row("Fenêtre du relief relatif", spin(500, 10, 100000, 50, 0, "m"),
                        "Convertie en nombre impair de cellules selon la résolution")
        self.sb = f.row("Bornes des classes de pente", QLineEdit(", ".join(str(b) for b in T.FAO_SLOPE_BREAKS)),
                        "En %, croissantes, séparées par des virgules (défaut : FAO 2006)")
        self.zl = f.row("Seuil des faibles pentes", spin(5, 0, 1000, 1, 1, "%"))
        self.zh = f.row("Seuil des fortes pentes", spin(15, 0, 1000, 1, 1, "%"))
        self.lay.addWidget(f)
        self.run_button("Lancer l'analyse topographique", self.run)
        self.shortcuts("topographie", "Outils Processing (GDAL) - version 0.1")

    def run(self):
        p = self.dock.dem_params()
        if not p:
            return
        try:
            breaks = [float(x.replace(",", ".")) for x in self.sb.text().replace(";", ",").split(", ") if x.strip()]
        except ValueError:
            breaks = []
        if not breaks or sorted(breaks) != breaks:
            self.dock.warn("Bornes de pente invalides : nombres croissants séparés par « , ».")
            return
        p.update(products=self.prods.selected(), zfactor=self.zf.value(), hypso_n=self.hn.value(),
                 hypso_method=self.hm.currentData(), hs_azimuth=self.az.value(), hs_altitude=self.alt.value(),
                 contour_interval=self.ci.value() or None, contour_master=self.cm.value(),
                 relief_window_m=self.rw.value(), slope_breaks=breaks, zone_low=self.zl.value(),
                 zone_high=self.zh.value())
        self.dock.run_analysis("Analyse topographique", topography.run, p)


# ==========================================================================
class HydroSettings(Form):
    """Paramètres hydrologiques partagés (prétraitement, routage, seuil)."""

    def __init__(self, dock):
        super().__init__("Prétraitement et routage")
        self.dock = dock
        self.fill = self.row("Correction des dépressions", combo([
            ("Comblement complet (Priority-Flood)", "fill"),
            ("Comblement limité en profondeur", "fill_depth"),
            ("Aucune (dépressions conservées)", "none")]),
            "Les dépressions naturelles peuvent être conservées : choisissez la méthode adaptée au terrain.")
        self.depth = self.row("Profondeur maximale comblée", spin(2.0, 0, 10000, 0.5, 2, "m"),
                              "Au-delà, la dépression reste un puits naturel (option « limité en profondeur »)")
        self.flow = self.row("Direction des écoulements", combo([
            ("D8 (O'Callaghan & Mark)", "d8"), ("MFD (Freeman, multidirectionnel)", "mfd"),
            ("D-Infinity (Tarboton)", "dinf")]),
            "Le réseau, les bassins et les ordres utilisent toujours le D8 ; MFD et D-Infinity servent aux "
            "accumulations et aux indices (TWI, SPI, LS).")
        self.exp = self.row("Exposant MFD", spin(1.1, 0.1, 10, 0.1, 2), "Freeman (1991) : 1,1")
        h = QHBoxLayout()
        self.thr = spin(1.0, 0.0001, 1e6, 0.1, 4, "km²")
        self.thr.setToolTip("Aire drainée minimale pour qu'une cellule appartienne au réseau")
        self.cells = QLabel()
        sug = QPushButton("Suggérer")
        sug.setToolTip("Seuil de départ : 1/2000 de la surface du MNT (au moins 50 cellules), à ajuster")
        sug.clicked.connect(self.suggest)
        h.addWidget(self.thr, 1)
        h.addWidget(sug)
        w = QWidget()
        w.setLayout(h)
        self.row("Seuil d'accumulation du réseau", w)
        self.full(self.cells)
        self.thr.valueChanged.connect(self.update_cells)
        self.fill.currentIndexChanged.connect(lambda i: self.depth.setEnabled(self.fill.currentData() == "fill_depth"))
        self.depth.setEnabled(False)

    def cell_area(self):
        lyr = self.dock.dem_layer()
        if lyr is None:
            return None
        return lyr.rasterUnitsPerPixelX() * lyr.rasterUnitsPerPixelY()

    def update_cells(self):
        ca = self.cell_area()
        if ca:
            self.cells.setText("= {:,.0f} cellules du MNT actif".format(self.thr.value() * 1e6 / ca).replace(",", " "))
        else:
            self.cells.setText("")

    def suggest(self):
        lyr = self.dock.dem_layer()
        if lyr is None:
            return
        ca = self.cell_area()
        cells = max(50, round(lyr.width() * lyr.height() / 2000.0))
        self.thr.setValue(cells * ca / 1e6)

    def params(self):
        ca = self.cell_area() or 1.0
        return {"fill": self.fill.currentData(), "max_depth": self.depth.value(), "flow": self.flow.currentData(),
                "mfd_exponent": self.exp.value(), "threshold_cells": max(2.0, self.thr.value() * 1e6 / ca)}


class HydrologyPage(Page):
    key, caption, module = "hydro", "Analyse hydrologique", "hydrologie"

    def build(self):
        self.settings = HydroSettings(self.dock)
        self.lay.addWidget(self.settings)
        self.prods = ChecksGroup("Produits", [
            ("filled", "MNT corrigé", True, ""), ("depressions", "Dépressions détectées", True, ""),
            ("directions", "Directions d'écoulement (D8)", True, ""),
            ("accumulation", "Accumulation des écoulements", True, ""),
            ("flow_length", "Longueurs d'écoulement", True, ""),
            ("convergence", "Zones de convergence", True, ""),
            ("concentration", "Zones de concentration", True, ""),
            ("streams", "Réseau (Strahler, Shreve)", True, ""), ("confluences", "Confluences", True, ""),
        ])
        self.lay.addWidget(self.prods)
        self.run_button("Lancer l'analyse hydrologique", self.run)
        self.shortcuts("hydrologie", "Moteurs externes (GRASS, SAGA, WhiteboxTools)")
        self.lay.addWidget(note("Un MNT corrigé par un moteur externe (brèche WhiteboxTools, r.fill.dir) peut "
                                "être choisi comme MNT actif avec « Aucune correction »."))

    def on_dem_changed(self):
        self.settings.suggest()
        self.settings.update_cells()

    def run(self):
        p = self.dock.dem_params()
        if not p:
            return
        p.update(self.settings.params(), products=self.prods.selected())
        self.dock.run_analysis("Analyse hydrologique", hydrology.run, p)


# ==========================================================================
class MorphometryPage(Page):
    key, caption, module = "morpho", "Analyse morphométrique", "morphometrie"

    def build(self):
        self.idx = ChecksGroup("Indices", [
            ("tpi", "TPI", True, "Topographic Position Index"), ("tri", "TRI", True, "Terrain Ruggedness Index"),
            ("vrm", "VRM", True, "Vector Ruggedness Measure"), ("rsp", "RSP (fenêtrée)", True, "Position relative"),
            ("twi", "TWI", True, "Topographic Wetness Index"), ("spi", "SPI", True, "Stream Power Index"),
            ("ls", "Facteur LS", True, ""), ("hi", "Intégrale hypsométrique locale", True, ""),
            ("dissection", "Indice de dissection", True, ""), ("units", "Unités morphométriques", True, ""),
        ])
        self.lay.addWidget(self.idx)
        f = Form("Paramètres (fenêtres en mètres, converties selon la résolution)")
        self.zf = f.row("Facteur Z", spin(1.0, 0.0001, 100000, 0.1, 4))
        self.tpi = f.row("Rayon du TPI", spin(300, 1, 100000, 50, 0, "m"))
        self.vrm = f.row("Fenêtre du VRM", spin(90, 1, 100000, 30, 0, "m"))
        self.rsp = f.row("Fenêtre de la RSP", spin(1000, 1, 100000, 100, 0, "m"))
        self.hi = f.row("Fenêtre de l'intégrale hypsométrique", spin(1000, 1, 100000, 100, 0, "m"))
        self.dis = f.row("Fenêtre de l'indice de dissection", spin(1000, 1, 100000, 100, 0, "m"))
        self.lsm = f.row("Exposant m du facteur LS", spin(0.4, 0, 2, 0.1, 2))
        self.lsn = f.row("Exposant n du facteur LS", spin(1.3, 0, 3, 0.1, 2))
        self.mt = f.row("tan β minimale (TWI, SPI)", spin(0.001, 1e-6, 1, 0.001, 6))
        self.flat = f.row("Pente maximale d'un replat", spin(5, 0, 90, 1, 1, "°"), "Weiss (2001) : 5°")
        self.lay.addWidget(f)
        self.lay.addWidget(note("Le routage (TWI, SPI, LS) suit les paramètres de la rubrique « Analyse hydrologique »."))
        self.run_button("Lancer l'analyse morphométrique", self.run)

    def run(self):
        p = self.dock.dem_params()
        if not p:
            return
        p.update(self.dock.pages["hydro"].settings.params())
        p.update(indices=self.idx.selected(), zfactor=self.zf.value(), tpi_radius_m=self.tpi.value(),
                 vrm_window_m=self.vrm.value(), rsp_window_m=self.rsp.value(), hi_window_m=self.hi.value(),
                 dissection_window_m=self.dis.value(), ls_m=self.lsm.value(), ls_n=self.lsn.value(),
                 min_tan=self.mt.value(), flat_slope_deg=self.flat.value())
        self.dock.run_analysis("Analyse morphométrique", morphometry_indices.run, p)


# ==========================================================================
class GeomorphologyPage(Page):
    key, caption, module = "geomorph", "Analyse géomorphologique", "geomorphologie"

    def build(self):
        self.curv = ChecksGroup("Courbures", [(k, v, True, "") for k, v in GM.CURVATURE_NAMES.items()])
        self.lay.addWidget(self.curv)
        self.prods = ChecksGroup("Classifications", [
            ("forms", "Surfaces concaves / planes / convexes", True, ""),
            ("slope_forms", "Versants concaves, convexes, rectilignes", True, "Profil × plan (Dikau)"),
            ("wood", "Sommets, crêtes, cols, talwegs, dépressions", True, "Wood (1996)"),
            ("weiss", "Unités géomorphologiques (10 classes)", True, "Weiss (2001)"),
            ("position", "Hauts / bas de versant, vallées", True, "Position de versant (Weiss)"),
            ("ridges", "Crêtes et talwegs", True, ""), ("breaks", "Ruptures de pente", True, ""),
        ])
        self.lay.addWidget(self.prods)
        f = Form("Paramètres")
        self.zf = f.row("Facteur Z", spin(1.0, 0.0001, 100000, 0.1, 4))
        self.scale = f.row("Échelle d'analyse", spin(0, 0, 100000, 30, 0, "m"),
                           "0 = dérivées 3 × 3 sans lissage. Sur un MNS, prenez au moins 3 cellules.")
        self.tm = f.row("Seuil de planéité", combo([("Automatique (écart-type robuste)", "auto"), ("Valeur fixe", "value")]))
        self.tf = f.row("Facteur du seuil automatique", spin(0.5, 0.01, 10, 0.1, 2))
        self.tv = f.row("Seuil fixe", spin(0.0001, 0, 1, 0.0001, 6, "1/m"))
        self.ts = f.row("Rayon TPI petite échelle", spin(300, 1, 100000, 50, 0, "m"))
        self.tl = f.row("Rayon TPI grande échelle", spin(2000, 1, 100000, 100, 0, "m"))
        self.fl = f.row("Pente maximale d'un replat / d'une plaine", spin(5, 0, 90, 1, 1, "°"))
        self.ws = f.row("Tolérance de pente (Wood)", spin(1, 0, 90, 0.5, 1, "°"))
        self.lay.addWidget(f)
        self.run_button("Lancer l'analyse géomorphologique", self.run)
        self.shortcuts("geomorphologie", "Moteurs externes")

    def run(self):
        p = self.dock.dem_params()
        if not p:
            return
        p.update(curvatures=self.curv.selected(), products=self.prods.selected(), zfactor=self.zf.value(),
                 scale_m=self.scale.value() or None, tol_mode=self.tm.currentData(), tol_factor=self.tf.value(),
                 tol_value=self.tv.value(), tpi_small_m=self.ts.value(), tpi_large_m=self.tl.value(),
                 flat_slope_deg=self.fl.value(), wood_slope_tol=self.ws.value())
        self.dock.run_analysis("Analyse géomorphologique", geomorphology.run, p)


# ==========================================================================
class BasinsPage(Page):
    key, caption, module = "bassins", "Bassins versants", "bassins"

    def build(self):
        f = Form("Exutoire")
        self.mode = f.row("Définition", combo([("Clic sur la carte", "click"), ("Coordonnées X / Y", "xy"),
                                                ("Couche de points", "layer")]))
        b = QPushButton("Cliquer l'exutoire sur la carte")
        b.clicked.connect(self.pick)
        f.full(b)
        self.x = f.row("X", spin(0, -1e9, 1e9, 10, 3))
        self.y = f.row("Y", spin(0, -1e9, 1e9, 10, 3))
        self.crs = QgsProjectionSelectionWidget()
        f.row("SCR des coordonnées", self.crs)
        self.pts = QgsMapLayerComboBox()
        self.pts.setFilters(_filter("PointLayer"))
        f.row("Couche d'exutoires", self.pts)
        self.sel = f.full(check("Entités sélectionnées uniquement", True))
        self.lay.addWidget(f)
        g = Form("Repositionnement de l'exutoire")
        self.snap = g.full(check("Repositionner sur la cellule d'accumulation maximale", True))
        self.rad = g.row("Distance maximale de recherche", spin(150, 0, 100000, 30, 0, "m"),
                         "L'exutoire initial et l'exutoire corrigé sont tous deux affichés")
        self.onnet = g.full(check("Limiter la recherche au réseau hydrographique", True))
        self.lay.addWidget(g)
        self.lay.addWidget(note("Prétraitement, routage et seuil du réseau : rubrique « Analyse hydrologique »."))
        self.run_button("Délimiter le bassin versant", self.run_outlet)
        a = Form("Délimitation automatique sans exutoire")
        self.amin = a.row("Superficie minimale des bassins", spin(5, 0.0001, 1e7, 1, 4, "km²"))
        self.edge = a.full(check("Exclure les bassins qui touchent le bord du MNT", False))
        self.lay.addWidget(a)
        self.run_button("Détecter les exutoires et délimiter les bassins", self.run_auto)

    def on_dem_changed(self):
        lyr = self.dock.dem_layer()
        if lyr is not None:
            self.crs.setCrs(self.dock.iface.mapCanvas().mapSettings().destinationCrs())

    def pick(self):
        self.mode.setCurrentIndex(0)
        self.dock.pick_point(self.on_point)

    def on_point(self, pt):
        self.crs.setCrs(self.dock.iface.mapCanvas().mapSettings().destinationCrs())
        self.x.setValue(pt.x())
        self.y.setValue(pt.y())
        self.dock.log("Exutoire saisi : {:.2f}, {:.2f} ({})".format(pt.x(), pt.y(), self.crs.crs().authid()))

    def outlets(self, dem_crs):
        mode = self.mode.currentData()
        if mode in ("click", "xy"):
            tr = QgsCoordinateTransform(self.crs.crs(), dem_crs, QgsProject.instance())
            p = tr.transform(QgsPointXY(self.x.value(), self.y.value()))
            return [(p.x(), p.y(), "Exutoire")]
        lyr = self.pts.currentLayer()
        if lyr is None:
            return []
        tr = QgsCoordinateTransform(lyr.crs(), dem_crs, QgsProject.instance())
        feats = lyr.getSelectedFeatures() if self.sel.isChecked() and lyr.selectedFeatureCount() else lyr.getFeatures()
        out = []
        for f in feats:
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            p = tr.transform(g.centroid().asPoint())
            out.append((p.x(), p.y(), "Exutoire {}".format(f.id())))
        return out

    def run_outlet(self):
        p = self.dock.dem_params()
        if not p:
            return
        lyr = self.dock.dem_layer()
        outs = self.outlets(lyr.crs())
        if not outs:
            self.dock.warn("Aucun exutoire défini.")
            return
        p.update(self.dock.pages["hydro"].settings.params())
        p.update(outlets=outs, snap=self.snap.isChecked(), snap_radius_m=self.rad.value(),
                 snap_to_stream=self.onnet.isChecked())
        self.dock.run_analysis("Délimitation du bassin versant", basins.run_outlets, p)

    def run_auto(self):
        p = self.dock.dem_params()
        if not p:
            return
        p.update(self.dock.pages["hydro"].settings.params())
        p.update(min_area_km2=self.amin.value(), exclude_edge=self.edge.isChecked())
        self.dock.run_analysis("Délimitation automatique", basins.run_auto, p)


# ==========================================================================
class SubBasinsPage(Page):
    key, caption, module = "sous_bassins", "Sous-bassins versants", "sous_bassins"

    def build(self):
        self.state = note("Aucun bassin délimité dans la session.")
        self.lay.addWidget(self.state)
        f = Form("Découpage")
        self.bid = f.row("Bassin à découper (identifiant)", ispin(1, 1, 100000))
        self.method = f.row("Méthode", combo([(v, k) for k, v in basins.SUB_METHODS.items()]))
        self.smin = f.row("Ordre de Strahler minimal", ispin(2, 1, 20))
        self.amin = f.row("Superficie minimale des sous-bassins", spin(1.0, 0.0001, 1e6, 0.5, 4, "km²"))
        self.thr = f.row("Seuil d'accumulation du découpage", spin(1.0, 0.0001, 1e6, 0.5, 4, "km²"))
        self.rad = f.row("Rayon de recalage des points", spin(150, 0, 100000, 30, 0, "m"))
        self.lay.addWidget(f)
        g = Form("Points de contrôle (méthode « points »)")
        self.plist = QListWidget()
        self.plist.setMaximumHeight(90)
        g.full(self.plist)
        h = QHBoxLayout()
        b1 = QPushButton("Ajouter par clic")
        b1.clicked.connect(lambda: self.dock.pick_point(self.add_point))
        b2 = QPushButton("Depuis la couche")
        b2.clicked.connect(self.from_layer)
        b3 = QPushButton("Effacer")
        b3.clicked.connect(self.plist.clear)
        for b in (b1, b2, b3):
            h.addWidget(b)
        w = QWidget()
        w.setLayout(h)
        g.full(w)
        self.pts = QgsMapLayerComboBox()
        self.pts.setFilters(_filter("PointLayer"))
        g.row("Couche de points", self.pts)
        self.lay.addWidget(g)
        self.run_button("Découper en sous-bassins", self.run)

    def refresh(self):
        super().refresh()
        lb = self.dock.ctx.last_basin
        if lb:
            txt = ", ".join("n° {} ({:.2f} km²)".format(r["id"], r["aire_km2"]) for r in lb["rows"][:8])
            self.state.setText("Bassin(s) disponible(s) : {}{}".format(txt, "…" if len(lb["rows"]) > 8 else ""))
            self.bid.setMaximum(max(lb["ids"]))

    def add_point(self, pt):
        dem = self.dock.dem_layer()
        if dem is None:
            return
        tr = QgsCoordinateTransform(self.dock.iface.mapCanvas().mapSettings().destinationCrs(), dem.crs(),
                                    QgsProject.instance())
        p = tr.transform(pt)
        it = QListWidgetItem("{:.1f}, {:.1f}".format(p.x(), p.y()))
        it.setData(Qt.ItemDataRole.UserRole, (p.x(), p.y()))
        self.plist.addItem(it)

    def from_layer(self):
        lyr, dem = self.pts.currentLayer(), self.dock.dem_layer()
        if lyr is None or dem is None:
            return
        tr = QgsCoordinateTransform(lyr.crs(), dem.crs(), QgsProject.instance())
        feats = lyr.getSelectedFeatures() if lyr.selectedFeatureCount() else lyr.getFeatures()
        for f in feats:
            if f.geometry() and not f.geometry().isEmpty():
                p = tr.transform(f.geometry().centroid().asPoint())
                it = QListWidgetItem("{:.1f}, {:.1f}".format(p.x(), p.y()))
                it.setData(Qt.ItemDataRole.UserRole, (p.x(), p.y()))
                self.plist.addItem(it)

    def run(self):
        if self.dock.ctx.last_basin is None:
            self.dock.warn("Délimitez d'abord un bassin versant.")
            return
        pts = [self.plist.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.plist.count())]
        p = {"method": self.method.currentData(), "basin_id": self.bid.value(), "strahler_min": self.smin.value(),
             "min_area_km2": self.amin.value(), "threshold_km2": self.thr.value(), "points": pts,
             "snap_radius_m": self.rad.value()}
        if p["method"] == "points" and not pts:
            self.dock.warn("Ajoutez au moins un point de contrôle.")
            return
        self.dock.run_analysis("Découpage en sous-bassins", basins.run_subbasins, p)


# ==========================================================================
class ProfilesPage(Page):
    key, caption, module = "profils", "Profils topographiques", "profils"

    def build(self):
        f = Form("Tracés")
        self.kind = f.row("Type de profil", combo([(v, k) for k, v in profiles.KINDS.items()]))
        self.plist = QListWidget()
        self.plist.setMaximumHeight(110)
        f.full(self.plist)
        grid = QGridLayout()
        b = QPushButton("Tracer sur la carte")
        b.setToolTip("Clic gauche : sommets ; clic droit : terminer le profil")
        b.clicked.connect(lambda: self.dock.draw_line(self.add_line))
        grid.addWidget(b, 0, 0)
        b = QPushButton("Lignes d'une couche")
        b.clicked.connect(self.from_layer)
        grid.addWidget(b, 0, 1)
        b = QPushButton("Cours d'eau principal du bassin")
        b.clicked.connect(self.main_channel)
        grid.addWidget(b, 1, 0)
        b = QPushButton("Effacer la liste")
        b.clicked.connect(self.plist.clear)
        grid.addWidget(b, 1, 1)
        w = QWidget()
        w.setLayout(grid)
        f.full(w)
        self.lines = QgsMapLayerComboBox()
        self.lines.setFilters(_filter("LineLayer"))
        f.row("Couche de lignes", self.lines)
        self.lay.addWidget(f)
        g = Form("Paramètres")
        self.step = g.row("Pas d'échantillonnage", spin(0, 0, 100000, 5, 2, "m"), "0 = résolution du MNT")
        self.smooth = g.row("Lissage (moyenne mobile)", ispin(5, 1, 101, "points"))
        self.lay.addWidget(g)
        self.run_button("Calculer et afficher les profils", self.run)
        b = QPushButton("Ouvrir la fenêtre de comparaison des profils")
        b.clicked.connect(self.dock.open_profile_dialog)
        self.lay.addWidget(b)

    def _add(self, name, xs, ys):
        it = QListWidgetItem("{} ({} sommets)".format(name, len(xs)))
        it.setData(Qt.ItemDataRole.UserRole, {"name": name, "xs": list(xs), "ys": list(ys)})
        self.plist.addItem(it)

    def add_line(self, pts):
        dem = self.dock.dem_layer()
        if dem is None:
            return
        tr = QgsCoordinateTransform(self.dock.iface.mapCanvas().mapSettings().destinationCrs(), dem.crs(),
                                    QgsProject.instance())
        tp = [tr.transform(p) for p in pts]
        self._add("Profil {}".format(self.plist.count() + 1), [p.x() for p in tp], [p.y() for p in tp])

    def from_layer(self):
        lyr, dem = self.lines.currentLayer(), self.dock.dem_layer()
        if lyr is None or dem is None:
            return
        tr = QgsCoordinateTransform(lyr.crs(), dem.crs(), QgsProject.instance())
        feats = lyr.getSelectedFeatures() if lyr.selectedFeatureCount() else lyr.getFeatures(QgsFeatureRequest().setLimit(20))
        for f in feats:
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            parts = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
            for part in parts:
                tp = [tr.transform(p) for p in part]
                if len(tp) >= 2:
                    self._add("{} {}".format(lyr.name(), f.id()), [p.x() for p in tp], [p.y() for p in tp])

    def main_channel(self):
        lb = self.dock.ctx.last_basin
        st = self.dock.ctx.hydro
        if not lb or st is None:
            self.dock.warn("Délimitez d'abord un bassin versant.")
            return
        g = st.grid
        for i, path in sorted(lb["paths"].items())[:5]:
            import numpy as np
            cells = np.array(path)
            xs, ys = g.rc_to_xy(cells // g.ncols, cells % g.ncols)
            self._add("Cours d'eau principal, bassin {}".format(i), xs, ys)
        self.kind.setCurrentIndex(list(profiles.KINDS).index("longitudinal"))

    def run(self):
        p = self.dock.dem_params()
        if not p:
            return
        lines = [self.plist.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.plist.count())]
        if not lines:
            self.dock.warn("Ajoutez au moins un tracé de profil.")
            return
        p.update(lines=lines, kind=self.kind.currentData(), step_m=self.step.value() or None,
                 smooth_n=self.smooth.value())
        self.dock.run_analysis("Profils", profiles.run, p, after=lambda r: self.dock.open_profile_dialog())


# ==========================================================================
class CartographyPage(Page):
    key, caption = "carto", "Cartographie automatique"

    def build(self):
        self.lay.addWidget(note("Cartes A4 avec titre, légende, échelle, nord, SCR, sources, résolution, méthode, "
                                "date et unités. Les cartes grisées attendent l'exécution du module indiqué."))
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.lay.addWidget(self.list)
        h = QHBoxLayout()
        for text, state in (("Tout sélectionner", True), ("Aucune", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, s=state: self.check_all(s))
            h.addWidget(b)
        b = QPushButton("Actualiser")
        b.clicked.connect(self.refresh)
        h.addWidget(b)
        self.lay.addLayout(h)
        f = Form("Options")
        self.fmt = f.row("Format", combo([("PDF", "pdf"), ("PNG", "png"), ("SVG", "svg")]))
        self.atlas = f.full(check("Atlas : toutes les cartes dans un seul PDF", False))
        self.register = f.full(check("Ajouter les mises en page au projet (modifiables)", True))
        self.clip = f.full(check("Limiter les cartes à l'emprise du bassin versant", False))
        self.field = f.row("Paramètre de la carte de répartition", combo(
            [(lab, k) for k, lab, unit, nature, _ in MORPHO_FIELDS if k not in ("id", "exutoire_x", "exutoire_y")]))
        self.dpi = f.row("Résolution", ispin(200, 72, 600, "dpi"))
        self.lay.addWidget(f)
        self.run_button("Générer les cartes", self.generate)

    def check_all(self, state):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsEnabled:
                it.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def refresh(self):
        checked = {self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                   if self.list.item(i).checkState() == Qt.CheckState.Checked}
        self.list.clear()
        for key, title_, ok, hint in self.dock.map_builder.availability():
            it = QListWidgetItem(title_ if ok else "{} - {}".format(title_, hint))
            it.setData(Qt.ItemDataRole.UserRole, key)
            flags = Qt.ItemFlag.ItemIsUserCheckable
            if ok:
                flags |= Qt.ItemFlag.ItemIsEnabled
            it.setFlags(flags)
            it.setCheckState(Qt.CheckState.Checked if (ok and key in checked) else Qt.CheckState.Unchecked)
            self.list.addItem(it)

    def generate(self):
        keys = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if not keys:
            self.dock.warn("Cochez au moins une carte disponible.")
            return
        self.dock.generate_maps(keys, self.fmt.currentData(), self.atlas.isChecked(), self.register.isChecked(),
                                self.clip.isChecked(), self.field.currentData(), self.dpi.value())


# ==========================================================================
class StatisticsPage(Page):
    key, caption = "stats", "Statistiques"

    def build(self):
        self.res = QComboBox()
        self.lay.addWidget(self.res)
        self.tab = QComboBox()
        self.lay.addWidget(self.tab)
        self.view = TableView()
        self.view.setMinimumHeight(260)
        self.lay.addWidget(self.view)
        self.res.currentIndexChanged.connect(self.fill_tables)
        self.tab.currentIndexChanged.connect(self.show_table)
        grid = QGridLayout()
        for i, (text, key) in enumerate((("Exporter TXT", "txt"), ("Exporter CSV", "csv"), ("Exporter Excel", "xlsx"),
                                          ("Fiche PDF", "pdf"))):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, k=key: self.export(k))
            grid.addWidget(b, 0, i)
        self.lay.addLayout(grid)
        b = QPushButton("Comparer tous les bassins et sous-bassins de la session")
        b.clicked.connect(self.compare)
        self.lay.addWidget(b)
        b = QPushButton("Exporter toutes les statistiques de la session (TXT, CSV, Excel)")
        b.clicked.connect(self.export_all_stats)
        self.lay.addWidget(b)
        self.extra = []

    def refresh(self):
        cur = self.res.currentIndex()
        self.res.blockSignals(True)
        self.res.clear()
        for r in self.dock.registry.all():
            self.res.addItem("{} - {} ({})".format(r.module_title, r.title, r.created.strftime("%H:%M:%S")), r)
        for t in self.extra:
            self.res.addItem("Comparaison - {}".format(t.title), t)
        self.res.blockSignals(False)
        self.res.setCurrentIndex(cur if 0 <= cur < self.res.count() else self.res.count() - 1)
        self.fill_tables()

    def current(self):
        return self.res.currentData()

    def _tables(self):
        r = self.current()
        if r is None:
            return []
        if hasattr(r, "tables"):
            from ..engines.results import Table
            out = []
            if r.summary:
                out.append(Table("Résumé des résultats", ["Indicateur", "Valeur", "Unité"], [list(s) for s in r.summary]))
            return out + list(r.tables)
        return [r]

    def fill_tables(self, *a):
        self.tab.blockSignals(True)
        self.tab.clear()
        for t in self._tables():
            self.tab.addItem(t.title)
        self.tab.blockSignals(False)
        self.show_table(0)

    def show_table(self, i):
        tabs = self._tables()
        if 0 <= i < len(tabs):
            self.view.set_table(tabs[i])

    def export(self, kind):
        r = self.current()
        if r is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Dossier de destination",
                                                  os.path.join(self.dock.ctx.workspace, "09_Statistiques"))
        if not folder:
            return
        if not hasattr(r, "tables"):
            files = [ST.write_csv(r, os.path.join(folder, "comparaison.csv")),
                     ST.write_xlsx([r], os.path.join(folder, "comparaison.xlsx"))]
        elif kind == "pdf":
            from ..engines import report
            files = [report.result_pdf(r, folder)]
        else:
            files = ST.export_result(r, folder, (kind,))
        self.dock.done_files(files)

    def compare(self):
        rows = []
        for r in self.dock.registry.all():
            st = r.extra.get("state")
            if r.module in ("bassins", "sous_bassins") and st:
                for row in st["rows"]:
                    d = dict(row)
                    d["_source"] = "{} ({})".format(r.title, r.created.strftime("%H:%M:%S"))
                    rows.append(d)
        if not rows:
            self.dock.warn("Aucun bassin ni sous-bassin dans la session.")
            return
        from ..core.morphometry import FIELD_LABELS
        keys = ["_source", "id"] + basins.SUMMARY_KEYS
        fields = [("_source", "Analyse", "")] + [(k, FIELD_LABELS[k][0], FIELD_LABELS[k][1]) for k in keys[1:]]
        t = ST.compare_zones("Comparaison des bassins et sous-bassins", rows, fields)
        self.extra.append(t)
        self.refresh()
        self.res.setCurrentIndex(self.res.count() - 1)

    def export_all_stats(self):
        folder = QFileDialog.getExistingDirectory(self, "Dossier de destination", self.dock.ctx.workspace)
        if not folder:
            return
        files = []
        for r in self.dock.registry.all():
            files += ST.export_result(r, os.path.join(folder, "09_Statistiques", r.slug[:32]))
        self.dock.done_files(files)


# ==========================================================================
class SettingsPage(Page):
    key, caption = "settings", "Paramètres"

    def build(self):
        s = self.dock.settings
        f = Form("Espace de travail")
        self.ws = QgsFileWidget()
        self.ws.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.ws.setFilePath(s["workspace"])
        f.row("Répertoire de sortie", self.ws, "Les résultats y sont rangés par module (01_Topographie, …)")
        self.lay.addWidget(f)
        g = Form("Exportations")
        self.sep = g.row("Séparateur CSV", combo([("Point-virgule ( ; )", ";"), ("Virgule ( , )", ","), ("Tabulation", "\t")]))
        self.dec = g.row("Séparateur décimal", combo([("Virgule", ","), ("Point", ".")]))
        self.prec = g.row("Chiffres significatifs (TXT)", ispin(4, 1, 12))
        self.src = g.row("Sources des données (cartes)", QLineEdit(s.get("source", "")),
                         "Vide = nom du fichier MNT. Exemple : Copernicus DEM GLO-30, ESA")
        self.auth = g.row("Réalisation (cartes)", QLineEdit(s.get("author", "")),
                          "Vide = TGS - TerraGeo Science (Allaye GUINDO)")
        self.lay.addWidget(g)
        for w, key in ((self.sep, "csv_separator"), (self.dec, "decimal")):
            i = w.findData(s.get(key))
            if i >= 0:
                w.setCurrentIndex(i)
        self.prec.setValue(int(s.get("precision", 4)))
        b = QPushButton("Enregistrer les paramètres")
        b.clicked.connect(self.save)
        self.lay.addWidget(b)
        b = QPushButton("Vider le cache de calcul de la session")
        b.setToolTip("Libère la mémoire des directions d'écoulement et du dernier bassin")
        b.clicked.connect(self.clear_cache)
        self.lay.addWidget(b)

    def save(self):
        s = self.dock.settings
        s.update(workspace=self.ws.filePath() or s["workspace"], csv_separator=self.sep.currentData(),
                 decimal=self.dec.currentData(), precision=self.prec.value(), source=self.src.text().strip(),
                 author=self.auth.text().strip())
        self.dock.apply_settings()
        self.dock.log("Paramètres enregistrés.")

    def clear_cache(self):
        self.dock.ctx.clear()
        self.dock.log("Cache de calcul vidé.")


PAGES = [DashboardPage, DemPage, TopographyPage, MorphometryPage, GeomorphologyPage, HydrologyPage, BasinsPage,
         SubBasinsPage, ProfilesPage, CartographyPage, StatisticsPage, SettingsPage]
