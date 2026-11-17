# -*- coding: utf-8 -*-
"""Module d'analyse des courbures et de la géomorphologie."""
import os

import numpy as np

from ..core import terrain as T, geomorph as GM
from ..core.grid import write_raster
from ..engines import charts, styles as S
from ..engines.results import LayerSpec, Table
from ..engines.statistics import describe_table, class_table
from .common import new_result, check_grid

DEFAULTS = {
    "curvatures": list(GM.CURVATURE_NAMES),
    "products": ["forms", "slope_forms", "wood", "weiss", "position", "ridges", "breaks"],
    "zfactor": 1.0, "scale_m": None, "tol_mode": "auto", "tol_factor": 0.5, "tol_value": 0.0001,
    "tpi_small_m": 300.0, "tpi_large_m": 2000.0, "flat_slope_deg": 5.0, "wood_slope_tol": 1.0,
}

MAP_KEYS = {"general": "courbures", "profile": "courbure_profil", "plan": "courbure_plan"}


def run(params, ctx, fb):
    p = dict(DEFAULTS, **params)
    prods = set(p["products"])
    grid = ctx.grid(p["dem_path"], p.get("band", 1))
    res = new_result("geomorphologie", "Analyse des courbures et géomorphologie", grid, p["zfactor"])
    check_grid(grid, res)
    out = ctx.module_dir("geomorphologie")
    res.folder = out
    z, dx, dy, zf = grid.z, grid.dx, grid.dy, p["zfactor"]
    ca = grid.cell_area
    scale = T.window_cells(p["scale_m"], dx, minimum=1) if p.get("scale_m") else 1
    res.add_param("Échelle d'analyse (lissage)", "{} × {} cellules{}".format(
        scale, scale, "" if scale > 1 else " (dérivées 3 × 3 sans lissage)"))
    need = set(p["curvatures"])
    if prods & {"forms"}:
        need.add("general")
    if prods & {"slope_forms", "breaks"}:
        need |= {"profile", "plan"}
    if "wood" in prods:
        need |= {"cross", "minimum", "maximum"}
    if "ridges" in prods:
        need.add("plan")
    fb.info("Calcul des courbures…")
    cv = GM.curvatures(z, dx, dy, zf, scale, sorted(need))
    fb.progress(30)

    def tol_of(a):
        if p["tol_mode"] == "value":
            return float(p["tol_value"])
        return GM.auto_tolerance(a, p["tol_factor"])

    tols = {k: tol_of(a) for k, a in cv.items()}
    res.add_param("Seuil de planéité", "automatique : {} × écart-type robuste".format(p["tol_factor"])
                  if p["tol_mode"] == "auto" else "{:g}".format(p["tol_value"]), "1/m")
    stats = []
    for key in p["curvatures"]:
        a = cv[key]
        name = GM.CURVATURE_NAMES[key]
        stats.append((name, a, "1/m"))
        pth = write_raster(os.path.join(out, "courbure_{}.tif".format(key)), a, grid)
        res.add_layer(LayerSpec(pth, name, style=S.ramp_style(a, "divergent", "diverging", 5, "1/m", fmt="{:.2e}"),
                                map_key=MAP_KEYS.get(key, "courbure_" + key),
                                map_title="Carte de la " + name.lower(), units="1/m",
                                visible=key == "general"))
        sc = GM.sign_classes(a, tols[key])
        tab = class_table("{} : concave / plane / convexe".format(name), sc, GM.SIGN_LABELS, ca)
        tab.note = "Seuil de planéité : ±{:.3e} 1/m".format(tols[key])
        res.add_table(tab)
    res.add_table(describe_table("Statistiques des courbures", stats, ca))
    fb.check()
    fb.progress(50)
    slp = T.slope(z, dx, dy, zf)

    if "forms" in prods:
        sc = GM.sign_classes(cv["general"], tols["general"])
        pth = write_raster(os.path.join(out, "formes_concave_convexe.tif"), sc, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Surfaces concaves, planes et convexes",
                                style=S.classes_style(GM.SIGN_LABELS, S.FORM_COLORS),
                                map_key="formes", map_title="Carte des zones concaves et convexes"))
        tab = class_table("Surfaces concaves, planes et convexes (courbure générale)", sc, GM.SIGN_LABELS, ca)
        res.add_table(tab)
        for row in tab.rows:
            res.add_summary("Cellules {}s".format(row[1].lower()), row[2], "")
            res.add_summary("Superficie {}".format(row[1].lower()), row[3], "km²")
            res.add_summary("Part {}".format(row[1].lower()), row[4], "%")
    if "slope_forms" in prods:
        sf = GM.slope_forms(cv["profile"], cv["plan"], tols["profile"], tols["plan"])
        sf[slp < p["wood_slope_tol"]] = 0
        tab = class_table("Formes de versant (profil × plan, Dikau 1989)", sf, GM.SLOPE_FORM_LABELS, ca)
        tab.note = "Cellules de pente < {:g}° non classées (versant indéfini).".format(p["wood_slope_tol"])
        res.add_table(tab)
        cols = ["#08306b", "#2171b5", "#6baed6", "#41ab5d", "#f0f0f0", "#fdae6b", "#fb6a4a", "#cb181d", "#67000d"]
        pth = write_raster(os.path.join(out, "formes_versants.tif"), sf, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Formes de versant", style=S.classes_style(GM.SLOPE_FORM_LABELS, cols),
                                map_key="formes_versants", map_title="Carte des versants concaves, convexes et rectilignes"))
    fb.progress(65)
    if "wood" in prods:
        tol_w = max(tols["minimum"], tols["maximum"])
        wf = GM.wood_features(slp, cv["cross"], cv["minimum"], cv["maximum"], p["wood_slope_tol"], tol_w)
        tab = class_table("Éléments morphométriques (Wood 1996)", wf, GM.WOOD_LABELS, ca)
        res.add_table(tab)
        pth = write_raster(os.path.join(out, "elements_wood.tif"), wf, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Sommets, crêtes, cols, talwegs, dépressions",
                                style=S.classes_style(GM.WOOD_LABELS, ["#f0f0f0", "#67000d", "#ef3b2c", "#fdae6b",
                                                                       "#2171b5", "#08306b"]),
                                map_key="elements_wood", map_title="Carte des éléments morphométriques (Wood)"))
        res.add_param("Tolérance de pente (Wood)", p["wood_slope_tol"], "°")
    if "weiss" in prods:
        rs = max(1, int(round(p["tpi_small_m"] / dx)))
        rl = max(rs + 1, int(round(p["tpi_large_m"] / dx)))
        lf = GM.weiss_landforms(z * zf, dx, dy, rs, rl, p["flat_slope_deg"])
        tab = class_table("Unités géomorphologiques (Weiss 2001)", lf, GM.WEISS_LABELS, ca)
        res.add_table(tab)
        cols = ["#08306b", "#2171b5", "#6baed6", "#41ab5d", "#d9f0a3", "#fee391", "#fe9929",
                "#ec7014", "#cc4c02", "#662506"]
        pth = write_raster(os.path.join(out, "unites_geomorphologiques.tif"), lf, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Unités géomorphologiques", style=S.classes_style(GM.WEISS_LABELS, cols),
                                map_key="unites", map_title="Carte des unités géomorphologiques"))
        res.add_param("Rayons du TPI (petite / grande échelle)",
                      "{:g} m / {:g} m".format(p["tpi_small_m"], p["tpi_large_m"]))
        res.charts += charts.bars(GM.WEISS_LABELS, [r[4] for r in tab.rows], os.path.join(out, "unites_geomorphologiques"),
                                  "Unités géomorphologiques", "Part de la surface (%)", colors=cols)
    if "position" in prods:
        rs = max(1, int(round(p["tpi_small_m"] / dx)))
        sp = GM.slope_position(z * zf, dx, dy, rs, p["flat_slope_deg"])
        res.add_table(class_table("Position sur le versant (Weiss 2001)", sp, GM.SLOPE_POSITION_LABELS, ca))
        pth = write_raster(os.path.join(out, "position_versant.tif"), sp, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Position sur le versant",
                                style=S.classes_style(GM.SLOPE_POSITION_LABELS,
                                                      ["#7f2704", "#d94801", "#fdae6b", "#ffffbf", "#74c476", "#2171b5"]),
                                map_key="position_versant", map_title="Carte des positions de versant",
                                visible=False))
    fb.progress(85)
    if "ridges" in prods:
        rs = max(1, int(round(p["tpi_small_m"] / dx)))
        rt = GM.ridges_thalwegs(z * zf, dx, dy, rs, cv["plan"], tols["plan"])
        labels = ["Talweg", "Crête"]
        res.add_table(class_table("Crêtes et talwegs", rt, labels, ca))
        pth = write_raster(os.path.join(out, "cretes_talwegs.tif"), rt, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Crêtes et talwegs", style=S.classes_style(labels, ["#2171b5", "#a50f15"]),
                                map_key="cretes", map_title="Carte des crêtes et talwegs"))
    if "breaks" in prods:
        tol_b = 2.0 * GM.auto_tolerance(cv["profile"], 1.0) if p["tol_mode"] == "auto" else float(p["tol_value"])
        br = GM.slope_breaks(cv["profile"], slp, tol_b)
        labels = ["Rupture concave", "Rupture convexe"]
        res.add_table(class_table("Ruptures de pente (courbure de profil)", br, labels, ca))
        pth = write_raster(os.path.join(out, "ruptures_pente.tif"), br, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Ruptures de pente", style=S.classes_style(labels, ["#2166ac", "#b2182b"]),
                                map_key="ruptures", map_title="Carte des ruptures de pente", visible=False))
    if "general" in cv:
        res.charts += charts.histogram(cv["general"], os.path.join(out, "histogramme_courbure_generale"),
                                       "Distribution de la courbure générale", "Courbure (1/m)", color="#6a51a3")
    res.method = (
        "Dérivées : polynôme d'Evans-Young sur 3 × 3 (Florinsky 2016), après lissage moyen à l'échelle choisie.\n"
        "Courbure générale = -(r + t) ; profil kv = -(p²r + 2pqs + q²t) / ((p² + q²)(1 + p² + q²)^1,5) ; "
        "plan kp = -(q²r - 2pqs + p²t) / (p² + q²)^1,5 ; longitudinale et transversale selon Wood (1996) ; "
        "minimale et maximale : H ∓ √(H² - K) avec H moyenne et K gaussienne. Signe positif = convexe.\n"
        "Concave / plane / convexe : seuil de planéité ± tolérance.\n"
        "Formes de versant : croisement profil × plan (Dikau 1989), 9 classes.\n"
        "Sommets, crêtes, cols, talwegs, dépressions, plans : classification de Wood (1996) "
        "à partir de la pente et des courbures transversale, minimale et maximale.\n"
        "Unités géomorphologiques : TPI standardisé à deux échelles et pente (Weiss 2001), 10 classes ; "
        "position de versant : 6 classes.\n"
        "Crêtes : TPI > +1 écart-type et courbure planaire divergente ; talwegs : TPI < -1 écart-type et "
        "courbure planaire convergente.")
    res.limits = (
        "Les courbures sont très sensibles au bruit du MNT et à la résolution : sur un MNS (Copernicus, "
        "SRTM), utilisez une échelle d'analyse supérieure à 3 cellules. Les seuils automatiques dépendent de "
        "la distribution des valeurs de la zone : ils ne sont pas transposables d'une zone à l'autre. "
        "Les classifications de Weiss et de Wood sont des aides à l'interprétation, à valider sur le terrain.")
    fb.progress(100)
    return res
