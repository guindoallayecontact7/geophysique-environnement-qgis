# -*- coding: utf-8 -*-
"""GeoPhysique & Environnement — cycle de vie de l'extension QGIS."""
import configparser
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

PLUGIN_DIR = os.path.dirname(__file__)
MENU = "&GeoPhysique"


def plugin_version():
    """Read the version from metadata.txt so the About box never drifts."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
    return parser.get("general", "version", fallback="?")


class GeoPhysiquePlugin:
    """Ajoute le panneau GeoPhysique & Environnement 2.0 (rubriques d'analyse)."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.about_action = None
        self.dock = None

    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, "icons", "plugin.svg"))
        self.action = QAction(icon, "GeoPhysique & Environnement", self.iface.mainWindow())
        self.action.setToolTip("Analyses topographiques, morphométriques, géomorphologiques et hydrologiques")
        self.action.triggered.connect(self.show_panel)
        self.about_action = QAction("À propos de GeoPhysique & Environnement", self.iface.mainWindow())
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
        self.dock.show()
        self.dock.raise_()

    def show_about(self):
        QMessageBox.about(
            self.iface.mainWindow(),
            "À propos — GeoPhysique & Environnement",
            "GeoPhysique & Environnement\n"
            "Version {}\n"
            "Auteur : Allaye GUINDO\n\n".format(plugin_version()) +
            "Extension QGIS dédiée à la géographie physique et à l'environnement : analyses "
            "topographiques, morphométriques, géomorphologiques et hydrologiques, délimitation "
            "des bassins et sous-bassins versants, profils, cartographie et statistiques.\n\n"
            "Licence GPL-2.0 ou ultérieure."
        )
