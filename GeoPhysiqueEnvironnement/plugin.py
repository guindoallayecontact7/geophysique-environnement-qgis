# -*- coding: utf-8 -*-
"""GeoPhysique & Environnement — initial QGIS plugin scaffold."""
import configparser
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QWidget, QVBoxLayout, QLabel,
    QPushButton, QComboBox, QTextEdit, QMessageBox, QGroupBox
)
from qgis.core import QgsProject, QgsRasterLayer, QgsApplication
import processing

PLUGIN_DIR = os.path.dirname(__file__)


def plugin_version():
    """Read the version from metadata.txt so the About box never drifts."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
    return parser.get("general", "version", fallback="?")


class GeoPhysiquePlugin:
    """Adds a dock panel with starter terrain and hydrology tools."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.raster_combo = None
        self.log = None

    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, "icons", "plugin.svg"))
        self.action = QAction(icon, "GeoPhysique & Environnement", self.iface.mainWindow())
        self.action.triggered.connect(self.show_panel)
        self.iface.addPluginToMenu("&GeoPhysique", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("&GeoPhysique", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
            self.raster_combo = None
            self.log = None

    def show_panel(self):
        if self.dock is None:
            self._build_panel()
        self.refresh_rasters()
        self.dock.show()
        self.dock.raise_()

    def _build_panel(self):
        self.dock = QDockWidget("GeoPhysique & Environnement", self.iface.mainWindow())
        self.dock.setObjectName("GeoPhysiqueEnvironnementDock")
        self.dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        root = QWidget()
        layout = QVBoxLayout(root)
        intro = QLabel(
            "Auteur : Allaye GUINDO\n"
            "Hydrologie · Bassins versants · Morphométrie\n"
            "Sélectionnez un MNT en entrée. Les algorithmes disponibles dépendent "
            "des fournisseurs installés dans votre QGIS."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        about_button = QPushButton("À propos du plugin")
        about_button.clicked.connect(self.show_about)
        layout.addWidget(about_button)

        source_group = QGroupBox("Données d'entrée")
        source_layout = QVBoxLayout(source_group)
        self.raster_combo = QComboBox()
        source_layout.addWidget(QLabel("Modèle numérique de terrain (raster) :"))
        source_layout.addWidget(self.raster_combo)
        refresh = QPushButton("Actualiser les rasters")
        refresh.clicked.connect(self.refresh_rasters)
        source_layout.addWidget(refresh)
        layout.addWidget(source_group)

        terrain_group = QGroupBox("Morphométrie et terrain")
        terrain_layout = QVBoxLayout(terrain_group)
        self._add_algorithm_button(terrain_layout, "Calculer la pente", "gdal:slope")
        self._add_algorithm_button(terrain_layout, "Calculer l'exposition", "gdal:aspect")
        self._add_algorithm_button(terrain_layout, "Créer un ombrage", "gdal:hillshade")
        self._add_algorithm_button(terrain_layout, "Calculer les courbes de niveau", "gdal:contour")
        layout.addWidget(terrain_group)

        hydro_group = QGroupBox("Hydrologie")
        hydro_layout = QVBoxLayout(hydro_group)
        self._add_algorithm_button(hydro_layout, "Combler les cellules NoData (GDAL)", "gdal:fillnodata")
        self._add_algorithm_button(hydro_layout, "Ouvrir GRASS r.watershed", "grass:r.watershed")
        layout.addWidget(hydro_group)

        note = QLabel(
            "Note : le remplissage des dépressions et la délimitation de bassins versants "
            "ne sont pas interchangeables. gdal:fillnodata est un outil de comblement "
            "des données NoData, pas un algorithme hydrologique de remplissage des puits. "
            "Pour une analyse hydrologique, utilisez un outil adapté tel que GRASS r.fill.dir / "
            "r.watershed ou un outil équivalent disponible dans votre installation."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #8a4b08;")
        layout.addWidget(note)

        layout.addWidget(QLabel("Journal"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(115)
        layout.addWidget(self.log)
        layout.addStretch(1)
        self.dock.setWidget(root)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    def show_about(self):
        QMessageBox.about(
            self.iface.mainWindow(),
            "À propos — GeoPhysique & Environnement",
            "GeoPhysique & Environnement\n"
            "Version {}\n"
            "Auteur : Allaye GUINDO\n\n".format(plugin_version()) +
            "Extension QGIS dédiée à la géographie physique et à l'environnement, "
            "avec des outils de terrain, d'hydrologie et de morphométrie."
        )

    def _add_algorithm_button(self, parent_layout, label, algorithm_id):
        button = QPushButton(label)
        button.clicked.connect(lambda checked=False, alg=algorithm_id: self.launch_algorithm(alg))
        parent_layout.addWidget(button)

    def refresh_rasters(self):
        if self.raster_combo is None:
            return
        current_id = self.raster_combo.currentData()
        self.raster_combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer) and layer.isValid():
                self.raster_combo.addItem(layer.name(), layer.id())
        if current_id:
            idx = self.raster_combo.findData(current_id)
            if idx >= 0:
                self.raster_combo.setCurrentIndex(idx)
        if self.raster_combo.count() == 0:
            self.raster_combo.addItem("Aucun raster valide dans le projet", None)

    def launch_algorithm(self, algorithm_id):
        if not QgsApplication.processingRegistry().algorithmById(algorithm_id):
            QMessageBox.warning(
                self.iface.mainWindow(), "Algorithme indisponible",
                "L'algorithme « {} » n'est pas disponible. Vérifiez que le fournisseur "
                "GDAL ou GRASS GIS est activé dans Traitements > Options > Fournisseurs.".format(algorithm_id)
            )
            self._log("Indisponible : {}".format(algorithm_id))
            return
        params = {}
        # Preselect the selected MNT when the algorithm exposes a conventional raster input.
        layer_id = self.raster_combo.currentData() if self.raster_combo else None
        alg = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        if layer_id:
            for p in alg.parameterDefinitions():
                name = p.name().upper()
                if name in ("INPUT", "ELEVATION", "DEM"):
                    params[p.name()] = layer_id
                    break
        self._log("Ouverture de l'algorithme : {}".format(algorithm_id))
        try:
            processing.execAlgorithmDialog(algorithm_id, params)
        except Exception as exc:
            QMessageBox.critical(self.iface.mainWindow(), "Erreur de lancement", str(exc))
            self._log("Erreur : {}".format(exc))

    def _log(self, message):
        if self.log:
            self.log.append(message)
