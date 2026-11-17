# -*- coding: utf-8 -*-
"""Composants d'interface réutilisables (formulaires, résultats, tableaux)."""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QSizePolicy,
)

from ..engines.statistics import fmt


def spin(value, lo, hi, step=1.0, decimals=2, suffix="", tip=""):
    w = QDoubleSpinBox()
    w.setDecimals(decimals)
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setValue(value)
    if suffix:
        w.setSuffix(" " + suffix)
    if tip:
        w.setToolTip(tip)
    return w


def ispin(value, lo, hi, suffix="", tip=""):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(value)
    if suffix:
        w.setSuffix(" " + suffix)
    if tip:
        w.setToolTip(tip)
    return w


def combo(items, tip=""):
    """items : liste de (libellé, donnée)."""
    w = QComboBox()
    for lab, data in items:
        w.addItem(lab, data)
    if tip:
        w.setToolTip(tip)
    return w


def check(text, checked=True, tip=""):
    w = QCheckBox(text)
    w.setChecked(checked)
    if tip:
        w.setToolTip(tip)
    return w


def note(text, color="#555555"):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: {}; font-size: 8.5pt;".format(color))
    return lab


def title(text):
    lab = QLabel(text)
    lab.setStyleSheet("font-size: 12pt; font-weight: bold; color: #1f3b57; padding: 2px 0 4px 0;")
    lab.setWordWrap(True)
    return lab


class Form(QGroupBox):
    """Groupe de paramètres : libellé, champ, info-bulle descriptive."""

    def __init__(self, caption):
        super().__init__(caption)
        self.lay = QFormLayout(self)
        self.lay.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.lay.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

    def row(self, label, widget, tip=""):
        lab = QLabel(label)
        if tip:
            lab.setToolTip(tip)
            if not widget.toolTip():
                widget.setToolTip(tip)
        self.lay.addRow(lab, widget)
        return widget

    def full(self, widget):
        self.lay.addRow(widget)
        return widget


class ChecksGroup(QGroupBox):
    """Liste de cases à cocher : produits à calculer."""

    def __init__(self, caption, items, columns=2):
        super().__init__(caption)
        grid = QGridLayout(self)
        self.boxes = {}
        for i, (key, text, on, tip) in enumerate(items):
            cb = check(text, on, tip)
            self.boxes[key] = cb
            grid.addWidget(cb, i // columns, i % columns)
        btns = QHBoxLayout()
        b1, b2 = QPushButton("Tout"), QPushButton("Aucun")
        for b in (b1, b2):
            b.setMaximumWidth(70)
            btns.addWidget(b)
        btns.addStretch(1)
        b1.clicked.connect(lambda: [c.setChecked(True) for c in self.boxes.values()])
        b2.clicked.connect(lambda: [c.setChecked(False) for c in self.boxes.values()])
        grid.addLayout(btns, (len(items) + columns - 1) // columns, 0, 1, columns)

    def selected(self):
        return [k for k, cb in self.boxes.items() if cb.isChecked()]


class ResultsBox(QGroupBox):
    """Rubrique « Résultats - Statistiques - Exportation » commune à tous les modules."""

    BUTTONS = [
        ("stats", "Afficher les statistiques"), ("txt", "Exporter les statistiques TXT"),
        ("csv", "Exporter en CSV"), ("xlsx", "Exporter en Excel"),
        ("map", "Générer la carte"), ("geotiff", "Exporter la carte en GeoTIFF"),
        ("gpkg", "Exporter en GeoPackage"), ("png", "Exporter en PNG"),
        ("pdf", "Générer une fiche PDF"), ("all", "Exporter tous les résultats"),
    ]

    def __init__(self, dock, modules):
        super().__init__("Résultats - Statistiques - Exportation")
        self.dock = dock
        self.modules = modules if isinstance(modules, (list, tuple)) else [modules]
        lay = QVBoxLayout(self)
        self.info = QLabel("Aucune analyse exécutée dans ce module.")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#555;")
        lay.addWidget(self.info)
        self.map_combo = QComboBox()
        self.map_combo.setToolTip("Couche à mettre en carte ou à exporter")
        lay.addWidget(self.map_combo)
        grid = QGridLayout()
        self.btn = {}
        for i, (key, text) in enumerate(self.BUTTONS):
            b = QPushButton(text)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda checked=False, k=key: self.dock.results_action(self, k))
            self.btn[key] = b
            grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(grid)
        self.refresh()

    def result(self):
        items = [r for m in self.modules for r in self.dock.registry.by_module(m)]
        if not items:
            return None
        return max(items, key=lambda r: r.created)

    def refresh(self):
        r = self.result()
        enabled = r is not None
        for b in self.btn.values():
            b.setEnabled(enabled)
        self.map_combo.clear()
        if not enabled:
            self.info.setText("Aucune analyse exécutée dans ce module.")
            return
        self.info.setText("Dernière analyse : <b>{}</b> ({}) - {} couche(s), {} tableau(x)".format(
            r.title, r.created.strftime("%d/%m/%Y %H:%M"), len(r.layers), len(r.tables)))
        for spec in r.layers:
            self.map_combo.addItem(spec.name, spec)
        has_raster = any(s.kind == "raster" for s in r.layers)
        has_vector = any(s.kind == "vector" for s in r.layers)
        self.btn["geotiff"].setEnabled(has_raster)
        self.btn["gpkg"].setEnabled(has_vector)
        self.btn["map"].setEnabled(bool(r.layers))
        self.btn["png"].setEnabled(bool(r.layers))

    def selected_spec(self):
        return self.map_combo.currentData()


class TableDialog(QDialog):
    """Affichage des tableaux statistiques d'une analyse."""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Statistiques - {}".format(result.title))
        self.resize(900, 560)
        lay = QVBoxLayout(self)
        head = QLabel("<b>{}</b><br/>{} · {}".format(result.title, result.module_title,
                                                     result.created.strftime("%d/%m/%Y %H:%M")))
        lay.addWidget(head)
        self.combo = QComboBox()
        self.tables = []
        if result.summary:
            from ..engines.results import Table
            self.tables.append(Table("Résumé des résultats", ["Indicateur", "Valeur", "Unité"],
                                     [list(s) for s in result.summary]))
        if result.params:
            from ..engines.results import Table
            self.tables.append(Table("Paramètres utilisés", ["Paramètre", "Valeur", "Unité"],
                                     [list(s) for s in result.params]))
        self.tables += list(result.tables)
        for t in self.tables:
            self.combo.addItem(t.title)
        lay.addWidget(self.combo)
        self.view = TableView()
        lay.addWidget(self.view, 1)
        self.note = note("")
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.combo.currentIndexChanged.connect(self.show_table)
        self.show_table(0)

    def show_table(self, i):
        if 0 <= i < len(self.tables):
            t = self.tables[i]
            self.view.set_table(t)
            self.note.setText(t.note or "")


class TableView(QTableWidget):
    def __init__(self):
        super().__init__()
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)

    def set_table(self, t):
        self.clear()
        self.setColumnCount(len(t.headers))
        self.setRowCount(len(t.rows))
        self.setHorizontalHeaderLabels([h + ("\n(" + u + ")" if u else "") for h, u in zip(t.headers, t.units)])
        for r, row in enumerate(t.rows):
            for c, v in enumerate(row):
                it = QTableWidgetItem(v if isinstance(v, str) else fmt(v))
                if not isinstance(v, str):
                    it.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                self.setItem(r, c, it)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
