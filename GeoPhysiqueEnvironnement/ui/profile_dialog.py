# -*- coding: utf-8 -*-
"""Fenêtre interactive des profils : affichage, comparaison, exportation PNG / SVG / PDF."""
import os

import numpy as np
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                                 QPushButton, QVBoxLayout, QCheckBox)

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
    HAS_QT_MPL = True
except Exception:  # noqa: BLE001 - repli sur les images PNG déjà produites
    HAS_QT_MPL = False

from ..engines import charts


class ProfileDialog(QDialog):
    def __init__(self, dock):
        super().__init__(dock)
        self.dock = dock
        self.setWindowTitle("Profils topographiques — GeoPhysique & Environnement 2.0")
        self.resize(1050, 640)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("Profils calculés (cochez pour comparer)"))
        self.list = QListWidget()
        self.list.itemChanged.connect(self.redraw)
        left.addWidget(self.list, 1)
        self.forms = QCheckBox("Afficher les formes (profil seul)")
        self.forms.setChecked(True)
        self.forms.toggled.connect(self.redraw)
        left.addWidget(self.forms)
        self.breaks = QCheckBox("Afficher les ruptures de pente")
        self.breaks.setChecked(True)
        self.breaks.toggled.connect(self.redraw)
        left.addWidget(self.breaks)
        for text, fmt in (("Exporter PNG", "png"), ("Exporter SVG", "svg"), ("Exporter PDF", "pdf")):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, f=fmt: self.export(f))
            left.addWidget(b)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        if HAS_QT_MPL:
            self.fig = Figure(figsize=(8, 5), dpi=100)
            self.canvas = FigureCanvasQTAgg(self.fig)
            right.addWidget(NavigationToolbar2QT(self.canvas, self))
            right.addWidget(self.canvas, 1)
        else:
            self.image = QLabel("Matplotlib (Qt) indisponible : aperçu PNG.")
            self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            right.addWidget(self.image, 1)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        right.addWidget(self.stats)
        lay.addLayout(right, 3)
        self.profiles = []

    def load(self, registry):
        self.list.blockSignals(True)
        self.list.clear()
        self.profiles = []
        results = registry.by_module("profils")
        for r in results:
            for p in r.extra.get("profiles", []):
                self.profiles.append(p)
                it = QListWidgetItem("{} ({})".format(p["name"], r.created.strftime("%H:%M:%S")))
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked)
                self.list.addItem(it)
        # cocher les profils du dernier calcul
        last = len(results[-1].extra.get("profiles", [])) if results else 0
        for i in range(self.list.count() - last, self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked)
        self.list.blockSignals(False)
        self.redraw()

    def selected(self):
        return [self.profiles[i] for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def _plot(self, fig, sel):
        fig.clear()
        single = len(sel) == 1 and self.forms.isChecked()
        if single:
            ax = fig.add_axes([0.08, 0.32, 0.9, 0.6])
            ax2 = fig.add_axes([0.08, 0.1, 0.9, 0.14], sharex=ax)
        else:
            ax, ax2 = fig.add_subplot(111), None
        ax.grid(True, color="#dddddd", linewidth=0.6)
        pal = ["#08519c", "#d94801", "#238b45", "#6a51a3", "#cb181d", "#525252"]
        for i, p in enumerate(sel):
            ax.plot(p["distance"], p["z"], color=pal[i % len(pal)], linewidth=1.5, label=p["name"])
            if self.breaks.isChecked() and len(p["breaks"]):
                ax.plot(p["distance"][p["breaks"]], p["z"][p["breaks"]], "v", color="#cb181d", markersize=5,
                        label="Ruptures de pente" if i == 0 else None)
        ax.set_ylabel("Altitude (m)")
        ax.set_title("Profil topographique" if len(sel) == 1 else "Comparaison des profils")
        if sel:
            ax.legend(fontsize=8)
        if ax2 is not None:
            p = sel[0]
            f, d = p["form"], p["distance"]
            ax2.fill_between(d, 0, 1, where=f == 1, color="#b2182b", alpha=0.7, step="mid", label="Convexe")
            ax2.fill_between(d, 0, 1, where=f == -1, color="#2166ac", alpha=0.7, step="mid", label="Concave")
            ax2.fill_between(d, 0, 1, where=f == 0, color="#bbbbbb", alpha=0.7, step="mid", label="Rectiligne")
            ax2.set_yticks([])
            ax2.legend(fontsize=7, ncol=3, loc="upper right")
            ax2.set_xlabel("Distance cumulée (m)")
        else:
            ax.set_xlabel("Distance cumulée (m)")

    def redraw(self, *a):
        sel = self.selected()
        if HAS_QT_MPL:
            self._plot(self.fig, sel)
            self.canvas.draw_idle()
        txt = []
        for p in sel:
            s = p["stats"]
            txt.append("<b>{}</b> : longueur {:.0f} m, z {:.1f}–{:.1f} m, pente moyenne {:.2f} %, convexe {:.0f} %, "
                       "concave {:.0f} %, {} rupture(s)".format(p["name"], s["longueur_m"], s["z_min"], s["z_max"],
                                                                s["pente_moy_pct"], s["part_convexe_pct"],
                                                                s["part_concave_pct"], s["nb_ruptures"]).replace(".", ","))
        self.stats.setText("<br/>".join(txt))

    def export(self, fmt):
        sel = self.selected()
        if not sel:
            return
        start = os.path.join(self.dock.ctx.workspace, "07_Profils", "profils.{}".format(fmt))
        os.makedirs(os.path.dirname(start), exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le graphique", start, "*.{}".format(fmt))
        if not path:
            return
        if HAS_QT_MPL:
            from matplotlib.figure import Figure as F
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            fig = F(figsize=(10, 6), dpi=200)
            FigureCanvasAgg(fig)
            self._plot(fig, sel)
            fig.savefig(path, format=fmt)
        else:
            charts.profiles(sel, os.path.splitext(path)[0], formats=(fmt,))
        self.dock.done_files([path])
