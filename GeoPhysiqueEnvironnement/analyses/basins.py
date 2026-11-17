# -*- coding: utf-8 -*-
"""Délimitation des bassins versants et découpage en sous-bassins."""
import math
import os

import numpy as np

from ..core import hydrology as hy, morphometry as M, terrain as T, vector_io as V
from ..core.grid import write_raster
from ..engines import charts, styles as S
from ..engines.results import LayerSpec, Table
from ..engines.statistics import class_table
from .common import new_result, check_grid, ensure_hydro, cells_to_km2, km2_to_cells
from .hydrology import stream_records, STREAM_FIELDS, FILL_LABELS

MORPHO_FIELDS = [k for k, *_ in M.FIELDS]
SUMMARY_KEYS = ["aire_km2", "perim_km", "long_km", "larg_moy_km", "z_min", "z_max", "z_moy", "denivele_m",
                "pente_moy", "kc_gravelius", "rf_forme", "re_allong", "rc_circul", "integ_hyps",
                "long_reseau_km", "dens_drain", "freq_cours_eau", "strahler_max", "shreve", "rb_bifurc",
                "lcp_km", "pente_lcp", "tc_kirpich_min", "tc_giandotti_h"]

BASIN_METHOD = (
    "Préparation : {fill} ; directions D8 avec drainage des zones planes ; accumulation D8 ; réseau extrait "
    "au seuil indiqué.\n"
    "Bassin : ensemble des cellules dont le chemin d'écoulement D8 aboutit à la cellule exutoire (parcours "
    "topologique de l'aval vers l'amont). Vectorisation GDAL en connexité 8.\n"
    "Paramètres morphométriques : voir le tableau « Définition des paramètres » (formules, unités, nature). "
    "Les temps de concentration sont des estimations empiriques, pas des mesures.")
BASIN_LIMITS = (
    "La délimitation automatique est à vérifier : position de l'exutoire, ouvrages (ponts, digues) et zones "
    "planes peuvent dévier les écoulements. Un bassin qui touche le bord du MNT est probablement incomplet. "
    "Le périmètre dépend de la résolution (effet d'escalier atténué par simplification) : Gravelius et "
    "circularité en héritent.")


def _field_defs():
    defs = []
    for k, lab, unit, nature, formula in M.FIELDS:
        t = int if k in ("id", "nb_cours_eau", "strahler_max", "shreve", "touche_bord") else float
        defs.append((k, t))
    return defs


def definitions_table():
    return Table("Définition des paramètres morphométriques",
                 ["Champ", "Paramètre", "Unité", "Nature", "Formule / méthode"],
                 [[k, lab, unit, nature, f] for k, lab, unit, nature, f in M.FIELDS])


def _attrs(row):
    return {k: row.get(k) for k in MORPHO_FIELDS}


def basin_products(res, grid, st, labels, ids, outlets, out, prefix, layer_name, title_word,
                   extra_attrs=None, map_key="bassin", clip_rasters=True):
    """Polygones, paramètres, réseau, cours d'eau principaux et rasters découpés."""
    model, net = st.model, st.net
    nc = grid.ncols
    geoms = V.polygonize_labels(labels, grid)
    slope = T.slope(grid.z, grid.dx, grid.dy)
    ufl_local = hy.flow_length_upstream(model, labels)
    rows, paths = M.basin_parameters(grid, model, labels, ids, outlets, geoms, slope, net, ufl_local,
                                     st.edge, grid.z.ravel())
    gpkg = os.path.join(out, "{}.gpkg".format(prefix))
    fields = _field_defs() + [(k, t) for k, t in (extra_attrs or {}).get("_fields", [])]
    recs = []
    for r in rows:
        a = _attrs(r)
        if extra_attrs:
            a.update(extra_attrs.get(r["id"], {}))
        recs.append((geoms[r["id"]], a))
    V.write_polygons(gpkg, layer_name, grid.wkt, fields, recs)
    # cours d'eau principaux
    lines = []
    for r in rows:
        pth = paths.get(r["id"])
        if pth and len(pth) > 1:
            cells = np.array(pth)
            xs, ys = grid.rc_to_xy(cells // nc, cells % nc)
            lines.append((xs, ys, {"id": r["id"], "long_km": r["lcp_km"], "pente_m_m": r["pente_lcp"],
                                   "z_amont": float(grid.z.ravel()[cells[0]]), "z_aval": float(grid.z.ravel()[cells[-1]])}))
    V.write_lines(gpkg, "cours_eau_principal", grid.wkt,
                  [("id", int), ("long_km", float), ("pente_m_m", float), ("z_amont", float), ("z_aval", float)], lines)
    mask = labels > 0
    srec = stream_records(grid, st, mask)
    V.write_lines(gpkg, "reseau", grid.wkt, STREAM_FIELDS, srec)
    res.add_layer(LayerSpec(gpkg, "Réseau hydrographique ({})".format(title_word), "vector", "reseau",
                            {"type": "streams", "field": "strahler", "label": "Strahler"},
                            map_key="reseau", map_title="Carte du réseau hydrographique"))
    res.add_layer(LayerSpec(gpkg, "Cours d'eau principal ({})".format(title_word), "vector", "cours_eau_principal",
                            {"type": "lines", "color": "#08306b", "width": 0.9}, map_key="cours_principal",
                            map_title="Carte du cours d'eau principal"))
    res.add_layer(LayerSpec(gpkg, layer_name.replace("_", " ").capitalize(), "vector", layer_name,
                            {"type": "categories", "field": "id", "label": title_word.capitalize()},
                            map_key=map_key, map_title="Carte des {}".format(layer_name.replace("_", " "))))
    if clip_rasters:
        z_b = np.where(mask.reshape(grid.z.shape), grid.z, np.nan)
        s_b = np.where(mask.reshape(grid.z.shape), slope, np.nan)
        pth = write_raster(os.path.join(out, "{}_mnt.tif".format(prefix)), z_b, grid)
        res.add_layer(LayerSpec(pth, "Hypsométrie ({})".format(title_word),
                                style=S.ramp_style(z_b, "hypsometrie", "minmax", 9, "m", opacity=0.85, fmt="{:.0f}"),
                                map_key="hypsometrie_bassin", map_title="Carte hypsométrique du bassin", units="m"))
        pth = write_raster(os.path.join(out, "{}_pente.tif".format(prefix)), s_b, grid)
        res.add_layer(LayerSpec(pth, "Pente ({})".format(title_word),
                                style=S.ramp_style(s_b, "pente", "p2p98", 5, "°", fmt="{:.1f}"),
                                map_key="pentes_bassin", map_title="Carte des pentes du bassin", units="°",
                                visible=False))
        pct = np.tan(np.radians(s_b)) * 100
        cls = T.classify_open(pct, T.FAO_SLOPE_BREAKS)
        pth = write_raster(os.path.join(out, "{}_classes_pente.tif".format(prefix)), cls, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Classes de pente ({})".format(title_word),
                                style=S.classes_style(T.FAO_SLOPE_LABELS, ramp="pente"),
                                map_key="classes_pente_bassin", map_title="Carte des classes de pente du bassin",
                                visible=False))
        res.add_table(class_table("Classes de pente dans le(s) {} (FAO 2006)".format(title_word), cls,
                                  T.FAO_SLOPE_LABELS, grid.cell_area))
        lab_r = write_raster(os.path.join(out, "{}_labels.tif".format(prefix)),
                             labels.reshape(grid.z.shape), grid, "int32", 0)
        res.extra["labels_raster"] = lab_r
    return rows, paths, geoms, gpkg


def _wide_table(title, rows, extra_cols=()):
    keys = ["id"] + list(extra_cols) + SUMMARY_KEYS + ["touche_bord"]
    heads, units = [], []
    for k in keys:
        lab, unit, nature, _ = M.FIELD_LABELS.get(k, (k, "", "", ""))
        heads.append(lab + (" [estimé]" if nature == "estimé" else ""))
        units.append(unit)
    return Table(title, heads, [[r.get(k) for k in keys] for r in rows], units)


def _long_table(row, title):
    out = []
    for k, lab, unit, nature, formula in M.FIELDS:
        out.append([lab, row.get(k), unit, nature])
    return Table(title, ["Paramètre", "Valeur", "Unité", "Nature"], out)


def _order_table(rows):
    data = []
    for r in rows:
        for o, n in sorted(r.get("_n_par_ordre", {}).items()):
            data.append([r["id"], o, n])
    return Table("Nombre de cours d'eau par ordre de Strahler", ["Bassin", "Ordre", "Nombre"], data)


def _common_params(res, st, grid, p):
    res.add_param("Correction des dépressions", FILL_LABELS[st.params.get("fill", "fill")])
    thr = st.net.threshold_cells
    res.add_param("Seuil d'accumulation du réseau", "{:g} cellules = {:.4f} km²".format(thr, cells_to_km2(thr, grid)))


# --------------------------------------------------------------------------
def run_outlets(params, ctx, fb):
    """Délimitation à partir d'un ou plusieurs exutoires (coordonnées dans le SCR du MNT)."""
    p = dict({"snap": True, "snap_radius_m": 150.0, "snap_to_stream": True, "fill": "fill"}, **params)
    grid = ctx.grid(p["dem_path"], p.get("band", 1))
    res = new_result("bassins", "Délimitation de bassin versant", grid)
    check_grid(grid, res)
    out = ctx.module_dir("bassins")
    res.folder = out
    st = ensure_hydro(ctx, grid, p, fb, (0, 50))
    _common_params(res, st, grid, p)
    model, net = st.model, st.net
    nc = grid.ncols
    acc = st.acc_d8
    rad = max(0, int(round(p["snap_radius_m"] / grid.dx))) if p["snap"] else 0
    res.add_param("Repositionnement de l'exutoire", "oui, rayon {:g} m ({} cellules){}".format(
        p["snap_radius_m"], rad, ", sur le réseau" if p["snap_to_stream"] else "") if p["snap"] else "non")
    seeds, initial, corrected = [], [], []
    for k, pt in enumerate(p["outlets"], start=1):
        x, y = pt[0], pt[1]
        name = pt[2] if len(pt) > 2 else "Exutoire {}".format(k)
        r, c = grid.xy_to_rc(x, y)
        if not grid.inside(r, c) or not grid.valid[r, c]:
            res.warnings.append("{} ({:.1f}, {:.1f}) hors du MNT ou sur NoData : ignoré.".format(name, x, y))
            continue
        r2, c2 = (hy.snap_outlet(model, acc, r, c, rad, net.mask if p["snap_to_stream"] else None)
                  if rad > 0 else (r, c))
        i2 = r2 * nc + c2
        if i2 in seeds:
            res.warnings.append("{} recalé sur la même cellule qu'un autre exutoire : ignoré.".format(name))
            continue
        seeds.append(i2)
        x2, y2 = grid.rc_to_xy(r2, c2)
        cx, cy = grid.rc_to_xy(r, c)
        dist = math.hypot(float(x2) - float(cx), float(y2) - float(cy))
        initial.append((x, y, {"id": len(seeds), "nom": name, "aire_amont_km2": cells_to_km2(float(acc[r, c]), grid)}))
        corrected.append((float(x2), float(y2), {"id": len(seeds), "nom": name, "deplacement_m": dist,
                                                 "aire_amont_km2": cells_to_km2(float(acc[r2, c2]), grid),
                                                 "sur_reseau": int(net.mask[i2])}))
    if not seeds:
        raise ValueError("Aucun exutoire valide dans l'emprise du MNT.")
    fb.progress(55)
    labels = hy.label_basins(model, seeds)
    ids = list(range(1, len(seeds) + 1))
    outlets = {i: s for i, s in zip(ids, seeds)}
    fb.info("Vectorisation et paramètres morphométriques…")
    rows, paths, geoms, gpkg = basin_products(res, grid, st, labels, ids, outlets, out, "bassin_versant",
                                              "bassins_versants", "bassin")
    fb.progress(85)
    fields = [("id", int), ("nom", str), ("aire_amont_km2", float)]
    V.write_points(gpkg, "exutoires_initiaux", grid.wkt, fields, initial)
    V.write_points(gpkg, "exutoires_corriges", grid.wkt, fields + [("deplacement_m", float), ("sur_reseau", int)], corrected)
    res.add_layer(LayerSpec(gpkg, "Exutoires initiaux", "vector", "exutoires_initiaux",
                            {"type": "points", "color": "#ff7f00", "size": 3.2}, map_key="exutoires",
                            map_title="Carte des exutoires"))
    res.add_layer(LayerSpec(gpkg, "Exutoires corrigés", "vector", "exutoires_corriges",
                            {"type": "points", "color": "#e31a1c", "size": 3.6}, map_key="exutoires",
                            map_title="Carte des exutoires"))
    res.add_table(Table("Exutoires", ["Id", "Nom", "X initial", "Y initial", "X corrigé", "Y corrigé",
                                      "Déplacement", "Aire drainée", "Sur le réseau"],
                        [[c[2]["id"], c[2]["nom"], i[0], i[1], c[0], c[1], c[2]["deplacement_m"],
                          c[2]["aire_amont_km2"], c[2]["sur_reseau"]] for i, c in zip(initial, corrected)],
                        ["", "", "m", "m", "m", "m", "m", "km²", "0/1"]))
    _finish(res, rows, grid, st, out, labels, ids, outlets, paths, p)
    ctx.last_basin = res.extra["state"]
    for r in rows:
        if r["touche_bord"]:
            res.warnings.append("Le bassin {} touche le bord du MNT : délimitation probablement incomplète.".format(r["id"]))
    if len(seeds) > 1:
        res.warnings.append("Plusieurs exutoires : si l'un est en amont d'un autre, son bassin est soustrait "
                            "du bassin aval (bassins emboîtés découpés).")
    res.title = "Délimitation de bassin versant" if len(seeds) == 1 else "Délimitation de {} bassins versants".format(len(seeds))
    fb.progress(100)
    return res


def run_auto(params, ctx, fb):
    """Délimitation automatique de tous les bassins dépassant une superficie minimale."""
    p = dict({"min_area_km2": 5.0, "exclude_edge": False, "fill": "fill"}, **params)
    grid = ctx.grid(p["dem_path"], p.get("band", 1))
    res = new_result("bassins", "Délimitation automatique des bassins versants", grid)
    check_grid(grid, res)
    out = ctx.module_dir("bassins")
    res.folder = out
    st = ensure_hydro(ctx, grid, p, fb, (0, 50))
    _common_params(res, st, grid, p)
    min_cells = km2_to_cells(p["min_area_km2"], grid)
    res.add_param("Superficie minimale des bassins", p["min_area_km2"], "km²")
    res.add_param("Exclure les bassins touchant le bord", "oui" if p["exclude_edge"] else "non")
    labels, outs = hy.auto_basins(st.model, min_cells)
    n_candidates = int(hy.terminal_cells(st.model).size)
    res.add_summary("Sorties hydrologiques potentielles (cellules terminales)", n_candidates, "")
    ids = list(range(1, len(outs) + 1))
    outlets = dict(zip(ids, outs))
    if p["exclude_edge"] and ids:
        edge = st.edge.ravel()
        keep = []
        for i in ids:
            g = np.flatnonzero(labels == i)
            if not np.any(edge[g] & (g != outlets[i])):
                keep.append(i)
        remap = np.zeros(len(ids) + 1, np.int64)
        remap[keep] = np.arange(1, len(keep) + 1)
        labels = remap[labels]
        outlets = {j + 1: outlets[i] for j, i in enumerate(keep)}
        ids = list(range(1, len(keep) + 1))
    if not ids:
        raise ValueError("Aucun bassin n'atteint {:g} km². Réduisez la superficie minimale.".format(p["min_area_km2"]))
    res.add_summary("Bassins retenus", len(ids), "")
    fb.progress(60)
    rows, paths, geoms, gpkg = basin_products(res, grid, st, labels, ids, outlets, out, "bassins_auto",
                                              "bassins_versants", "bassin")
    nc = grid.ncols
    pts = []
    for i in ids:
        s = outlets[i]
        x, y = grid.rc_to_xy(s // nc, s % nc)
        kind = "puits" if st.model.sinks[s] else "bord du MNT"
        pts.append((float(x), float(y), {"id": i, "type": kind, "aire_km2": cells_to_km2(float(st.acc_d8.ravel()[s]), grid)}))
    V.write_points(gpkg, "exutoires", grid.wkt, [("id", int), ("type", str), ("aire_km2", float)], pts)
    res.add_layer(LayerSpec(gpkg, "Exutoires détectés", "vector", "exutoires",
                            {"type": "points", "color": "#e31a1c", "size": 3.0}, map_key="exutoires",
                            map_title="Carte des exutoires"))
    covered = sum(r["aire_km2"] for r in rows)
    total = grid.valid.sum() * grid.cell_area / 1e6
    res.add_summary("Superficie couverte par les bassins retenus", covered, "km²")
    res.add_summary("Part de l'emprise couverte", 100 * covered / total if total else 0, "%")
    _finish(res, rows, grid, st, out, labels, ids, outlets, paths, p)
    ctx.last_basin = res.extra["state"]
    n_edge = sum(1 for r in rows if r["touche_bord"])
    if n_edge:
        res.warnings.append("{} bassin(s) touchent le bord du MNT : délimitation probablement incomplète "
                            "(champ touche_bord = 1).".format(n_edge))
    res.limits += (" Délimitation automatique : chaque sortie (bord du MNT ou puits) définit un bassin ; "
                   "les bassins sous la superficie minimale ne sont pas retenus.")
    fb.progress(100)
    return res


def _finish(res, rows, grid, st, out, labels, ids, outlets, paths, p):
    res.add_table(_wide_table("Paramètres morphométriques des bassins", rows))
    if len(rows) == 1:
        res.add_table(_long_table(rows[0], "Fiche morphométrique du bassin"))
        r = rows[0]
        for k in ("aire_km2", "perim_km", "kc_gravelius", "denivele_m", "pente_moy", "dens_drain",
                  "strahler_max", "lcp_km", "tc_kirpich_min"):
            lab, unit, nature, _ = M.FIELD_LABELS[k]
            res.add_summary(lab + (" (estimé)" if nature == "estimé" else ""), r[k], unit)
    res.add_table(_order_table(rows))
    res.add_table(definitions_table())
    z = grid.z.ravel()
    for r in rows[:5]:
        vals = z[labels == r["id"]]
        h, above, hi = T.hypsometric_curve(vals)
        res.charts += charts.hypsometric_curve(h, above, hi, os.path.join(out, "courbe_hypsometrique_bassin_{}".format(r["id"])),
                                               "Courbe hypsométrique, bassin {}".format(r["id"]))
    if rows and rows[0].get("_n_par_ordre"):
        res.charts += charts.horton_plot(rows[0]["_n_par_ordre"], os.path.join(out, "loi_horton_bassin_1"))
    res.method = BASIN_METHOD.format(fill=FILL_LABELS[st.params.get("fill", "fill")])
    res.limits = BASIN_LIMITS
    # état réutilisé par les sous-bassins et les profils
    res.extra["state"] = {"labels": labels, "ids": ids, "outlets": outlets, "rows": rows, "paths": paths,
                          "hydro_key": st.key, "grid_source": grid.source}


# --------------------------------------------------------------------------
SUB_METHODS = {
    "liens": "Confluences / tronçons hydrographiques (un sous-bassin par tronçon)",
    "strahler": "Ordre de Strahler (un sous-bassin par cours d'eau d'ordre ≥ k)",
    "superficie": "Superficie minimale (fusion vers l'aval des sous-bassins trop petits)",
    "seuil": "Seuil d'accumulation propre au découpage",
    "points": "Exutoires intermédiaires / points de contrôle de l'utilisateur",
}


def run_subbasins(params, ctx, fb):
    p = dict({"method": "liens", "strahler_min": 2, "min_area_km2": 1.0, "threshold_km2": 1.0,
              "points": [], "snap_radius_m": 150.0, "basin_id": 1}, **params)
    lb = ctx.last_basin
    if lb is None:
        raise ValueError("Délimitez d'abord un bassin versant (rubrique « Bassins versants »).")
    st = ctx.hydro
    if st is None or st.key != lb["hydro_key"]:
        raise ValueError("L'état hydrologique a changé depuis la délimitation : relancez la délimitation du bassin.")
    grid = st.grid
    res = new_result("sous_bassins", "Découpage en sous-bassins versants", grid)
    out = ctx.module_dir("sous_bassins")
    res.folder = out
    model, net = st.model, st.net
    nc = grid.ncols
    bid = int(p["basin_id"])
    if bid not in lb["outlets"]:
        raise ValueError("Bassin {} introuvable.".format(bid))
    basin_mask = lb["labels"] == bid
    outlet = lb["outlets"][bid]
    _common_params(res, st, grid, p)
    res.add_param("Bassin parent", bid)
    res.add_param("Méthode de découpage", SUB_METHODS[p["method"]])
    method = p["method"]
    if method == "liens":
        seeds = hy.subbasin_seeds(model, net, basin_mask, outlet, "liens")
    elif method == "strahler":
        seeds = hy.subbasin_seeds(model, net, basin_mask, outlet, "strahler", param=p["strahler_min"])
        res.add_param("Ordre de Strahler minimal", int(p["strahler_min"]))
    elif method == "seuil":
        thr = km2_to_cells(p["threshold_km2"], grid)
        seeds = hy.subbasin_seeds(model, net, basin_mask, outlet, "seuil", st.acc_d8, thr)
        res.add_param("Seuil d'accumulation du découpage", "{:g} km² ({:.0f} cellules)".format(p["threshold_km2"], thr))
    elif method == "superficie":
        seeds = hy.subbasin_seeds(model, net, basin_mask, outlet, "liens")
        res.add_param("Superficie minimale des sous-bassins", p["min_area_km2"], "km²")
    elif method == "points":
        rad = max(0, int(round(p["snap_radius_m"] / grid.dx)))
        cells = []
        for pt in p["points"]:
            r, c = grid.xy_to_rc(pt[0], pt[1])
            if not grid.inside(r, c):
                res.warnings.append("Point ({:.1f}, {:.1f}) hors du MNT : ignoré.".format(pt[0], pt[1]))
                continue
            r2, c2 = hy.snap_outlet(model, st.acc_d8, r, c, rad, net.mask) if rad else (r, c)
            i2 = r2 * nc + c2
            if not basin_mask[i2]:
                res.warnings.append("Point ({:.1f}, {:.1f}) hors du bassin : ignoré.".format(pt[0], pt[1]))
                continue
            cells.append(i2)
        seeds = hy.subbasin_seeds(model, net, basin_mask, outlet, "points", user_cells=np.array(cells, np.int64))
        res.add_param("Rayon de recalage des points", p["snap_radius_m"], "m")
    else:
        raise ValueError("Méthode inconnue.")
    fb.progress(20)
    if method == "superficie":
        seeds, labels = hy.merge_small_subbasins(model, seeds, outlet, km2_to_cells(p["min_area_km2"], grid))
    else:
        labels = hy.label_basins(model, seeds)
    labels = np.where(basin_mask, labels, 0)
    ids = list(range(1, len(seeds) + 1))
    outlets = {i: int(s) for i, s in zip(ids, seeds)}
    # relations amont-aval
    rel = {"_fields": [("parent", int), ("aval", int), ("ordre", int), ("amont", str)]}
    downstream = {}
    for i, s in outlets.items():
        r = model.rec[s]
        d = int(labels[r]) if r >= 0 and basin_mask[r] else 0
        downstream[i] = d
    upstream = {i: [] for i in ids}
    for i, d in downstream.items():
        if d:
            upstream[d].append(i)
    for i, s in outlets.items():
        rel[i] = {"parent": bid, "aval": downstream[i], "ordre": int(net.strahler[s]),
                  "amont": ",".join(str(u) for u in sorted(upstream[i]))}
    fb.info("{} sous-bassins : vectorisation et paramètres…".format(len(ids)))
    rows, paths, geoms, gpkg = basin_products(res, grid, st, labels, ids, outlets, out, "sous_bassins",
                                              "sous_bassins", "sous-bassin", rel, map_key="sous_bassins")
    for r in rows:
        r.update(rel[r["id"]])
    fb.progress(80)
    pts = []
    for i, s in outlets.items():
        x, y = grid.rc_to_xy(s // nc, s % nc)
        pts.append((float(x), float(y), {"id": i, "aval": downstream[i], "ordre": int(net.strahler[s])}))
    V.write_points(gpkg, "exutoires_sous_bassins", grid.wkt, [("id", int), ("aval", int), ("ordre", int)], pts)
    res.add_layer(LayerSpec(gpkg, "Exutoires des sous-bassins", "vector", "exutoires_sous_bassins",
                            {"type": "points", "color": "#e31a1c", "size": 2.6}, map_key="exutoires",
                            map_title="Carte des exutoires des sous-bassins"))
    # contrôle topologique
    basin_area = basin_mask.sum() * grid.cell_area / 1e6
    sum_area = sum(r["aire_km2"] for r in rows)
    poly_sum = sum(geoms[i].GetArea() for i in ids) / 1e6
    from osgeo import ogr
    invalid = 0
    coll = ogr.Geometry(ogr.wkbMultiPolygon)
    for i in ids:
        g = geoms[i]
        if not g.IsValid():
            invalid += 1
        flat = ogr.ForceToMultiPolygon(g.Clone())
        for k in range(flat.GetGeometryCount()):
            coll.AddGeometry(flat.GetGeometryRef(k))
    union = coll.UnionCascaded() if coll.GetGeometryCount() else None
    union_area = union.GetArea() / 1e6 if union is not None else 0.0
    overlap = poly_sum - union_area
    res.add_table(Table("Contrôle topologique et hydrologique",
                        ["Contrôle", "Valeur", "Unité", "Statut"],
                        [["Superficie du bassin parent (raster)", basin_area, "km²", ""],
                         ["Somme des superficies des sous-bassins (raster)", sum_area, "km²",
                          "conforme" if abs(sum_area - basin_area) <= 1e-9 * max(1, basin_area) + grid.cell_area / 1e6 else "écart"],
                         ["Écart relatif", 100 * (sum_area - basin_area) / basin_area if basin_area else 0, "%", ""],
                         ["Somme des aires des polygones", poly_sum, "km²", ""],
                         ["Aire de l'union des polygones", union_area, "km²", ""],
                         ["Recouvrements entre sous-bassins", overlap, "km²", "conforme" if abs(overlap) < grid.cell_area / 1e6 else "à vérifier"],
                         ["Zone non couverte", basin_area - union_area, "km²",
                          "conforme" if abs(basin_area - union_area) < grid.cell_area / 1e6 else "à vérifier"],
                         ["Géométries invalides", invalid, "", "conforme" if invalid == 0 else "à vérifier"],
                         ["Sous-bassins sans aval (exutoire du bassin)", sum(1 for d in downstream.values() if d == 0), "",
                          "conforme" if sum(1 for d in downstream.values() if d == 0) == 1 else "à vérifier"]]))
    res.add_table(_wide_table("Tableau comparatif des sous-bassins", rows, ("parent", "aval", "ordre")))
    res.add_table(Table("Relations amont-aval", ["Sous-bassin", "Aval", "Amont", "Ordre de Strahler à l'exutoire"],
                        [[i, downstream[i] or "exutoire", ",".join(str(u) for u in sorted(upstream[i])) or "-",
                          int(net.strahler[outlets[i]])] for i in ids]))
    res.add_table(definitions_table())
    res.add_summary("Nombre de sous-bassins", len(ids), "")
    res.add_summary("Superficie du bassin parent", basin_area, "km²")
    res.add_summary("Somme des superficies des sous-bassins", sum_area, "km²")
    areas = [r["aire_km2"] for r in rows]
    res.add_summary("Superficie moyenne des sous-bassins", float(np.mean(areas)), "km²")
    res.add_summary("Plus petit / plus grand sous-bassin", "{:.3f} / {:.3f}".format(min(areas), max(areas)).replace(".", ","), "km²")
    if len(rows) <= 60:
        res.charts += charts.bars([str(r["id"]) for r in rows], areas, os.path.join(out, "superficies_sous_bassins"),
                                  "Superficie des sous-bassins", "km²")
    res.method = BASIN_METHOD.format(fill=FILL_LABELS[st.params.get("fill", "fill")]) + (
        "\nSous-bassins : chaque exutoire intermédiaire délimite la zone qui lui est propre ; un exutoire "
        "situé en aval s'arrête aux limites des sous-bassins amont. La relation « aval » est le sous-bassin "
        "qui reçoit l'écoulement de l'exutoire. Longueur hydrographique principale : plus long chemin "
        "d'écoulement interne au sous-bassin.")
    res.limits = BASIN_LIMITS + (" Les sous-bassins d'interfluve (sans cours d'eau propre) sont normaux avec "
                                 "un découpage par tronçons ; préférez la méthode par superficie minimale pour "
                                 "les regrouper.")
    res.extra["state"] = {"labels": labels, "ids": ids, "outlets": outlets, "rows": rows, "paths": paths}
    fb.progress(100)
    return res
