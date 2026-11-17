# -*- coding: utf-8 -*-
"""Module hydrologique : prétraitement, directions, accumulations, réseau."""
import os

import numpy as np

from ..core import hydrology as hy, geomorph as GM, vector_io as V
from ..core.grid import write_raster, D8_CODES
from ..engines import charts, styles as S
from ..engines.results import LayerSpec, Table
from ..engines.statistics import describe, describe_table, class_table
from .common import new_result, check_grid, ensure_hydro, cells_to_km2

DEFAULTS = {
    "fill": "fill", "max_depth": 2.0, "flow": "d8", "mfd_exponent": 1.1, "threshold_cells": None,
    "products": ["filled", "depressions", "directions", "accumulation", "flow_length", "convergence",
                 "concentration", "streams", "confluences"],
}

FILL_LABELS = {
    "fill": "Comblement complet (Priority-Flood)",
    "fill_depth": "Comblement limité en profondeur (dépressions profondes conservées)",
    "none": "Aucune correction (dépressions conservées)",
}
FLOW_LABELS = {"d8": "D8 (O'Callaghan & Mark 1984)", "mfd": "MFD (Freeman 1991)", "dinf": "D-Infinity (Tarboton 1997)"}
DIR_LABELS = ["Est", "Sud-est", "Sud", "Sud-ouest", "Ouest", "Nord-ouest", "Nord", "Nord-est"]

STREAM_FIELDS = [("troncon", int), ("strahler", int), ("shreve", int), ("aval", int), ("long_m", float),
                 ("z_amont", float), ("z_aval", float), ("pente_m_m", float), ("aire_amont_km2", float)]


def stream_records(grid, st, mask=None):
    """Tronçons du réseau sous forme de polylignes (option : limités à un masque à plat)."""
    model, net = st.model, st.net
    nc = grid.ncols
    z = grid.z.ravel()
    recs = []
    lengths = {}
    for lid, cells in hy.link_polylines(model, net, None, None):
        if mask is not None and not mask[cells[0]]:
            continue
        if mask is not None:
            keep = mask[cells]
            # garder la jonction aval seulement si elle est dans le masque
            cells = cells[keep] if not keep.all() else cells
            if cells.size < 2:
                continue
        r, c = cells // nc, cells % nc
        xs, ys = grid.rc_to_xy(r, c)
        seg = np.hypot(np.diff(xs), np.diff(ys)).sum()
        last = cells[-1]
        down = model.rec[cells[-2]] if cells.size >= 2 else -1
        aval = int(net.link[down]) if down >= 0 and net.mask[down] and net.link[down] != lid else 0
        zu, zd = float(z[cells[0]]), float(z[cells[-1]])
        recs.append((xs, ys, {
            "troncon": lid, "strahler": int(net.strahler[cells[0]]), "shreve": int(net.shreve[cells[-2] if cells.size > 1 else last]),
            "aval": aval, "long_m": float(seg), "z_amont": zu, "z_aval": zd,
            "pente_m_m": (zu - zd) / seg if seg > 0 else None,
            "aire_amont_km2": cells_to_km2(float(st.acc_d8.ravel()[cells[-2] if cells.size > 1 else last]), grid),
        }))
        lengths[lid] = seg
    return recs


def run(params, ctx, fb):
    p = dict(DEFAULTS, **params)
    prods = set(p["products"])
    grid = ctx.grid(p["dem_path"], p.get("band", 1))
    res = new_result("hydrologie", "Analyse hydrologique", grid)
    check_grid(grid, res)
    out = ctx.module_dir("hydrologie")
    res.folder = out
    ca = grid.cell_area
    st = ensure_hydro(ctx, grid, p, fb, (0, 50))
    model, net = st.model, st.net
    valid = grid.valid
    vflat = valid.ravel()
    thr = st.net.threshold_cells
    res.add_param("Correction des dépressions", FILL_LABELS[p["fill"]])
    if p["fill"] == "fill_depth":
        res.add_param("Profondeur maximale comblée", p["max_depth"], "m")
    res.add_param("Méthode de direction des écoulements", FLOW_LABELS[p["flow"]])
    if p["flow"] == "mfd":
        res.add_param("Exposant MFD", p["mfd_exponent"], "")
    res.add_param("Seuil d'accumulation du réseau", "{:g} cellules = {:.4f} km²".format(thr, cells_to_km2(thr, grid)))

    depth = st.filled - grid.z
    dep = np.where(valid & (depth > 1e-9), depth, np.nan)
    n_dep_cells = int(np.isfinite(dep).sum())
    res.add_summary("Cellules relevées par le comblement", n_dep_cells, "")
    res.add_summary("Superficie des dépressions comblées", cells_to_km2(n_dep_cells, grid), "km²")
    res.add_summary("Volume de comblement", float(np.nansum(dep)) * ca / 1e6, "hm³")
    res.add_summary("Profondeur maximale comblée", float(np.nanmax(dep)) if n_dep_cells else 0.0, "m")
    n_sinks = int(model.sinks.sum())
    res.add_summary("Puits conservés (cellules terminales intérieures)", n_sinks, "")
    if "filled" in prods and p["fill"] != "none":
        pth = write_raster(os.path.join(out, "mnt_corrige.tif"), st.filled, grid)
        res.add_layer(LayerSpec(pth, "MNT hydrologiquement corrigé",
                                style=S.ramp_style(st.filled, "hypsometrie", "minmax", 9, "m", fmt="{:.0f}"),
                                map_key="mnt_corrige", map_title="MNT hydrologiquement corrigé", units="m",
                                visible=False))
    if "depressions" in prods and n_dep_cells:
        pth = write_raster(os.path.join(out, "profondeur_depressions.tif"), dep, grid)
        res.add_layer(LayerSpec(pth, "Profondeur des dépressions comblées",
                                style=S.ramp_style(dep, "humidite", "p2p98", 5, "m"),
                                map_key="depressions", map_title="Carte des dépressions détectées", units="m",
                                visible=False))
    fb.progress(55)

    # ---- directions D8
    codes = model.d8_codes()
    dir_cls = np.zeros(codes.shape, np.uint8)
    for i, c in enumerate(D8_CODES):
        dir_cls[codes == c] = i + 1
    tab = class_table("Statistiques des directions d'écoulement (D8)", dir_cls, DIR_LABELS, ca)
    res.add_table(tab)
    res.add_summary("Cellules d'écoulement (valides)", int(vflat.sum()), "")
    res.add_summary("Cellules de sortie (bord ou puits)", int((vflat & (model.rec < 0)).sum()), "")
    if "directions" in prods:
        pth = write_raster(os.path.join(out, "directions_d8.tif"), codes, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Directions d'écoulement (D8)",
                                style=S.classes_style(["{} ({})".format(lab, c) for lab, c in zip(DIR_LABELS, D8_CODES)],
                                                      S.ASPECT_COLORS[1:], codes=list(D8_CODES)),
                                map_key="directions", map_title="Carte des directions d'écoulement"))

    # ---- accumulation selon la méthode
    fb.info("Accumulation des écoulements ({})…".format(p["flow"].upper()))
    if p["flow"] == "mfd":
        acc = hy.accumulate_mfd(model, p["mfd_exponent"], feedback=fb)
    elif p["flow"] == "dinf":
        acc = hy.accumulate_dinf(model, feedback=fb)
    else:
        acc = st.acc_d8
    fb.progress(75)
    acc_km2 = acc * ca / 1e6
    d = describe(acc)
    res.add_summary("Accumulation minimale", d["min"], "cellules")
    res.add_summary("Accumulation maximale", d["max"], "cellules")
    res.add_summary("Accumulation moyenne", d["moyenne"], "cellules")
    res.add_summary("Aire drainée maximale", d["max"] * ca / 1e6, "km²")
    if "accumulation" in prods:
        pth = write_raster(os.path.join(out, "accumulation_{}.tif".format(p["flow"])), acc, grid)
        res.add_layer(LayerSpec(pth, "Accumulation des écoulements ({})".format(p["flow"].upper()),
                                style=S.ramp_style(acc, "ecoulement", "log", 6, "cellules", fmt="{:.0f}"),
                                map_key="accumulation", map_title="Carte d'accumulation des écoulements",
                                units="cellules"))
    stats = [("Accumulation ({})".format(p["flow"].upper()), acc, "cellules"),
             ("Aire drainée ({})".format(p["flow"].upper()), acc_km2, "km²")]
    if "flow_length" in prods:
        dfl = hy.flow_length_downstream(model)
        ufl = hy.flow_length_upstream(model).reshape(grid.z.shape)
        stats += [("Longueur d'écoulement aval", dfl, "m"), ("Longueur d'écoulement amont", ufl, "m")]
        pth = write_raster(os.path.join(out, "longueur_ecoulement_aval.tif"), dfl, grid)
        res.add_layer(LayerSpec(pth, "Longueur d'écoulement vers l'aval", style=S.ramp_style(dfl, "sequentiel", "minmax", 5, "m", fmt="{:.0f}"),
                                map_key="longueur_aval", map_title="Carte des longueurs d'écoulement (aval)", units="m",
                                visible=False))
        pth = write_raster(os.path.join(out, "longueur_ecoulement_amont.tif"), ufl, grid)
        res.add_layer(LayerSpec(pth, "Longueur d'écoulement depuis l'amont", style=S.ramp_style(ufl, "sequentiel", "p2p98", 5, "m", fmt="{:.0f}"),
                                map_key="longueur_amont", map_title="Carte des longueurs d'écoulement (amont)", units="m",
                                visible=False))
    fb.progress(80)
    if "convergence" in prods:
        ci = GM.convergence_index(grid.z, grid.dx, grid.dy)
        stats.append(("Indice de convergence", ci, "%"))
        pth = write_raster(os.path.join(out, "indice_convergence.tif"), ci, grid)
        res.add_layer(LayerSpec(pth, "Indice de convergence (Köthe & Lehmeier)",
                                style=S.ramp_style(ci, "divergent", "diverging", 5, "%", fmt="{:.0f}"),
                                map_key="convergence", map_title="Carte des zones de convergence", units="%"))
        conv = np.zeros(ci.shape, np.uint8)
        f = np.isfinite(ci)
        conv[f & (ci <= -10)] = 1
        conv[f & (ci > -10) & (ci < 10)] = 2
        conv[f & (ci >= 10)] = 3
        res.add_table(class_table("Zones de convergence et de divergence", conv,
                                  ["Convergence (IC ≤ -10 %)", "Neutre", "Divergence (IC ≥ 10 %)"], ca))
    if "concentration" in prods:
        la = np.log10(np.where(acc > 0, acc_km2, np.nan))
        lv = la[np.isfinite(la)]
        brk = list(np.quantile(lv, [0.5, 0.8, 0.95, 0.99]))
        cc = np.zeros(la.shape, np.uint8)
        f = np.isfinite(la)
        cc[f] = (np.searchsorted(brk, la[f], side="right") + 1).astype(np.uint8)
        labels = ["Très faible (< médiane)", "Faible (50–80 %)", "Moyenne (80–95 %)", "Forte (95–99 %)", "Très forte (> 99 %)"]
        res.add_table(class_table("Zones de concentration des écoulements", cc, labels, ca))
        pth = write_raster(os.path.join(out, "concentration_ecoulements.tif"), cc, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Potentiel de concentration du ruissellement",
                                style=S.classes_style(labels, ramp="ecoulement"),
                                map_key="concentration", map_title="Carte du potentiel de concentration du ruissellement",
                                visible=False))
    res.add_table(describe_table("Statistiques hydrologiques", stats, ca))
    fb.check()
    fb.progress(85)

    # ---- réseau hydrographique
    recs = stream_records(grid, st)
    total_len = sum(r[2]["long_m"] for r in recs) / 1000.0
    area = valid.sum() * ca / 1e6
    n_conf = int(net.junction.sum())
    orders = {}
    starts = np.flatnonzero(net.order_start)
    if starts.size:
        u, c = np.unique(net.strahler[starts], return_counts=True)
        orders = {int(a): int(b) for a, b in zip(u, c)}
    res.add_summary("Longueur totale du réseau", total_len, "km")
    res.add_summary("Nombre de tronçons (entre confluences)", len(recs), "")
    res.add_summary("Nombre de cours d'eau (Strahler, Σ Nu)", sum(orders.values()), "")
    res.add_summary("Nombre de confluences", n_conf, "")
    res.add_summary("Densité de drainage (emprise du MNT)", total_len / area if area else float("nan"), "km/km²")
    res.add_summary("Fréquence hydrographique", sum(orders.values()) / area if area else float("nan"), "1/km²")
    res.add_summary("Ordre de Strahler maximal", int(net.strahler.max()), "")
    res.add_summary("Magnitude de Shreve maximale", int(net.shreve.max()), "")
    rows = []
    lens = {}
    for r in recs:
        lens[r[2]["strahler"]] = lens.get(r[2]["strahler"], 0.0) + r[2]["long_m"] / 1000.0
    for o in sorted(orders):
        nxt = orders.get(o + 1)
        rows.append([o, orders[o], lens.get(o, 0.0), lens.get(o, 0.0) / orders[o] if orders[o] else None,
                     orders[o] / nxt if nxt else None])
    res.add_table(Table("Répartition des ordres de Strahler", ["Ordre", "Nombre de cours d'eau", "Longueur totale",
                                                              "Longueur moyenne", "Rapport de bifurcation"],
                        rows, ["", "", "km", "km", ""]))
    sh = net.shreve[net.mask]
    if sh.size:
        bins = [1, 2, 3, 5, 10, 20, 50, 100, 1000, 10 ** 9]
        rows = []
        for a, b in zip(bins[:-1], bins[1:]):
            n = int(((sh >= a) & (sh < b)).sum())
            if n:
                rows.append(["{} – {}".format(a, b - 1) if b < 10 ** 9 else "≥ {}".format(a), n, 100.0 * n / sh.size])
        res.add_table(Table("Répartition des magnitudes de Shreve (cellules du réseau)",
                            ["Magnitude", "Cellules du réseau", "Part (%)"], rows))
    res.charts += charts.horton_plot(orders, os.path.join(out, "loi_horton"))
    if "streams" in prods:
        gpkg = os.path.join(out, "reseau_hydrographique.gpkg")
        V.write_lines(gpkg, "reseau", grid.wkt, STREAM_FIELDS, recs)
        res.add_layer(LayerSpec(gpkg, "Réseau hydrographique (Strahler)", "vector", "reseau",
                                {"type": "streams", "field": "strahler", "label": "Strahler"},
                                map_key="strahler", map_title="Carte des ordres hydrographiques de Strahler"))
        res.add_layer(LayerSpec(gpkg, "Réseau hydrographique (Shreve)", "vector", "reseau",
                                {"type": "streams_bins", "field": "shreve", "label": "Shreve",
                                 "bins": [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 10 ** 9]},
                                map_key="shreve", map_title="Carte des ordres hydrographiques de Shreve",
                                visible=False))
    if "confluences" in prods and n_conf:
        nc = grid.ncols
        j = np.flatnonzero(net.junction)
        xs, ys = grid.rc_to_xy(j // nc, j % nc)
        pts = [(x, y, {"id": i + 1, "strahler": int(net.strahler[k]), "shreve": int(net.shreve[k]),
                       "aire_amont_km2": cells_to_km2(float(st.acc_d8.ravel()[k]), grid)})
               for i, (x, y, k) in enumerate(zip(xs, ys, j))]
        gpkg = os.path.join(out, "reseau_hydrographique.gpkg")
        V.write_points(gpkg, "confluences", grid.wkt,
                       [("id", int), ("strahler", int), ("shreve", int), ("aire_amont_km2", float)], pts)
        res.add_layer(LayerSpec(gpkg, "Confluences", "vector", "confluences", {"type": "points", "color": "#e31a1c", "size": 2.2},
                                map_key="confluences", map_title="Carte des confluences"))
    res.extra["orders"] = orders
    res.method = (
        "Prétraitement : {}. Le comblement applique le Priority-Flood (Barnes et al. 2014) au graphe des "
        "bassins de dépression (résultat identique au Priority-Flood cellule par cellule, vérifié par test). "
        "Option « limitée en profondeur » : une dépression dont le comblement dépasserait la profondeur "
        "maximale reste un puits naturel.\n"
        "Zones planes : drainées vers le point de sortie le plus proche (parcours en largeur sur les cellules de "
        "même altitude).\n"
        "Directions : D8 (plus grande pente vers l'un des 8 voisins, distance diagonale prise en compte). "
        "Accumulation : {} ; tri topologique (Kahn) garantissant la conservation des volumes.\n"
        "Réseau : cellules dont l'accumulation D8 atteint le seuil ; ordres de Strahler (1957) et de "
        "Shreve (1966) ; tronçons entre confluences. Longueur d'écoulement : cumul des pas D8 vers l'aval ou "
        "plus long chemin depuis l'amont. Indice de convergence : Köthe & Lehmeier (1996). Zones de "
        "concentration : quantiles du logarithme de l'aire drainée.".format(
            FILL_LABELS[p["fill"]], FLOW_LABELS[p["flow"]]))
    res.limits = (
        "Le réseau extrait dépend du seuil d'accumulation : comparez-le à une source indépendante (cartes, "
        "imagerie). Sur un MNS, les ponts, digues et forêts créent de faux barrages. Le comblement supprime "
        "toutes les dépressions, y compris naturelles (mares, cuvettes) : utilisez l'option limitée en "
        "profondeur ou aucune correction si elles comptent. La densité de drainage calculée sur l'emprise du "
        "MNT n'est pas celle d'un bassin.")
    fb.progress(100)
    return res
