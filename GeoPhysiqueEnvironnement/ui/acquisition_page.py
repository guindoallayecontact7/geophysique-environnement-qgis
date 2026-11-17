# -*- coding: utf-8 -*-
"""Rubrique « Acquisition de données » : zone d'étude, recherche, choix et téléchargement des scènes."""
import os

from qgis.PyQt.QtCore import Qt, QDate, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDistanceArea, QgsFeature,
    QgsField, QgsFillSymbol, QgsGeometry, QgsProject, QgsRasterLayer, QgsRectangle, QgsVectorLayer,
)
from qgis.gui import QgsFileWidget, QgsMapLayerComboBox, QgsRubberBand

from ..acquisition import catalogs as C
from ..acquisition.jobs import job_download, job_search, utm_epsg
from ..acquisition.http import human_size
from .maptools import RectTool, _POLY
from .pages import Page, _filter
from .widgets import Form, check, combo, ispin, note

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
GROUP = "TGS - Acquisition"
CHECKED, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked


def _ftype(name):
    """Type de champ : QMetaType (QGIS ≥ 3.38, Qt6) ou QVariant (QGIS 3.34)."""
    try:
        from qgis.PyQt.QtCore import QMetaType
        t = getattr(QMetaType.Type, {"String": "QString"}.get(name, name))
        QgsField("x", t)
        return t
    except (ImportError, AttributeError, TypeError):
        return getattr(QVariant, name)


def _checkable(text, checked, data=None):
    it = QListWidgetItem(text)
    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    it.setCheckState(CHECKED if checked else UNCHECKED)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    return it


class AcquisitionPage(Page):
    key, caption = "acquisition", "Acquisition de données"

    # ------------------------------------------------------------------ construction
    def build(self):
        self.aoi = None          # QgsGeometry en WGS 84
        self.band = None
        self.scenes = []
        self.footprints = None
        self.lay.addWidget(note(
            "Recherche et téléchargement de MNT et d'images (Landsat, Sentinel, ALOS PALSAR) sur la zone "
            "d'étude. Les sources COG ne lisent que la zone : un MNT de bassin versant prend quelques "
            "secondes. Les sources marquées « compte » demandent un compte gratuit (voir « Comptes »)."))
        self._build_aoi()
        self._build_sources()
        self.run_button("RECHERCHER LES SCÈNES DISPONIBLES", self.search)
        self._build_results()
        self._build_download()
        self.run_button("TÉLÉCHARGER LES SCÈNES COCHÉES", self.download)
        self._build_accounts()

    def _build_aoi(self):
        f = Form("1. Zone d'étude")
        self.aoi_info = QLabel("Aucune zone d'étude définie.")
        self.aoi_info.setWordWrap(True)
        self.aoi_info.setStyleSheet("color:#b35806;font-weight:bold;")
        f.full(self.aoi_info)
        row = QHBoxLayout()
        for text, slot, tip in (
                ("Dessiner un rectangle", self.draw_rect, "Appuyez, faites glisser puis relâchez sur la carte"),
                ("Emprise de la carte", self.from_canvas, "Partie de la carte actuellement visible"),
                ("Emprise du MNT actif", self.from_dem, "Rectangle englobant le MNT choisi en haut du panneau")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
        f.lay.addRow(row)
        self.vfile = QgsFileWidget()
        self.vfile.setFilter("Vecteurs (*.shp *.gpkg *.geojson *.json *.kml *.kmz *.gml *.sqlite *.tab)")
        h = QHBoxLayout()
        h.addWidget(self.vfile, 1)
        b = QPushButton("Importer")
        b.clicked.connect(self.from_file)
        h.addWidget(b)
        f.lay.addRow(QLabel("Fichier de limite"), h)
        self.vlayer = QgsMapLayerComboBox()
        self.vlayer.setFilters(_filter("VectorLayer"))
        h = QHBoxLayout()
        h.addWidget(self.vlayer, 1)
        self.only_sel = check("Sélection seule", False, "N'utiliser que les entités sélectionnées de la couche")
        h.addWidget(self.only_sel)
        b = QPushButton("Utiliser")
        b.clicked.connect(self.from_layer)
        h.addWidget(b)
        f.lay.addRow(QLabel("Couche du projet"), h)
        grid = QGridLayout()
        self.coord = {}
        for i, (k, lab, lo, hi, v) in enumerate((("n", "Nord", -90, 90, 13.6), ("s", "Sud", -90, 90, 13.0),
                                                  ("o", "Ouest", -180, 180, -8.6), ("e", "Est", -180, 180, -7.9))):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(5)
            sp.setSingleStep(0.01)
            sp.setValue(v)
            sp.setSuffix(" °")
            self.coord[k] = sp
            grid.addWidget(QLabel(lab), i // 2, 2 * (i % 2))
            grid.addWidget(sp, i // 2, 2 * (i % 2) + 1)
        b = QPushButton("Appliquer les coordonnées")
        b.setToolTip("Latitudes et longitudes en degrés décimaux (WGS 84) ; ouest et sud négatifs")
        b.clicked.connect(self.from_coords)
        grid.addWidget(b, 2, 0, 1, 4)
        f.lay.addRow(QLabel("Coordonnées GPS"), grid)
        self.lay.addWidget(f)

    def _build_sources(self):
        f = Form("2. Données recherchées")
        h = QHBoxLayout()
        self.kind = combo([("Toutes", ""), ("MNT", "MNT"), ("Optique", "Optique"), ("Radar", "Radar")])
        self.res = combo([("Toutes résolutions", 1e9), ("≤ 10 m", 10), ("≤ 30 m", 30), ("≤ 100 m", 100),
                          ("≤ 1 000 m", 1000)])
        h.addWidget(self.kind)
        h.addWidget(self.res)
        f.lay.addRow(QLabel("Type, résolution"), h)
        self.src_list = QListWidget()
        self.src_list.setMinimumHeight(150)
        f.full(self.src_list)
        self.kind.currentIndexChanged.connect(self._fill_sources)
        self.res.currentIndexChanged.connect(self._fill_sources)
        self._fill_sources()
        h = QHBoxLayout()
        today = QDate.currentDate()
        self.d0 = QDateEdit(today.addMonths(-3))
        self.d1 = QDateEdit(today)
        for d in (self.d0, self.d1):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        h.addWidget(QLabel("du"))
        h.addWidget(self.d0)
        h.addWidget(QLabel("au"))
        h.addWidget(self.d1)
        h.addStretch(1)
        f.lay.addRow(QLabel("Période d'acquisition"), h)
        self.cloud = ispin(30, 0, 100, " %", "Couverture nuageuse maximale (images optiques)")
        f.row("Nuages au plus", self.cloud)
        self.cover = ispin(0, 0, 100, " %", "Part minimale de la zone d'étude couverte par la scène "
                                           "(100 % = couverture intégrale)")
        f.row("Couverture de la zone au moins", self.cover)
        self.limit = ispin(30, 1, 500, "", "Nombre maximal de scènes par source")
        f.row("Scènes par source au plus", self.limit)
        self.lay.addWidget(f)

    def _fill_sources(self):
        kept = {self.src_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.src_list.count()) if self.src_list.item(i).checkState() == CHECKED}
        if not kept and self.src_list.count() == 0:
            kept = {"cop30"}
        self.src_list.clear()
        kind, res = self.kind.currentData(), self.res.currentData()
        for s in C.SOURCES:
            if (kind and s["kind"] != kind) or s["res"] > res:
                continue
            self.src_list.addItem(_checkable("[{}] {}".format(s["kind"], C.source_line(s)), s["id"] in kept, s["id"]))

    def _build_results(self):
        box = QGroupBox("3. Scènes trouvées")
        v = QVBoxLayout(box)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "Date", "Source", "Scène", "Nuages %", "Couverture %",
                                              "Taille"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(220)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.itemChanged.connect(self._on_check)
        self.table.cellDoubleClicked.connect(lambda r, c: self.show_metadata())
        v.addWidget(self.table)
        v.addWidget(note("Triées par date (cliquez un en-tête pour changer le tri). Double-clic : métadonnées."))
        h = QHBoxLayout()
        for text, slot in (("Tout cocher", lambda: self._check_all(True)),
                           ("Tout décocher", lambda: self._check_all(False)),
                           ("Métadonnées", self.show_metadata), ("Zoomer sur la scène", self.zoom_scene)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        self.found = QLabel("")
        v.addWidget(self.found)
        self.lay.addWidget(box)

    def _build_download(self):
        f = Form("4. Téléchargement")
        self.assets = QListWidget()
        self.assets.setMinimumHeight(110)
        self.assets.setToolTip("Bandes ou fichiers à télécharger pour chaque source des scènes cochées")
        f.row("Bandes et fichiers", self.assets)
        self.mode = combo([("Zone d'étude seulement (COG)", "zone"),
                           ("Fichiers complets", "complet")],
                          "Zone d'étude seulement : seule la zone est lue à distance (sources COG). Les autres sources "
                          "sont toujours téléchargées en entier.")
        f.row("Étendue", self.mode)
        self.clip_after = check("Découper aussi les fichiers complets", True,
                                "Après téléchargement complet, crée une copie découpée à la zone (*_zone.tif)")
        f.full(self.clip_after)
        self.cut_shape = check("Découper selon la forme exacte de la zone", False,
                               "Sinon, découpe selon le rectangle englobant la zone d'étude")
        f.full(self.cut_shape)
        self.srs = combo([("SCR du projet", "project"), ("UTM automatique", "utm"), ("SCR d'origine", "native")],
                         "UTM automatique : zone UTM du centre de la zone d'étude. Les analyses de TGS "
                         "demandent un SCR projeté en mètres.")
        f.row("Reprojection", self.srs)
        self.mosaic = check("MNT : assembler les dalles", True, "Mosaïque des dalles du MNT en un seul fichier découpé")
        f.full(self.mosaic)
        self.use_dem = check("Utiliser comme MNT actif", True, "Le MNT obtenu devient le MNT de toutes les rubriques")
        f.full(self.use_dem)
        self.add_layers = check("Ajouter au projet", True, "Rasters ajoutés au groupe « TGS - Acquisition »")
        f.full(self.add_layers)
        self.folder = QgsFileWidget()
        self.folder.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.folder.lineEdit().setPlaceholderText("Vide = espace de travail / Acquisition")
        f.row("Dossier", self.folder, "Un sous-dossier par source puis par scène ; un journal par téléchargement")
        self.lay.addWidget(f)

    def _build_accounts(self):
        from qgis.gui import QgsAuthConfigSelect
        f = Form("Comptes (sources marquées « compte »)")
        f.full(note("Les identifiants sont gardés chiffrés par le gestionnaire d'authentification de QGIS. "
                    "Créez une configuration « Basic » (identifiant, mot de passe) pour chaque compte."))
        self.auth = {}
        for key, (label, tip) in C.ACCOUNTS.items():
            w = QgsAuthConfigSelect()
            w.setToolTip(tip)
            cid = self.dock.settings.get("auth_" + key) or ""
            if cid:
                w.setConfigId(cid)
            w.selectedConfigIdChanged.connect(lambda cid, k=key: self._save_auth(k, cid))
            self.auth[key] = w
            f.row(label, w, tip)
        self.lay.addWidget(f)

    def _save_auth(self, key, cid):
        self.dock.settings["auth_" + key] = cid or ""
        self.dock.apply_settings()

    # ------------------------------------------------------------------ zone d'étude
    def _canvas(self):
        return self.dock.iface.mapCanvas()

    def _project_crs(self):
        return QgsProject.instance().crs()

    def set_aoi(self, geom, crs):
        if geom is None or geom.isEmpty():
            self.dock.warn("Zone d'étude vide.")
            return
        g = QgsGeometry(geom)
        if crs.isValid() and crs != WGS84:
            g.transform(QgsCoordinateTransform(crs, WGS84, QgsProject.instance()))
        if not g.isGeosValid():
            g = g.makeValid()
        self.aoi = g
        bb = g.boundingBox()
        da = QgsDistanceArea()
        da.setSourceCrs(WGS84, QgsProject.instance().transformContext())
        da.setEllipsoid("WGS84")
        km2 = da.measureArea(g) / 1e6
        self.aoi_info.setText("Zone d'étude : O {:.4f}°, S {:.4f}°, E {:.4f}°, N {:.4f}° - {:,.1f} km² - UTM {}".format(
            bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum(), km2,
            utm_epsg(bb.center().x(), bb.center().y()) % 100).replace(",", " "))
        for k, v in (("n", bb.yMaximum()), ("s", bb.yMinimum()), ("o", bb.xMinimum()), ("e", bb.xMaximum())):
            self.coord[k].setValue(v)
        self._show_aoi()
        if km2 > 50000:
            self.dock.log("⚠ Zone très étendue ({:,.0f} km²) : téléchargements longs.".format(km2).replace(",", " "))
        self.dock.log("Zone d'étude définie ({:.1f} km²).".format(km2))

    def _show_aoi(self):
        canvas = self._canvas()
        if self.band is None:
            self.band = QgsRubberBand(canvas, _POLY)
            self.band.setColor(QColor(227, 26, 28, 30))
            self.band.setStrokeColor(QColor(227, 26, 28))
            self.band.setWidth(2)
        g = QgsGeometry(self.aoi)
        dst = canvas.mapSettings().destinationCrs()
        if dst.isValid() and dst != WGS84:
            g.transform(QgsCoordinateTransform(WGS84, dst, QgsProject.instance()))
        self.band.setToGeometry(g, None)

    def draw_rect(self):
        tool = RectTool(self._canvas())

        def got(rect):
            self.set_aoi(QgsGeometry.fromRect(rect), self._canvas().mapSettings().destinationCrs())
            if self.dock._prev_tool is not None:
                self._canvas().setMapTool(self.dock._prev_tool)
        tool.finished.connect(got)
        self.dock._set_tool(tool)
        self.dock.log("Tracez le rectangle de la zone d'étude sur la carte (appuyer, glisser, relâcher).")

    def from_canvas(self):
        c = self._canvas()
        self.set_aoi(QgsGeometry.fromRect(c.extent()), c.mapSettings().destinationCrs())

    def from_dem(self):
        lyr = self.dock.dem_layer()
        if lyr is None:
            self.dock.warn("Aucun MNT actif.")
            return
        self.set_aoi(QgsGeometry.fromRect(lyr.extent()), lyr.crs())

    def _layer_geom(self, lyr, selected_only):
        feats = lyr.selectedFeatures() if selected_only else list(lyr.getFeatures())
        geoms = [f.geometry() for f in feats if f.hasGeometry()]
        if not geoms:
            return None
        if lyr.geometryType() != _POLY:
            return QgsGeometry.fromRect(QgsGeometry.unaryUnion(geoms).boundingBox())
        return QgsGeometry.unaryUnion(geoms)

    def from_file(self):
        path = self.vfile.filePath()
        if not path or not os.path.exists(path):
            self.dock.warn("Choisissez un fichier vectoriel de limite.")
            return
        lyr = QgsVectorLayer(path, "zone", "ogr")
        if not lyr.isValid():
            self.dock.warn("Fichier vectoriel illisible : {}".format(path))
            return
        self.set_aoi(self._layer_geom(lyr, False), lyr.crs())

    def from_layer(self):
        lyr = self.vlayer.currentLayer()
        if lyr is None:
            self.dock.warn("Choisissez une couche vectorielle.")
            return
        sel = self.only_sel.isChecked()
        if sel and lyr.selectedFeatureCount() == 0:
            self.dock.warn("Aucune entité sélectionnée dans « {} ».".format(lyr.name()))
            return
        self.set_aoi(self._layer_geom(lyr, sel), lyr.crs())

    def from_coords(self):
        n, s = self.coord["n"].value(), self.coord["s"].value()
        o, e = self.coord["o"].value(), self.coord["e"].value()
        if n <= s or e <= o:
            self.dock.warn("Coordonnées incohérentes : il faut Nord > Sud et Est > Ouest.")
            return
        self.set_aoi(QgsGeometry.fromRect(QgsRectangle(o, s, e, n)), WGS84)

    def _aoi_dict(self):
        bb = self.aoi.boundingBox()
        return {"bbox": [bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()], "wkt": self.aoi.asWkt(8)}

    # ------------------------------------------------------------------ comptes
    def _creds(self, keys):
        out = {}
        mgr = QgsApplication.authManager()
        from qgis.core import QgsAuthMethodConfig
        for k in keys:
            if not k or k not in self.auth:
                continue
            cid = self.auth[k].configId()
            if not cid:
                continue
            cfg = QgsAuthMethodConfig()
            res = mgr.loadAuthenticationConfig(cid, cfg, True)
            if isinstance(res, tuple):
                ok, cfg = res[0], res[1]
            else:
                ok = res
            if ok:
                out[k] = {"username": cfg.config("username", ""), "password": cfg.config("password", "")}
        return out

    # ------------------------------------------------------------------ recherche
    def _chosen_sources(self):
        return [self.src_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.src_list.count())
                if self.src_list.item(i).checkState() == CHECKED]

    def search(self):
        if self.aoi is None:
            self.dock.warn("Définissez d'abord la zone d'étude (étape 1).")
            return
        ids = self._chosen_sources()
        if not ids:
            self.dock.warn("Cochez au moins une source de données.")
            return
        if self.d0.date() > self.d1.date():
            self.dock.warn("La date de début est après la date de fin.")
            return
        need = {C.SOURCE_BY_ID[i].get("auth") for i in ids if C.SOURCE_BY_ID[i]["catalog"] == "usgs"}
        params = {"aoi": self._aoi_dict(), "sources": ids, "start": self.d0.date().toString("yyyy-MM-dd"),
                  "end": self.d1.date().toString("yyyy-MM-dd"), "cloud_max": self.cloud.value(),
                  "limit": self.limit.value(), "min_cover": self.cover.value(), "creds": self._creds(need)}
        self.dock.run_raw("Recherche de scènes", job_search, params, self._show_results)

    def _show_results(self, res):
        self.scenes = res["scenes"]
        for e in res["errors"]:
            self.dock.log("⚠ " + e)
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.scenes))
        for r, s in enumerate(self.scenes):
            src = C.SOURCE_BY_ID[s["source"]]
            size = sum((a.get("size") or 0) for k, a in s["assets"].items() if k in src["assets"])
            first = QTableWidgetItem("")
            first.setFlags(first.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            first.setCheckState(UNCHECKED)
            first.setData(Qt.ItemDataRole.UserRole, r)
            self.table.setItem(r, 0, first)
            vals = [s["date"] or "-", src["label"], s["title"],
                    "" if s["cloud"] is None else "{:.1f}".format(s["cloud"]),
                    "" if s.get("coverage") is None else "{:.0f}".format(s["coverage"]), human_size(size)]
            for c, v in enumerate(vals, start=1):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        n_src = len({s["source"] for s in self.scenes})
        self.found.setText("{} scène(s) trouvée(s) dans {} source(s). Cochez les scènes à télécharger.".format(
            len(self.scenes), n_src))
        self.dock.log("✔ Recherche terminée : {} scène(s).".format(len(self.scenes)))
        self._draw_footprints()
        self._fill_assets()

    def _scene_of_row(self, row):
        it = self.table.item(row, 0)
        return None if it is None else self.scenes[it.data(Qt.ItemDataRole.UserRole)]

    def _checked_scenes(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None and it.checkState() == CHECKED:
                out.append(self.scenes[it.data(Qt.ItemDataRole.UserRole)])
        return out

    def _check_all(self, on):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(CHECKED if on else UNCHECKED)
        self.table.blockSignals(False)
        self._fill_assets()

    def _on_check(self, item):
        if item.column() == 0:
            self._fill_assets()

    def _fill_assets(self):
        prev = {self.assets.item(i).data(Qt.ItemDataRole.UserRole): self.assets.item(i).checkState() == CHECKED
                for i in range(self.assets.count())}
        self.assets.clear()
        seen, s_types = {}, {}
        for s in self._checked_scenes():
            for k, a in s["assets"].items():
                seen.setdefault((s["source"], k), a.get("title") or k)
                s_types.setdefault((s["source"], k), a.get("type", ""))
        for (sid, k), title in sorted(seen.items()):
            src = C.SOURCE_BY_ID[sid]
            if k in ("tilejson", "rendered_preview", "thumbnail", "preview") or k.startswith("schema-"):
                continue
            typ = (s_types.get((sid, k)) or "").lower()
            if any(t in typ for t in ("xml", "json", "png", "jpeg", "html", "text")):
                continue
            default = prev.get((sid, k), k in src["assets"])
            text = "{} : {}{}".format(src["label"], k, "" if title == k else " ({})".format(title))
            self.assets.addItem(_checkable(text, default, (sid, k)))

    # ------------------------------------------------------------------ carte et métadonnées
    def _draw_footprints(self):
        prj = QgsProject.instance()
        if self.footprints is not None and prj.mapLayer(self.footprints) is not None:
            prj.removeMapLayer(self.footprints)
        self.footprints = None
        if not self.scenes:
            return
        lyr = QgsVectorLayer("Polygon?crs=EPSG:4326", "Emprises des scènes trouvées", "memory")
        pr = lyr.dataProvider()
        fields = [QgsField("n", _ftype("Int")), QgsField("date", _ftype("String")), QgsField("source", _ftype("String")),
                  QgsField("scene", _ftype("String")), QgsField("nuages", _ftype("Double")),
                  QgsField("couverture", _ftype("Double"))]
        pr.addAttributes(fields)
        lyr.updateFields()
        feats = []
        import json
        for i, s in enumerate(self.scenes):
            if not s.get("geometry"):
                continue
            from osgeo import ogr
            og = ogr.CreateGeometryFromJson(json.dumps(s["geometry"]))
            if og is None:
                continue
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry.fromWkt(og.ExportToWkt()))
            f.setAttributes([i, s["date"], C.SOURCE_BY_ID[s["source"]]["label"], s["title"],
                             s["cloud"], s.get("coverage")])
            feats.append(f)
        pr.addFeatures(feats)
        lyr.updateExtents()
        lyr.setRenderer(lyr.renderer().clone())
        sym = QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "31,59,87,200",
                                          "outline_width": "0.4"})
        lyr.renderer().setSymbol(sym)
        prj.addMapLayer(lyr, False)
        root = prj.layerTreeRoot()
        g = root.findGroup(GROUP) or root.insertGroup(0, GROUP)
        g.insertLayer(0, lyr)
        self.footprints = lyr.id()

    def _on_select(self):
        rows = {i.row() for i in self.table.selectedItems()}
        lyr = QgsProject.instance().mapLayer(self.footprints) if self.footprints else None
        if lyr is None:
            return
        idx = [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows if self.table.item(r, 0)]
        ids = [f.id() for f in lyr.getFeatures() if f["n"] in idx]
        lyr.selectByIds(ids)

    def zoom_scene(self):
        r = self.table.currentRow()
        s = self._scene_of_row(r) if r >= 0 else None
        lyr = QgsProject.instance().mapLayer(self.footprints) if self.footprints else None
        if s is None or lyr is None:
            return
        n = self.scenes.index(s)
        for f in lyr.getFeatures():
            if f["n"] == n:
                g = f.geometry()
                c = self._canvas()
                g.transform(QgsCoordinateTransform(WGS84, c.mapSettings().destinationCrs(), QgsProject.instance()))
                c.setExtent(g.boundingBox().buffered(g.boundingBox().width() * 0.05))
                c.refresh()
                break

    def show_metadata(self):
        r = self.table.currentRow()
        s = self._scene_of_row(r) if r >= 0 else None
        if s is None:
            self.dock.warn("Sélectionnez une scène dans le tableau.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Métadonnées - " + s["title"])
        dlg.resize(720, 560)
        v = QVBoxLayout(dlg)
        t = QPlainTextEdit(C.metadata_text(s))
        t.setReadOnly(True)
        v.addWidget(t)
        b = QPushButton("Fermer")
        b.clicked.connect(dlg.close)
        v.addWidget(b)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.open()

    # ------------------------------------------------------------------ téléchargement
    def download(self):
        scenes = self._checked_scenes()
        if not scenes:
            self.dock.warn("Cochez au moins une scène dans le tableau (étape 3).")
            return
        assets = {}
        for i in range(self.assets.count()):
            it = self.assets.item(i)
            if it.checkState() == CHECKED:
                sid, k = it.data(Qt.ItemDataRole.UserRole)
                assets.setdefault(sid, []).append(k)
        for s in scenes:
            if s["source"] not in assets:
                self.dock.warn("Aucune bande cochée pour {}.".format(C.SOURCE_BY_ID[s["source"]]["label"]))
                return
        folder = self.folder.filePath() or os.path.join(self.dock.settings.get("workspace", ""), "Acquisition")
        srs_mode = self.srs.currentData()
        project_wkt = None
        if srs_mode == "project":
            crs = self._project_crs()
            if not crs.isValid():
                srs_mode = "utm"
            else:
                project_wkt = crs.toWkt()
                if crs.isGeographic():
                    self.dock.log("⚠ Le SCR du projet est géographique : les analyses de TGS demandent un SCR "
                                  "projeté (choisissez « UTM automatique »).")
        auth_needed = {C.SOURCE_BY_ID[s["source"]].get("auth") for s in scenes}
        creds = self._creds(auth_needed)
        missing = [C.ACCOUNTS[a][0] for a in auth_needed if a and a not in creds]
        if missing:
            self.dock.warn("Compte à configurer dans « Comptes » : {}.".format(", ".join(missing)))
            return
        mode = self.mode.currentData()
        big = sum((a.get("size") or 0) for s in scenes for k, a in s["assets"].items()
                  if k in assets.get(s["source"], []) and (mode == "complet" or
                                                           not C.SOURCE_BY_ID[s["source"]].get("cog")))
        if big > 2 * 1024 ** 3:
            ans = QMessageBox.question(self, "Téléchargement volumineux",
                                       "Environ {} à télécharger. Continuer ?".format(human_size(big)))
            if ans != QMessageBox.StandardButton.Yes:
                return
        params = {"aoi": self._aoi_dict(), "scenes": scenes, "assets": assets, "mode": mode,
                  "clip_after": self.clip_after.isChecked(), "srs_mode": srs_mode, "project_wkt": project_wkt,
                  "cut_shape": self.cut_shape.isChecked(), "mosaic_dem": self.mosaic.isChecked(),
                  "folder": folder, "creds": creds}
        self.dock.run_raw("Téléchargement de {} scène(s)".format(len(scenes)), job_download, params,
                          self._downloaded)

    def _downloaded(self, res):
        for e in res["errors"]:
            self.dock.log("✘ " + e)
        added_dem = False
        if self.add_layers.isChecked():
            prj = QgsProject.instance()
            root = prj.layerTreeRoot()
            g = root.findGroup(GROUP) or root.insertGroup(0, GROUP)
            for path, name, kind in res["rasters"]:
                if kind == "MNT" and self.use_dem.isChecked() and not added_dem:
                    lyr = QgsRasterLayer(path, name, "gdal")
                    if lyr.isValid():
                        prj.addMapLayer(lyr, False)
                        g.insertLayer(0, lyr)
                        self.dock.dem.setLayer(lyr)
                        added_dem = True
                        self.dock.log("MNT actif : {}".format(path))
                    continue
                lyr = QgsRasterLayer(path, name, "gdal")
                if lyr.isValid():
                    prj.addMapLayer(lyr, False)
                    g.addLayer(lyr)
        n = len(res["outputs"])
        self.dock.log("✔ Téléchargement terminé : {} fichier(s) dans {}{}".format(
            n, res["folder"], " ; {} erreur(s)".format(len(res["errors"])) if res["errors"] else ""))
        if res["errors"]:
            self.dock.iface.messageBar().pushWarning("TGS", "{} fichier(s) obtenu(s), {} erreur(s) : voir le "
                                                            "journal.".format(n, len(res["errors"])))
        else:
            self.dock.iface.messageBar().pushSuccess("TGS", "{} fichier(s) téléchargé(s).".format(n))

    def cleanup(self):
        if self.band is not None:
            self._canvas().scene().removeItem(self.band)
            self.band = None
