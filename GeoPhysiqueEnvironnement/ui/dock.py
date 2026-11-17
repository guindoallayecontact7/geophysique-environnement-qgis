# -*- coding: utf-8 -*-
"""Panneau principal : navigation par rubriques, MNT actif, tâches, journal."""
import datetime
import os
import shutil
import tempfile

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QFrame,
)
from qgis.core import Qgis, QgsApplication, QgsProject, QgsRasterLayer, QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox, QgsRasterBandComboBox

from ..analyses.common import Context
from ..engines import statistics as ST, report as R, providers as P
from ..engines.results import ResultRegistry
from .layers import add_result_layers, project_layer
from .mapping import MapBuilder, export_all, export_result_bundle
from .maptools import PointTool, LineTool
from .pages import PAGES, _filter
from .tasks import JobTask
from .widgets import TableDialog

SETTINGS_PREFIX = "GeoPhysiqueEnvironnement/"
MIN_WIDTH = 760       # en dessous, certaines rubriques défilent horizontalement
PREFERRED_WIDTH = 820  # largeur à l'ouverture
DEFAULT_SETTINGS = {
    "workspace": os.path.join(os.path.expanduser("~"), "GeoPhysique_Environnement"),
    "csv_separator": ";", "decimal": ",", "precision": 4, "source": "", "author": "",
}


def load_settings():
    qs = QSettings()
    out = {}
    for k, v in DEFAULT_SETTINGS.items():
        val = qs.value(SETTINGS_PREFIX + k, v)
        if isinstance(v, int):
            try:
                val = int(val)
            except (TypeError, ValueError):
                val = v
        out[k] = val
    return out


def save_settings(s):
    qs = QSettings()
    for k in DEFAULT_SETTINGS:
        qs.setValue(SETTINGS_PREFIX + k, s.get(k))


class MainDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("GeoPhysique & Environnement 2.0", parent)
        self.setObjectName("GeoPhysiqueEnvironnementDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(MIN_WIDTH)
        self.iface = iface
        self.settings = load_settings()
        self.registry = ResultRegistry()
        self.ctx = Context(self.settings["workspace"])
        self.map_builder = MapBuilder(self.registry, self.settings)
        self.task = None
        self.run_buttons = []
        self.map_files = []
        self._tool = None
        self._prev_tool = None
        self.profile_dialog = None
        self.apply_settings(save=False)
        self._build()
        self.registry.listeners.append(lambda r: self.refresh_pages())

    # ------------------------------------------------------------------ UI
    def _build(self):
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(4, 4, 4, 4)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>MNT</b>"))
        self.dem = QgsMapLayerComboBox()
        self.dem.setFilters(_filter("RasterLayer"))
        self.dem.setToolTip("Modèle numérique de terrain utilisé par toutes les rubriques")
        head.addWidget(self.dem, 1)
        head.addWidget(QLabel("Bande"))
        self.band = QgsRasterBandComboBox()
        self.band.setMaximumWidth(110)
        head.addWidget(self.band)
        v.addLayout(head)
        self.dem_state = QLabel()
        self.dem_state.setWordWrap(True)
        self.dem_state.setStyleSheet("font-size:8.5pt;")
        v.addWidget(self.dem_state)

        split = QSplitter(Qt.Orientation.Vertical)
        body = QWidget()
        h = QHBoxLayout(body)
        h.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget()
        self.nav.setMaximumWidth(175)
        self.nav.setMinimumWidth(140)
        self.stack = QStackedWidget()
        self.pages = {}
        for cls in PAGES:
            page = cls(self)
            self.pages[page.key] = page
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.Shape.NoFrame)
            sc.setWidget(page)
            self.stack.addWidget(sc)
            self.nav.addItem(QListWidgetItem(page.caption))
        self.nav.currentRowChanged.connect(self._on_nav)
        h.addWidget(self.nav)
        h.addWidget(self.stack, 1)
        split.addWidget(body)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        pr = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p %")
        pr.addWidget(self.progress, 1)
        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        pr.addWidget(self.cancel_btn)
        bl.addLayout(pr)
        self.logbox = QTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setPlaceholderText("Journal des traitements")
        bl.addWidget(self.logbox)
        split.addWidget(bottom)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)
        v.addWidget(split, 1)
        self.setWidget(root)
        self.dem.layerChanged.connect(self._on_dem)
        self.nav.setCurrentRow(0)
        self._on_dem(self.dem.currentLayer())

    def _on_nav(self, row):
        self.stack.setCurrentIndex(row)
        page = list(self.pages.values())[row]
        page.refresh()

    def _on_dem(self, layer):
        self.band.setLayer(layer)
        if layer is None:
            self.dem_state.setText("<span style='color:#b2182b'>Aucun raster dans le projet : ajoutez un MNT.</span>")
        else:
            crs = layer.crs()
            geo = crs.isGeographic()
            self.dem_state.setText("{} - {} - {:g} m - {} × {}{}".format(
                layer.name(), crs.authid() or "SCR inconnu", layer.rasterUnitsPerPixelX(), layer.width(),
                layer.height(),
                " - <span style='color:#b2182b'>SCR géographique : reprojetez (Gestion des MNT)</span>" if geo else ""))
        for p in self.pages.values():
            p.on_dem_changed()

    def refresh_pages(self):
        for p in self.pages.values():
            p.refresh()

    def apply_settings(self, save=True):
        s = self.settings
        ST.SETTINGS.csv_separator = s.get("csv_separator", ";")
        ST.SETTINGS.decimal = s.get("decimal", ",")
        ST.SETTINGS.precision = int(s.get("precision", 4))
        ws = s.get("workspace") or DEFAULT_SETTINGS["workspace"]
        try:
            os.makedirs(ws, exist_ok=True)
        except OSError:
            ws = os.path.join(tempfile.gettempdir(), "GeoPhysique_Environnement")
            os.makedirs(ws, exist_ok=True)
        self.ctx.workspace = ws
        if save:
            save_settings(s)

    # ------------------------------------------------------------------ messages
    def log(self, text):
        self.logbox.append("[{}] {}".format(datetime.datetime.now().strftime("%H:%M:%S"), text))

    def warn(self, text):
        self.log("⚠ " + text)
        self.iface.messageBar().pushWarning("GeoPhysique", text)

    def done_files(self, files):
        files = [f for f in files if f]
        if not files:
            return
        self.log("{} fichier(s) écrit(s) dans {}".format(len(files), os.path.dirname(files[0])))
        self.iface.messageBar().pushSuccess("GeoPhysique", "{} fichier(s) exporté(s) : {}".format(
            len(files), os.path.dirname(files[0])))

    # ------------------------------------------------------------------ MNT
    def dem_layer(self):
        return self.dem.currentLayer()

    def dem_params(self, require_projected=True):
        lyr = self.dem_layer()
        if lyr is None:
            self.warn("Sélectionnez un MNT (raster) en haut du panneau.")
            return None
        if lyr.providerType() != "gdal":
            self.warn("Le MNT doit être un fichier raster local (fournisseur GDAL).")
            return None
        path = lyr.source().split("|")[0]
        if not os.path.exists(path):
            self.warn("Fichier MNT introuvable : {}".format(path))
            return None
        if require_projected and lyr.crs().isGeographic():
            self.warn("Le MNT est en coordonnées géographiques. Reprojetez-le en UTM (rubrique Gestion des MNT).")
            return None
        return {"dem_path": path, "band": max(1, self.band.currentBand())}

    def add_dem(self, path, name):
        lyr = QgsRasterLayer(path, name, "gdal")
        if not lyr.isValid():
            self.warn("Raster illisible : {}".format(path))
            return
        QgsProject.instance().addMapLayer(lyr)
        self.dem.setLayer(lyr)
        self.log("MNT actif : {}".format(path))

    def open_dem_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un MNT", "", "Rasters (*.tif *.tiff *.vrt *.img *.asc)")
        if path:
            self.add_dem(path, os.path.splitext(os.path.basename(path))[0])

    # ------------------------------------------------------------------ tâches
    def _busy(self, busy):
        for b in self.run_buttons:
            b.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        if not busy:
            self.progress.setValue(0)

    def run_analysis(self, description, fn, params, after=None):
        def done(result):
            self._busy(False)
            self.task = None
            n = len(add_result_layers(result))
            self.registry.add(result)
            self.log("✔ {} terminée : {} couche(s) ajoutée(s), dossier {}".format(result.title, n, result.folder))
            for w in result.warnings:
                self.log("⚠ " + w)
            self.iface.messageBar().pushSuccess("GeoPhysique", "{} terminée.".format(result.title))
            if after:
                after(result)
        self._start(description, fn, params, done)

    def run_raw(self, description, fn, params, on_done):
        def done(result):
            self._busy(False)
            self.task = None
            on_done(result)
        self._start(description, fn, params, done)

    def _start(self, description, fn, params, done):
        if self.task is not None:
            self.warn("Un traitement est déjà en cours.")
            return

        def failed(msg, canceled):
            self._busy(False)
            self.task = None
            if canceled:
                self.log("Traitement annulé.")
                return
            first = msg.strip().splitlines()[0] if msg else "Erreur"
            self.log("✘ {} : {}".format(description, msg))
            self.iface.messageBar().pushCritical("GeoPhysique", "{} : {}".format(description, first))

        self.task = JobTask("GeoPhysique - " + description, fn, params, self.ctx, done, failed)
        self.task.progressChanged.connect(lambda v: self.progress.setValue(int(v)))
        self.task.message.connect(self.log)
        self._busy(True)
        self.log("▶ {}…".format(description))
        QgsApplication.taskManager().addTask(self.task)

    def cancel(self):
        if self.task is not None:
            self.task.cancel()
            self.log("Annulation demandée…")

    # ------------------------------------------------------------------ outils de carte
    def _set_tool(self, tool):
        canvas = self.iface.mapCanvas()
        self._prev_tool = canvas.mapTool()
        self._tool = tool
        canvas.setMapTool(tool)

    def pick_point(self, callback):
        tool = PointTool(self.iface.mapCanvas())

        def got(pt):
            callback(pt)
            tool.clear()
            if self._prev_tool is not None:
                self.iface.mapCanvas().setMapTool(self._prev_tool)
        tool.picked.connect(got)
        self._set_tool(tool)
        self.log("Cliquez sur la carte pour placer le point.")

    def draw_line(self, callback):
        tool = LineTool(self.iface.mapCanvas())
        tool.finished.connect(callback)
        self._set_tool(tool)
        self.log("Tracez le profil : clic gauche pour chaque sommet, clic droit pour terminer.")

    def launch_algorithm(self, alg_id):
        import processing
        real = P.resolve_algorithm(alg_id)
        if real is None:
            self.warn("Algorithme « {} » indisponible : activez le fournisseur dans Traitements > Options.".format(alg_id))
            return
        params = {}
        lyr = self.dem_layer()
        if lyr is not None:
            alg = QgsApplication.processingRegistry().algorithmById(real)
            for p in alg.parameterDefinitions():
                if p.name().upper() in ("INPUT", "ELEVATION", "DEM", "DEM_INPUT"):
                    params[p.name()] = lyr.id()
                    break
        self.log("Ouverture de l'algorithme : {}".format(real))
        try:
            processing.execAlgorithmDialog(real, params)
        except Exception as exc:  # noqa: BLE001
            self.warn("Erreur de lancement : {}".format(exc))

    # ------------------------------------------------------------------ résultats
    def show_stats(self, result):
        dlg = TableDialog(result, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.open()

    def _ask_dir(self, sub):
        start = os.path.join(self.ctx.workspace, sub)
        os.makedirs(start, exist_ok=True)
        return QFileDialog.getExistingDirectory(self, "Dossier de destination", start)

    def results_action(self, box, key):
        r = box.result()
        if r is None:
            return
        try:
            if key == "stats":
                self.show_stats(r)
            elif key in ("txt", "csv", "xlsx"):
                d = self._ask_dir("09_Statistiques")
                if d:
                    self.done_files(ST.export_result(r, d, (key,)))
            elif key == "pdf":
                d = self._ask_dir("10_Rapports")
                if d:
                    self.done_files([R.result_pdf(r, d)])
            elif key == "map":
                spec = box.selected_spec()
                ms = self.map_builder.spec_for_layer(spec, r) if spec else None
                if ms is None:
                    self.warn("Couche introuvable dans le projet.")
                    return
                files = self.map_builder.export([ms], os.path.join(self.ctx.workspace, "08_Cartes"), "pdf",
                                                register=True)
                self.map_files += files
                self.done_files(files)
                layout = QgsProject.instance().layoutManager().layouts()[-1]
                self.iface.openLayoutDesigner(layout)
            elif key == "png":
                spec = box.selected_spec()
                ms = self.map_builder.spec_for_layer(spec, r) if spec else None
                if ms is None:
                    return
                path, _ = QFileDialog.getSaveFileName(self, "Exporter la carte en PNG",
                                                      os.path.join(self.ctx.workspace, "08_Cartes", ms.key + ".png"),
                                                      "PNG (*.png)")
                if path:
                    from ..engines import cartography as C
                    C.export_layout(C.build_layout([ms], ms.title), path, "png")
                    self.map_files.append(path)
                    self.done_files([path])
            elif key == "geotiff":
                spec = box.selected_spec()
                if spec is None or spec.kind != "raster":
                    spec = next((s for s in r.layers if s.kind == "raster"), None)
                path, _ = QFileDialog.getSaveFileName(self, "Exporter en GeoTIFF",
                                                      os.path.join(self.ctx.workspace, os.path.basename(spec.path)),
                                                      "GeoTIFF (*.tif)")
                if path:
                    from osgeo import gdal
                    gdal.Translate(path, spec.path, options=gdal.TranslateOptions(format="GTiff",
                                                                                   creationOptions=["COMPRESS=DEFLATE"]))
                    self.done_files([path])
            elif key == "gpkg":
                spec = box.selected_spec()
                if spec is None or spec.kind != "vector":
                    spec = next((s for s in r.layers if s.kind == "vector"), None)
                path, _ = QFileDialog.getSaveFileName(self, "Exporter en GeoPackage",
                                                      os.path.join(self.ctx.workspace, spec.layer + ".gpkg"),
                                                      "GeoPackage (*.gpkg)")
                if path:
                    from osgeo import gdal
                    gdal.VectorTranslate(path, spec.path, options=gdal.VectorTranslateOptions(
                        format="GPKG", layers=[spec.layer], accessMode="overwrite"))
                    self.done_files([path])
            elif key == "all":
                d = self._ask_dir("")
                if d:
                    folder = os.path.join(d, "{}_{}".format(r.slug[:32], r.created.strftime("%Y%m%d_%H%M%S")))
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    try:
                        files = export_result_bundle(r, folder, self.map_builder)
                    finally:
                        QApplication.restoreOverrideCursor()
                    self.done_files(files)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.warn("Exportation impossible : {}".format(exc))

    def generate_maps(self, keys, fmt, atlas, register, clip, field, dpi):
        specs, missing = [], []
        for k in keys:
            ms = self.map_builder.spec_for_key(k, clip, field)
            (specs if ms is not None else missing).append(ms if ms is not None else k)
        if missing:
            self.log("Cartes non produites (données manquantes) : {}".format(", ".join(missing)))
        if not specs:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            files = self.map_builder.export(specs, os.path.join(self.ctx.workspace, "08_Cartes"), fmt, atlas,
                                            register, dpi=dpi)
        except Exception as exc:  # noqa: BLE001
            self.warn("Génération des cartes impossible : {}".format(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.map_files += files
        self.done_files(files)

    def export_everything(self):
        if not self.registry.all():
            self.warn("Aucune analyse exécutée dans la session.")
            return
        d = QFileDialog.getExistingDirectory(self, "Dossier de l'exportation globale", self.ctx.workspace)
        if not d:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            base, files = export_all(self.registry, d, self.map_builder, self.map_files,
                                     self.pages["dashboard"].maps_too.isChecked(),
                                     lambda v: self.progress.setValue(int(v)))
        except Exception as exc:  # noqa: BLE001
            self.warn("Exportation globale impossible : {}".format(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.progress.setValue(0)
        self.log("Exportation globale : {} fichier(s) dans {}".format(len(files), base))
        self.iface.messageBar().pushSuccess("GeoPhysique", "Exportation globale : {}".format(base))

    # ------------------------------------------------------------------ profils
    def open_profile_dialog(self):
        from .profile_dialog import ProfileDialog
        items = self.registry.by_module("profils")
        if not items:
            self.warn("Calculez d'abord un profil (rubrique Profils topographiques).")
            return
        if self.profile_dialog is None:
            self.profile_dialog = ProfileDialog(self)
        self.profile_dialog.load(self.registry)
        self.profile_dialog.show()
        self.profile_dialog.raise_()

    def cleanup(self):
        if self.task is not None:
            self.task.cancel()
        canvas = self.iface.mapCanvas()
        if self._tool is not None and canvas.mapTool() is self._tool:
            canvas.unsetMapTool(self._tool)
        if self.profile_dialog is not None:
            self.profile_dialog.close()
            self.profile_dialog.deleteLater()
            self.profile_dialog = None
