# -*- coding: utf-8 -*-
"""Test d'intégration dans QGIS (sans affichage) : panneau, tâches, couches, cartes, exports.

Usage : python-qgis-ltr.bat tests/test_gui.py <mnt.tif> <dossier_de_sortie> [x y de l'exutoire]
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from qgis.core import QgsApplication, QgsProject, QgsRasterLayer  # noqa: E402

qgs = QgsApplication([], True)
QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
qgs.initQgis()
for p in (os.path.join(os.environ.get("QGIS_PREFIX_PATH", ""), "python", "plugins"),):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402
Processing.initialize()

from qgis.PyQt.QtCore import QObject  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow, QFileDialog  # noqa: E402
from qgis.gui import QgsMapCanvas, QgsMessageBar  # noqa: E402


class Iface(QObject):
    def __init__(self):
        super().__init__()
        self.win = QMainWindow()
        self.canvas = QgsMapCanvas(self.win)
        self.bar = QgsMessageBar(self.win)
        self.menus, self.icons, self.docks, self.designers = [], [], [], []

    def mainWindow(self):
        return self.win

    def mapCanvas(self):
        return self.canvas

    def messageBar(self):
        return self.bar

    def addPluginToMenu(self, m, a):
        self.menus.append(a)

    def removePluginMenu(self, m, a):
        self.menus.remove(a)

    def addToolBarIcon(self, a):
        self.icons.append(a)

    def removeToolBarIcon(self, a):
        self.icons.remove(a)

    def addDockWidget(self, area, d):
        self.docks.append(d)
        self.win.addDockWidget(area, d)

    def removeDockWidget(self, d):
        self.docks.remove(d)
        self.win.removeDockWidget(d)

    def openLayoutDesigner(self, layout):
        self.designers.append(layout)


def wait(dock, timeout=900):
    t = time.time()
    while dock.task is not None and time.time() - t < timeout:
        QgsApplication.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        QgsApplication.processEvents()
    assert dock.task is None, "tâche non terminée"


def main():
    dem, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    # boîtes de dialogue de fichiers remplacées pour le test
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out)
    QFileDialog.getSaveFileName = staticmethod(lambda parent, cap, start, *a, **k: (
        os.path.join(out, os.path.basename(start)), ""))

    import GeoPhysiqueEnvironnement as pkg
    iface = Iface()
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    assert len(iface.menus) == 2 and len(iface.icons) == 1
    lyr = QgsRasterLayer(dem, "MNT test", "gdal")
    assert lyr.isValid()
    QgsProject.instance().addMapLayer(lyr)
    iface.canvas.setDestinationCrs(lyr.crs())
    iface.canvas.setExtent(lyr.extent())
    plugin.show_panel()
    dock = plugin.dock
    dock.settings["workspace"] = os.path.join(out, "espace")
    dock.apply_settings(save=False)
    dock.dem.setLayer(lyr)
    print("Rubriques :", [p.caption for p in dock.pages.values()])
    errors = []
    orig_failed = dock.iface.messageBar().pushCritical
    dock.iface.messageBar().pushCritical = lambda t, m: (errors.append(m), orig_failed(t, m))

    pages = dock.pages
    t0 = time.time()
    pages["topo"].run(); wait(dock)
    pages["hydro"].settings.fill.setCurrentIndex(0)
    pages["hydro"].run(); wait(dock)
    pages["morpho"].run(); wait(dock)
    pages["geomorph"].scale.setValue(90)
    pages["geomorph"].run(); wait(dock)
    b = pages["bassins"]
    b.mode.setCurrentIndex(1)
    b.crs.setCrs(lyr.crs())
    x, y = (float(sys.argv[3]), float(sys.argv[4])) if len(sys.argv) >= 5 else (lyr.extent().center().x(),
                                                                                lyr.extent().center().y())
    b.x.setValue(x)
    b.y.setValue(y)
    b.rad.setValue(200)
    b.run_outlet(); wait(dock)
    sb = pages["sous_bassins"]
    sb.method.setCurrentIndex(sb.method.findData("strahler"))
    sb.smin.setValue(3)
    sb.run(); wait(dock)
    pp = pages["profils"]
    pp.main_channel()
    e = lyr.extent()
    pp._add("Transect", [e.xMinimum() + 0.3 * e.width(), e.xMinimum() + 0.7 * e.width()],
            [e.center().y(), e.center().y()])
    pp.run(); wait(dock)
    print("Analyses : {:.0f} s ; erreurs : {}".format(time.time() - t0, errors))
    assert not errors, errors
    for r in dock.registry.all():
        print("  - {:<45} couches={:2d} tableaux={:2d}".format(r.title, len(r.layers), len(r.tables)))
    n_layers = len(QgsProject.instance().mapLayers())
    print("Couches dans le projet :", n_layers)

    # rubrique Résultats – Statistiques – Exportation de chaque module
    for key in ("topo", "hydro", "morpho", "geomorph", "bassins", "sous_bassins", "profils"):
        box = pages[key].results
        box.refresh()
        for action in ("txt", "csv", "xlsx", "pdf", "map", "png", "geotiff", "gpkg"):
            if box.btn[action].isEnabled():
                dock.results_action(box, action)
    dock.results_action(pages["bassins"].results, "all")
    print("Mises en page ouvertes :", len(iface.designers))

    # cartographie automatique : toutes les cartes disponibles, puis atlas
    cp = pages["carto"]
    cp.refresh()
    avail = [k for k, t, ok, h in dock.map_builder.availability() if ok]
    print("Cartes disponibles ({}/{}) : {}".format(len(avail), len(dock.map_builder.availability()), avail))
    cp.check_all(True)
    cp.fmt.setCurrentIndex(cp.fmt.findData("png"))
    cp.generate()
    cp.atlas.setChecked(True)
    cp.generate()
    # statistiques : comparaison
    pages["stats"].refresh()
    pages["stats"].compare()
    # exportation globale
    dock.export_everything()
    print("Fichiers de cartes :", len(dock.map_files))
    # fenêtre des profils
    dock.open_profile_dialog()
    dock.profile_dialog.export("svg")
    print("Journal (fin) :")
    print("\n".join(dock.logbox.toPlainText().splitlines()[-12:]))
    assert not errors, errors
    plugin.unload()
    assert not iface.menus and not iface.icons and not iface.docks
    print("Déchargement propre : OK")
    QgsProject.instance().clear()
    iface.win.deleteLater()
    QgsApplication.processEvents()


if __name__ == "__main__":
    try:
        main()
    finally:
        qgs.exitQgis()
