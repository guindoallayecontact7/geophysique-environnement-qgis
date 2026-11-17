# -*- coding: utf-8 -*-
"""TERRA-MORPHO GIS - cycle de vie de l'extension QGIS."""
import configparser
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtWidgets import QAction, QMessageBox

PLUGIN_DIR = os.path.dirname(__file__)
MENU = "&TERRA-MORPHO GIS"


def plugin_version():
    """Read the version from metadata.txt so the About box never drifts."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
    return parser.get("general", "version", fallback="?")


class GeoPhysiquePlugin:
    """Ajoute le panneau TERRA-MORPHO GIS (rubriques d'analyse)."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.about_action = None
        self.dock = None

    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, "icons", "plugin.png"))
        self.action = QAction(icon, "TERRA-MORPHO GIS", self.iface.mainWindow())
        self.action.setToolTip("Analyses topographiques, morphométriques, géomorphologiques et hydrologiques")
        self.action.triggered.connect(self.show_panel)
        self.about_action = QAction("À propos de TERRA-MORPHO GIS", self.iface.mainWindow())
        self.about_action.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(MENU, self.action)
        self.iface.addPluginToMenu(MENU, self.about_action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.about_action:
            self.iface.removePluginMenu(MENU, self.about_action)
            self.about_action.deleteLater()
            self.about_action = None
        if self.dock:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    def show_panel(self):
        if self.dock is None:
            from .ui.dock import MainDock
            self.dock = MainDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            from .ui.dock import PREFERRED_WIDTH
            try:
                self.iface.mainWindow().resizeDocks([self.dock], [PREFERRED_WIDTH], Qt.Orientation.Horizontal)
            except AttributeError:
                self.dock.resize(PREFERRED_WIDTH, self.dock.height())
        self.dock.show()
        self.dock.raise_()

    def show_about(self):
        box = QMessageBox(self.iface.mainWindow())
        box.setWindowTitle("À propos - TERRA-MORPHO GIS")
        logo = QPixmap(os.path.join(PLUGIN_DIR, "icons", "logo.png"))
        if not logo.isNull():
            box.setIconPixmap(logo.scaledToWidth(360, Qt.TransformationMode.SmoothTransformation))
        box.setText(
            "<b>TERRA-MORPHO GIS</b><br/>Version {}<br/>Auteur : Allaye GUINDO<br/><br/>"
            "Extension QGIS dédiée à la géographie physique et à l'environnement : analyses "
            "topographiques, morphométriques, géomorphologiques et hydrologiques, délimitation "
            "des bassins et sous-bassins versants, profils, cartographie et statistiques.<br/><br/>"
            "Anciennement GeoPhysique &amp; Environnement. Licence GPL-2.0 ou ultérieure.".format(plugin_version()))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()
