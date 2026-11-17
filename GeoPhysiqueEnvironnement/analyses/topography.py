# -*- coding: utf-8 -*-
"""Module d'analyse topographique."""
import os

import numpy as np

from ..core import terrain as T, geomorph as GM, vector_io as V
from ..core.grid import write_raster
from ..engines import charts, styles as S
from ..engines.results import LayerSpec, Table
from ..engines.statistics import describe, describe_table, class_table
from .common import new_result, check_grid

DEFAULTS = {
    "products": ["stats", "hypso", "slope_deg", "slope_pct", "slope_classes", "slope_zones", "aspect",
                 "hillshade", "multihillshade", "contours", "relief", "roughness", "breaks"],
    "zfactor": 1.0, "hypso_n": 8, "hypso_method": "equal",
    "hs_azimuth": 315.0, "hs_altitude": 45.0,
    "contour_interval": None, "contour_master": 5,
    "relief_window_m": 500.0,
    "slope_breaks": list(T.FAO_SLOPE_BREAKS),
    "zone_low": 5.0, "zone_high": 15.0,
    "break_factor": 1.0,
}


def suggest_contour_interval(zmin, zmax):
    """Équidistance « ronde » donnant environ 20 à 50 courbes sur le dénivelé."""
    rng = max(zmax - zmin, 1e-6)
    for step in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500):
        if rng / step <= 50:
            return float(step)
    return 1000.0


def run(params, ctx, fb):
    p = dict(DEFAULTS, **params)
    prods = set(p["products"])
    grid = ctx.grid(p["dem_path"], p.get("band", 1))
    res = new_result("topographie", "Analyse topographique", grid, p["zfactor"])
    check_grid(grid, res)
    out = ctx.module_dir("topographie")
    res.folder = out
    z, dx, dy, zf = grid.z, grid.dx, grid.dy, p["zfactor"]
    valid = grid.valid
    ca = grid.cell_area
    zv = z[valid]
    zmin, zmax = float(zv.min()), float(zv.max())
    res.inputs.append(("Cellules valides", "{:,}".format(int(valid.sum())).replace(",", " ")))

    # ---- statistiques altimétriques
    d = describe(z, ca)
    res.add_summary("Altitude minimale", d["min"], "m")
    res.add_summary("Altitude maximale", d["max"], "m")
    res.add_summary("Altitude moyenne", d["moyenne"], "m")
    res.add_summary("Altitude médiane", d["mediane"], "m")
    res.add_summary("Écart-type des altitudes", d["ecart_type"], "m")
    res.add_summary("Variance des altitudes", d["variance"], "m²")
    res.add_summary("Dénivelé total", zmax - zmin, "m")
    res.add_summary("Superficie analysée", d["superficie_km2"], "km²")
    h, above, hi = T.hypsometric_curve(z)
    res.add_summary("Intégrale hypsométrique (Pike & Wilson)", hi, "")
    stats_arrays = [("Altitude", z, "m")]
    fb.progress(5)

    # ---- hypsométrie
    if "hypso" in prods or "stats" in prods:
        brk = T.class_breaks(z, int(p["hypso_n"]), p["hypso_method"])
        cls = T.classify(z, brk)
        labels = ["{:.0f} - {:.0f} m".format(brk[i], brk[i + 1]) for i in range(len(brk) - 1)]
        tab = class_table("Distribution des classes altimétriques", cls, labels, ca)
        tab.note = "Classes {} ({} classes).".format(
            "d'effectifs égaux (quantiles)" if p["hypso_method"] == "quantile" else "d'amplitude égale",
            len(labels))
        res.add_table(tab)
        res.add_param("Classes hypsométriques", "{} ({})".format(len(labels), p["hypso_method"]))
        if "hypso" in prods:
            pth = write_raster(os.path.join(out, "classes_altimetriques.tif"), cls, grid, "uint8", 0)
            res.add_layer(LayerSpec(pth, "Classes altimétriques", style=S.classes_style(labels, ramp="hypsometrie"),
                                    map_key="hypsometrie_classes", map_title="Carte des classes altimétriques",
                                    units="m"))
            res.add_layer(LayerSpec(grid.source, "Hypsométrie (MNT)",
                                    style=S.ramp_style(z, "hypsometrie", "minmax", 9, "m", opacity=0.8, fmt="{:.0f}"),
                                    map_key="hypsometrie", map_title="Carte hypsométrique", units="m"))
        res.charts += charts.hypsometric_curve(h, above, hi, os.path.join(out, "courbe_hypsometrique"))
        res.charts += charts.histogram(z, os.path.join(out, "histogramme_altitudes"),
                                       "Distribution des altitudes", "Altitude (m)", color="#8c5a33")
    fb.check()
    fb.progress(15)

    # ---- pentes
    slp_deg = None
    if prods & {"slope_deg", "slope_pct", "slope_classes", "slope_zones", "breaks", "stats"}:
        slp_deg = T.slope(z, dx, dy, zf, "degrees")
        slp_pct = np.tan(np.radians(slp_deg)) * 100.0
        stats_arrays += [("Pente", slp_deg, "°"), ("Pente", slp_pct, "%")]
        sd = describe(slp_deg)
        res.add_summary("Pente moyenne", sd["moyenne"], "°")
        res.add_summary("Pente maximale", sd["max"], "°")
        if "slope_deg" in prods:
            pth = write_raster(os.path.join(out, "pente_degres.tif"), slp_deg, grid)
            res.add_layer(LayerSpec(pth, "Pente (°)", style=S.ramp_style(slp_deg, "pente", "p2p98", 5, "°", fmt="{:.1f}"),
                                    map_key="pentes", map_title="Carte des pentes (degrés)", units="°"))
        if "slope_pct" in prods:
            pth = write_raster(os.path.join(out, "pente_pourcent.tif"), slp_pct, grid)
            res.add_layer(LayerSpec(pth, "Pente (%)", style=S.ramp_style(slp_pct, "pente", "p2p98", 5, "%", fmt="{:.1f}"),
                                    map_key="pentes_pct", map_title="Carte des pentes (pourcentage)", units="%"))
        if "slope_classes" in prods or "stats" in prods:
            brk = [float(b) for b in p["slope_breaks"]]
            cls = T.classify_open(slp_pct, brk)
            labels = (["< {:g} %".format(brk[0])]
                      + ["{:g} - {:g} %".format(brk[i], brk[i + 1]) for i in range(len(brk) - 1)]
                      + ["> {:g} %".format(brk[-1])])
            if brk == [float(x) for x in T.FAO_SLOPE_BREAKS]:
                labels = list(T.FAO_SLOPE_LABELS)
            tab = class_table("Répartition des classes de pente", cls, labels, ca)
            tab.note = "Bornes en % : {}{}".format(", ".join("{:g}".format(b) for b in brk),
                                                    " (classes FAO 2006)" if labels == T.FAO_SLOPE_LABELS else "")
            res.add_table(tab)
            res.charts += charts.bars(labels, [r[4] for r in tab.rows], os.path.join(out, "classes_pente"),
                                      "Répartition des classes de pente", "Part de la surface (%)",
                                      colors=S.palette_colors(len(labels), "pente"))
            if "slope_classes" in prods:
                pth = write_raster(os.path.join(out, "classes_pente.tif"), cls, grid, "uint8", 0)
                res.add_layer(LayerSpec(pth, "Classes de pente", style=S.classes_style(labels, ramp="pente"),
                                        map_key="classes_pente", map_title="Carte des classes de pente", units="%"))
        if "slope_zones" in prods:
            lo, hi_ = float(p["zone_low"]), float(p["zone_high"])
            zones = T.classify_open(slp_pct, [lo, hi_])
            labels = ["Faibles pentes (< {:g} %)".format(lo), "Pentes moyennes ({:g} - {:g} %)".format(lo, hi_),
                      "Fortes pentes (> {:g} %)".format(hi_)]
            res.add_table(class_table("Zones de fortes et faibles pentes", zones, labels, ca))
            pth = write_raster(os.path.join(out, "zones_pentes.tif"), zones, grid, "uint8", 0)
            res.add_layer(LayerSpec(pth, "Zones de pente", style=S.classes_style(labels, ["#1a9641", "#ffffbf", "#d7191c"]),
                                    map_key="zones_pentes", map_title="Carte des zones de fortes et faibles pentes"))
            res.add_param("Seuils des zones de pente", "{:g} et {:g}".format(lo, hi_), "%")
        res.charts += charts.histogram(slp_deg, os.path.join(out, "histogramme_pentes"),
                                       "Distribution des pentes", "Pente (°)", color="#d7191c")
    fb.check()
    fb.progress(35)

    # ---- exposition
    if "aspect" in prods or "stats" in prods:
        asp = T.aspect(z, dx, dy, zf)
        acls = T.aspect_classes(asp)
        tab = class_table("Distribution des expositions", acls, T.ASPECT_LABELS, ca)
        res.add_table(tab)
        res.charts += charts.rose(asp, os.path.join(out, "rose_expositions"))
        if "aspect" in prods:
            pth = write_raster(os.path.join(out, "exposition_degres.tif"), asp, grid)
            res.add_layer(LayerSpec(pth, "Exposition (°)", style=S.ramp_style(asp, ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#ff0000"], "minmax", 7, "°", fmt="{:.0f}"),
                                    map_key="expositions_deg", map_title="Carte des expositions (degrés)", units="°",
                                    visible=False))
            pth = write_raster(os.path.join(out, "exposition_classes.tif"), acls, grid, "uint8", 0)
            res.add_layer(LayerSpec(pth, "Exposition (classes)", style=S.classes_style(T.ASPECT_LABELS, S.ASPECT_COLORS),
                                    map_key="expositions", map_title="Carte des expositions"))
    fb.progress(45)

    # ---- ombrages
    if "hillshade" in prods:
        hs = T.hillshade(z, dx, dy, p["hs_azimuth"], p["hs_altitude"], zf)
        pth = write_raster(os.path.join(out, "ombrage.tif"), hs, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Ombrage", style=S.gray_style(), map_key="ombrage",
                                map_title="Carte d'ombrage du relief"))
        res.add_param("Ombrage : azimut / hauteur", "{:g} / {:g}".format(p["hs_azimuth"], p["hs_altitude"]), "°")
    if "multihillshade" in prods:
        hs = T.hillshade_multidirectional(z, dx, dy, p["hs_altitude"], zf)
        pth = write_raster(os.path.join(out, "ombrage_multidirectionnel.tif"), hs, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Ombrage multidirectionnel", style=S.gray_style(), map_key="ombrage_multi",
                                map_title="Carte d'ombrage multidirectionnel"))
    fb.check()
    fb.progress(55)

    # ---- courbes de niveau
    if "contours" in prods:
        iv = p["contour_interval"] or suggest_contour_interval(zmin, zmax)
        gpkg = os.path.join(out, "courbes_niveau.gpkg")
        _, n = V.contours(grid, gpkg, "courbes_niveau", iv, 0.0, int(p["contour_master"]))
        res.add_layer(LayerSpec(gpkg, "Courbes de niveau", "vector", "courbes_niveau", {"type": "contours"},
                                map_key="courbes", map_title="Carte des courbes de niveau"))
        res.add_param("Équidistance des courbes", iv, "m")
        res.add_param("Courbe maîtresse toutes les", int(p["contour_master"]), "courbes")
        res.add_summary("Nombre de courbes de niveau (segments)", n, "")
    fb.progress(65)

    # ---- relief relatif, rugosité
    if "relief" in prods:
        w = T.window_cells(p["relief_window_m"], dx)
        rel = T.local_relief(z, w)
        stats_arrays.append(("Relief relatif", rel, "m"))
        pth = write_raster(os.path.join(out, "relief_relatif.tif"), rel, grid)
        res.add_layer(LayerSpec(pth, "Relief relatif", style=S.ramp_style(rel, "relief", "p2p98", 5, "m", fmt="{:.0f}"),
                                map_key="relief", map_title="Carte du relief relatif", units="m"))
        res.add_param("Fenêtre du relief relatif", "{:g} m ({} × {} cellules)".format(p["relief_window_m"], w, w))
    if "roughness" in prods:
        rg = T.roughness(z)
        stats_arrays.append(("Rugosité (max - min 3 × 3)", rg, "m"))
        pth = write_raster(os.path.join(out, "rugosite.tif"), rg, grid)
        res.add_layer(LayerSpec(pth, "Rugosité du terrain", style=S.ramp_style(rg, "relief", "p2p98", 5, "m"),
                                map_key="rugosite", map_title="Carte de la rugosité du terrain", units="m"))
    fb.progress(80)

    # ---- ruptures de pente
    if "breaks" in prods:
        cv = GM.curvatures(z, dx, dy, zf, 1, ["profile"])["profile"]
        tol = GM.auto_tolerance(cv, p["break_factor"] * 2.0)
        br = GM.slope_breaks(cv, slp_deg if slp_deg is not None else T.slope(z, dx, dy, zf), tol)
        labels = ["Rupture concave", "Rupture convexe"]
        res.add_table(class_table("Ruptures de pente", br, labels, ca))
        pth = write_raster(os.path.join(out, "ruptures_pente.tif"), br, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Ruptures de pente", style=S.classes_style(labels, ["#2166ac", "#b2182b"]),
                                map_key="ruptures", map_title="Carte des ruptures de pente"))
        res.add_param("Seuil de rupture (|courbure de profil|)", tol, "1/m")

    res.add_table(describe_table("Statistiques descriptives", stats_arrays, ca))
    res.method = (
        "Pente et exposition : dérivées de Horn (1981) sur une fenêtre 3 × 3, comme gdaldem. "
        "Exposition : azimut de la plus grande pente descendante, en degrés depuis le nord, -1 = plat.\n"
        "Ombrage : modèle lambertien ; ombrage multidirectionnel : 4 éclairages (225°, 270°, 315°, 360°) "
        "pondérés par sin²(exposition - azimut) (Mark 1992).\n"
        "Courbes de niveau : GDAL ContourGenerate ; une courbe sur N est marquée comme maîtresse.\n"
        "Relief relatif : altitude maximale moins altitude minimale dans une fenêtre carrée. "
        "Rugosité : écart max - min sur 3 × 3.\n"
        "Ruptures de pente : |courbure de profil| (Florinsky 2016) supérieure à 2 × l'écart-type robuste "
        "(1,4826 × MAD) de la courbure, sur les cellules de pente ≥ 0,5°.\n"
        "Courbe et intégrale hypsométriques : Strahler (1952), HI = (moy - min) / (max - min).")
    res.limits = (
        "Les altitudes sont supposées en mètres ; un MNS (Copernicus, SRTM) inclut la végétation et le bâti. "
        "Les pentes dépendent de la résolution : elles sont lissées sur les MNT grossiers. "
        "Les cellules de bord et voisines du NoData utilisent la valeur valide la plus proche.")
    fb.progress(100)
    return res
