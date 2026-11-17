# -*- coding: utf-8 -*-
"""Construction des cartes thématiques et exportation globale."""
import datetime
import os
import shutil

import numpy as np
from qgis.core import (QgsProject, QgsRectangle, QgsVectorLayer, QgsGraduatedSymbolRenderer, QgsRendererRange,
                       QgsSymbol)

from ..engines import cartography as C
from ..engines import report as R
from ..engines import statistics as ST
from ..engines.results import MODULE_DIRS, slugify, Table
from ..engines.styles import apply_style, palette_colors, _qcolor
from .layers import project_layer, make_layer

# carte du catalogue → clés de couches qui peuvent la produire (par ordre de préférence)
SOURCES = {
    "hypsometrie": ["hypsometrie_bassin", "hypsometrie"],
    "pentes": ["pentes_bassin", "pentes"],
    "expositions": ["expositions"],
    "ombrage": ["ombrage", "ombrage_multi"],
    "reseau": ["reseau", "strahler"],
    "directions": ["directions"],
    "accumulation": ["accumulation"],
    "sous_bassins": ["sous_bassins"],
    "strahler": ["strahler", "reseau"],
    "shreve": ["shreve"],
    "courbes": ["courbes"],
    "courbures": ["courbures", "courbure_profil", "courbure_plan"],
    "formes": ["formes", "formes_versants"],
    "twi": ["twi"],
    "spi": ["spi"],
    "concentration": ["concentration", "convergence"],
    "unites": ["unites", "unites_morpho"],
    "classes_pente": ["classes_pente_bassin", "classes_pente"],
    "relief": ["relief"], "tpi": ["tpi"], "tri": ["tri"], "vrm": ["vrm"], "ls": ["ls"],
    "convergence": ["convergence"], "bassin": ["bassin"], "exutoires": ["exutoires"],
    "cretes": ["cretes"], "courbure_profil": ["courbure_profil"], "courbure_plan": ["courbure_plan"],
}
SPECIAL = {"localisation", "parametres"}
BASIN_KEYS = {"bassin", "sous_bassins", "exutoires", "reseau", "hypsometrie_bassin", "pentes_bassin",
              "classes_pente_bassin", "cours_principal"}


class MapBuilder:
    def __init__(self, registry, settings):
        self.registry = registry
        self.settings = settings
        self._keep = []  # couches auxiliaires (contours de bassin, cartes de paramètres)

    # ------------------------------------------------------------------
    def produced(self):
        """map_key → (spec, result), en gardant la production la plus récente."""
        out = {}
        for r in self.registry.all():
            for s in r.layers:
                if s.map_key and project_layer(s) is not None:
                    out[s.map_key] = (s, r)
        return out

    def availability(self):
        prod = self.produced()
        rows = []
        for key, title in C.MAP_CATALOGUE:
            if key == "localisation":
                ok = "bassin" in prod and any(k in prod for k in ("hypsometrie", "ombrage"))
                hint = "délimiter un bassin et lancer l'analyse topographique"
            elif key == "parametres":
                ok = "sous_bassins" in prod or "bassin" in prod
                hint = "délimiter un bassin ou des sous-bassins"
            else:
                ok = any(k in prod for k in SOURCES.get(key, [key]))
                hint = "exécuter le module correspondant"
            rows.append((key, title, ok, hint))
        return rows

    def _first(self, keys):
        prod = self.produced()
        for k in keys:
            if k in prod:
                return prod[k]
        return None, None

    def _hillshade(self):
        s, _ = self._first(["ombrage", "ombrage_multi"])
        return project_layer(s) if s else None

    def _basin_outline(self):
        s, _ = self._first(["bassin"])
        if s is None:
            return None
        lyr = QgsVectorLayer(s.uri, "Limite du bassin versant", "ogr")
        if not lyr.isValid():
            return None
        apply_style(lyr, {"type": "outline", "color": "#000000", "width": 0.8})
        self._keep.append(lyr)
        return lyr

    def _basin_extent(self):
        s, _ = self._first(["bassin"])
        lyr = project_layer(s) if s else None
        return QgsRectangle(lyr.extent()) if lyr is not None else None

    def info(self, spec, result):
        src = self.settings.get("source") or "MNT : {}".format(os.path.basename(result.dem_source or ""))
        meth = (result.method or "").split("\n")[0]
        if len(meth) > 230:
            meth = meth[:227] + "…"
        return {"resolution": result.resolution, "unites": spec.units if spec else "", "methode": meth,
                "source": src, "date": result.created.strftime("%d/%m/%Y"),
                "auteur": self.settings.get("author") or None}

    # ------------------------------------------------------------------
    def spec_for_layer(self, spec, result, clip_to_basin=False):
        """Carte d'une couche quelconque d'un résultat."""
        main = project_layer(spec)
        if main is None:
            main = make_layer(spec)
            if main is None:
                return None
            self._keep.append(main)
        layers = [main]
        legend = [main]
        outline = None
        if spec.map_key not in BASIN_KEYS or spec.map_key in ("hypsometrie_bassin", "pentes_bassin", "classes_pente_bassin"):
            outline = self._basin_outline()
        if outline is not None and spec.map_key not in ("bassin", "sous_bassins"):
            layers.insert(0, outline)
            legend.append(outline)
        if spec.kind == "raster" and spec.map_key not in ("ombrage", "ombrage_multi"):
            hs = self._hillshade()
            if hs is not None:
                layers.append(hs)
        elif spec.kind == "vector":
            hs = self._hillshade()
            if hs is not None:
                layers.append(hs)
        extent = None
        if clip_to_basin or spec.map_key in BASIN_KEYS:
            extent = self._basin_extent()
        title = spec.map_title or spec.name
        return C.MapSpec(spec.map_key or slugify(spec.name), title, layers, legend, extent, self.info(spec, result),
                         subtitle=result.title)

    def spec_for_key(self, key, clip_to_basin=False, param_field=None):
        prod = self.produced()
        if key == "localisation":
            return self._localisation(prod)
        if key == "parametres":
            return self._parameters(prod, param_field or "kc_gravelius")
        for k in SOURCES.get(key, [key]):
            if k in prod:
                spec, res = prod[k]
                ms = self.spec_for_layer(spec, res, clip_to_basin)
                if ms is None:
                    return None
                ms.title = C.MAP_TITLES.get(key, ms.title)
                if key in ("reseau", "strahler", "shreve", "sous_bassins", "exutoires", "bassin"):
                    self._add_hydro_context(ms, prod, key)
                return ms
        return None

    def _add_hydro_context(self, ms, prod, key):
        extra = []
        if key in ("sous_bassins", "exutoires", "bassin"):
            s, _ = (prod.get("reseau") or (None, None))
            if s is not None and project_layer(s) is not None:
                extra.append(project_layer(s))
        if key == "exutoires":
            # tous les exutoires (initiaux et corrigés) du dernier résultat de bassin
            res = prod["exutoires"][1]
            for s in res.layers:
                if s.map_key == "exutoires" and project_layer(s) is not None and project_layer(s) not in ms.layers:
                    ms.layers.insert(0, project_layer(s))
                    ms.legend_layers.append(project_layer(s))
        if key == "bassin":
            s, _ = prod.get("cours_principal", (None, None))
            if s is not None and project_layer(s) is not None:
                extra.insert(0, project_layer(s))
        for lyr in extra:
            if lyr not in ms.layers:
                ms.layers.insert(0, lyr)
                ms.legend_layers.append(lyr)

    def _localisation(self, prod):
        basin_spec, res = prod.get("bassin", (None, None))
        if basin_spec is None:
            return None
        outline = QgsVectorLayer(basin_spec.uri, "Bassin versant", "ogr")
        apply_style(outline, {"type": "outline", "color": "#d7191c", "width": 1.2})
        self._keep.append(outline)
        layers, legend = [outline], [outline]
        s, _ = prod.get("strahler", prod.get("reseau", (None, None)))
        if s is not None and project_layer(s) is not None:
            layers.append(project_layer(s))
            legend.append(project_layer(s))
        hyp, _ = prod.get("hypsometrie", (None, None))
        if hyp is not None and project_layer(hyp) is not None:
            layers.append(project_layer(hyp))
            legend.append(project_layer(hyp))
            extent = QgsRectangle(project_layer(hyp).extent())
        else:
            extent = None
        hs = self._hillshade()
        if hs is not None:
            layers.append(hs)
            if extent is None:
                extent = QgsRectangle(hs.extent())
        return C.MapSpec("localisation", C.MAP_TITLES["localisation"], layers, legend, extent,
                         self.info(basin_spec, res), subtitle="Bassin dans l'emprise du MNT")

    def _parameters(self, prod, field):
        spec, res = prod.get("sous_bassins") or prod.get("bassin") or (None, None)
        if spec is None:
            return None
        lyr = QgsVectorLayer(spec.uri, "Paramètre : {}".format(field), "ogr")
        if not lyr.isValid() or lyr.fields().indexOf(field) < 0:
            return None
        vals = [f[field] for f in lyr.getFeatures()]
        vals = np.array([v for v in vals if v is not None], dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            return None
        n = min(5, max(1, np.unique(vals).size))
        brk = np.unique(np.quantile(vals, np.linspace(0, 1, n + 1)))
        if brk.size < 2:
            brk = np.array([vals.min() - 0.5, vals.max() + 0.5])
        cols = palette_colors(len(brk) - 1, "chaleur")
        ranges = []
        for i in range(len(brk) - 1):
            sym = QgsSymbol.defaultSymbol(lyr.geometryType())
            sym.setColor(_qcolor(cols[i]))
            ranges.append(QgsRendererRange(float(brk[i]), float(brk[i + 1]), sym,
                                           "{} - {}".format(ST.fmt(float(brk[i]), 3), ST.fmt(float(brk[i + 1]), 3))))
        lyr.setRenderer(QgsGraduatedSymbolRenderer(field, ranges))
        self._keep.append(lyr)
        from ..core.morphometry import FIELD_LABELS
        lab, unit, nature, formula = FIELD_LABELS.get(field, (field, "", "", ""))
        layers = [lyr]
        hs = self._hillshade()
        if hs is not None:
            layers.append(hs)
        info = self.info(spec, res)
        info["unites"] = unit
        info["methode"] = "{} : {}".format(lab, formula)
        return C.MapSpec("parametres", "{} - {}".format(C.MAP_TITLES["parametres"], lab), layers, [lyr],
                         QgsRectangle(lyr.extent()), info, subtitle=res.title)

    # ------------------------------------------------------------------
    def export(self, specs, folder, fmt="pdf", atlas=False, register=False, name=None, dpi=200):
        """Exporte une ou plusieurs cartes. Renvoie la liste des fichiers produits."""
        os.makedirs(folder, exist_ok=True)
        out = []
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if atlas and len(specs) > 1:
            layout = C.build_layout(specs, name or "Atlas TERRA-MORPHO {}".format(stamp))
            path = os.path.join(folder, "atlas_{}.pdf".format(stamp))
            C.export_layout(layout, path, "pdf", dpi)
            out.append(path)
            if register:
                C.register_layout(layout)
            return out
        for s in specs:
            layout = C.build_layout([s], "{} ({})".format(s.title, stamp))
            path = os.path.join(folder, "{}_{}.{}".format(slugify(s.key)[:40], stamp, fmt))
            C.export_layout(layout, path, fmt, dpi)
            out.append(path)
            if register:
                C.register_layout(layout)
        return out


# --------------------------------------------------------------------------
def _copy(src, dst_dir, done):
    if not src or not os.path.exists(src):
        return None
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    key = (os.path.abspath(src), dst_dir)
    if key in done:
        return dst
    shutil.copy2(src, dst)
    done.add(key)
    return dst


def export_result_bundle(result, folder, builder=None, with_maps=True, dpi=150):
    """Tous les fichiers d'une analyse : statistiques, fiche PDF, couches, graphiques, cartes."""
    os.makedirs(folder, exist_ok=True)
    files = ST.export_result(result, folder)
    files.append(R.result_pdf(result, folder))
    done = set()
    for s in result.layers:
        if s.path and os.path.abspath(s.path) != os.path.abspath(result.dem_source or ""):
            p = _copy(s.path, os.path.join(folder, "couches"), done)
            if p and p not in files:
                files.append(p)
    for c in result.charts:
        p = _copy(c, os.path.join(folder, "graphiques"), done)
        if p:
            files.append(p)
    for c in result.exports:
        if c.lower().endswith(".csv") and os.path.dirname(c) != folder:
            p = _copy(c, os.path.join(folder, "donnees"), done)
            if p:
                files.append(p)
    if with_maps and builder is not None:
        specs = []
        seen = set()
        for s in result.layers:
            if s.map_key and s.map_key not in seen and project_layer(s) is not None:
                ms = builder.spec_for_layer(s, result)
                if ms is not None:
                    specs.append(ms)
                    seen.add(s.map_key)
        if specs:
            files += builder.export(specs, os.path.join(folder, "cartes"), "png", dpi=dpi)
    return files


def export_all(registry, root, builder=None, map_files=(), with_maps=False, progress=None):
    """Exportation globale vers root/TerraMorpho_Export/ (dossiers vides non créés)."""
    base = os.path.join(root, "TerraMorpho_Export")
    if os.path.exists(base):
        base = base + "_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    results = registry.all()
    written = []
    synth = []
    for i, r in enumerate(results):
        d = os.path.join(base, MODULE_DIRS[r.module], "{}_{}".format(r.slug[:32], r.created.strftime("%H%M%S")))
        stats_dir = os.path.join(base, MODULE_DIRS["statistiques"])
        rep_dir = os.path.join(base, MODULE_DIRS["rapports"])
        done = set()
        for s in r.layers:
            if s.path and os.path.abspath(s.path) != os.path.abspath(r.dem_source or ""):
                p = _copy(s.path, d, done)
                if p:
                    written.append(p)
        for c in r.charts + [e for e in r.exports if e.lower().endswith(".csv")]:
            p = _copy(c, os.path.join(d, "graphiques" if not c.lower().endswith(".csv") else "donnees"), done)
            if p:
                written.append(p)
        prefix = "{}_{}".format(MODULE_DIRS[r.module][:2], r.slug[:28])
        written.append(ST.write_txt(r, os.path.join(stats_dir, prefix + ".txt")))
        written.append(ST.write_xlsx(r, os.path.join(stats_dir, prefix + ".xlsx")))
        written.append(R.write_pdf(R.result_html(r), os.path.join(rep_dir, prefix + "_fiche.pdf")))
        for lab, val, unit in r.summary:
            synth.append([r.module_title, r.title, r.created.strftime("%d/%m/%Y %H:%M"), lab, val, unit])
        if progress:
            progress(100.0 * (i + 1) / max(1, len(results)))
    if synth:
        t = Table("Synthèse des analyses", ["Module", "Analyse", "Date", "Indicateur", "Valeur", "Unité"], synth)
        written.append(ST.write_xlsx([t], os.path.join(base, MODULE_DIRS["statistiques"], "synthese_analyses.xlsx")))
        written.append(ST.write_csv(t, os.path.join(base, MODULE_DIRS["statistiques"], "synthese_analyses.csv")))
    done = set()
    for f in map_files:
        p = _copy(f, os.path.join(base, MODULE_DIRS["cartes"]), done)
        if p:
            written.append(p)
    if with_maps and builder is not None:
        specs = []
        for key, title, ok, _ in builder.availability():
            if ok:
                ms = builder.spec_for_key(key)
                if ms is not None:
                    specs.append(ms)
        if specs:
            written += builder.export(specs, os.path.join(base, MODULE_DIRS["cartes"]), "pdf", atlas=True)
    with open(os.path.join(base, "LISEZMOI.txt"), "w", encoding="utf-8") as f:
        f.write("TERRA-MORPHO GIS - exportation du {}\n\n".format(
            datetime.datetime.now().strftime("%d/%m/%Y %H:%M")))
        f.write("{} analyse(s) exportée(s). Les dossiers des modules non exécutés ne sont pas créés.\n\n".format(len(results)))
        for r in results:
            f.write("- {} : {} ({})\n".format(r.module_title, r.title, r.created.strftime("%d/%m/%Y %H:%M")))
    return base, written
