# -*- coding: utf-8 -*-
"""Module d'analyse morphométrique : indices de terrain."""
import math
import os

import numpy as np

from ..core import terrain as T, geomorph as GM, hydrology as hy
from ..core.grid import write_raster
from ..engines import charts, styles as S
from ..engines.results import LayerSpec
from ..engines.statistics import describe_table, class_table
from .common import new_result, check_grid, ensure_hydro

DEFAULTS = {
    "indices": ["tpi", "tri", "vrm", "rsp", "twi", "spi", "ls", "hi", "dissection", "units"],
    "zfactor": 1.0, "tpi_radius_m": 300.0, "vrm_window_m": 90.0, "rsp_window_m": 1000.0,
    "hi_window_m": 1000.0, "dissection_window_m": 1000.0,
    "flow": "mfd", "mfd_exponent": 1.1, "fill": "fill", "max_depth": None,
    "ls_m": 0.4, "ls_n": 1.3, "min_tan": 0.001, "flat_slope_deg": 5.0,
}

LABELS = {
    "tpi": ("TPI", "m"), "tri": ("TRI (Riley)", "m"), "vrm": ("VRM", ""), "rsp": ("Position relative (RSP fenêtrée)", ""),
    "twi": ("TWI", ""), "spi": ("SPI (ln)", ""), "ls": ("Facteur LS", ""), "hi": ("Intégrale hypsométrique locale", ""),
    "dissection": ("Indice de dissection", ""),
}


def specific_catchment_area(grid, ctx, p, fb):
    """Aire drainée spécifique a = A / largeur de contour (m²/m), selon la méthode choisie."""
    st = ensure_hydro(ctx, grid, p, fb, (5, 40))
    method = p["flow"]
    fb.info("Accumulation {} pour les indices hydrologiques…".format(method.upper()))
    if method == "d8":
        acc = st.acc_d8
    elif method == "dinf":
        acc = hy.accumulate_dinf(st.model, feedback=fb)
    else:
        acc = hy.accumulate_mfd(st.model, p["mfd_exponent"], feedback=fb)
    return acc * grid.dx * grid.dy / grid.dx  # largeur de contour = taille de cellule


def run(params, ctx, fb):
    p = dict(DEFAULTS, **params)
    idx = set(p["indices"])
    grid = ctx.grid(p["dem_path"], p.get("band", 1))
    res = new_result("morphometrie", "Analyse morphométrique", grid, p["zfactor"])
    check_grid(grid, res)
    out = ctx.module_dir("morphometrie")
    res.folder = out
    z, dx, dy, zf = grid.z, grid.dx, grid.dy, p["zfactor"]
    ca = grid.cell_area
    arrays = []
    slp = T.slope(z, dx, dy, zf)
    beta = np.radians(slp)

    def add(key, arr, ramp, mode="p2p98", map_key=None, title=None, fmt="{:.2f}"):
        lab, unit = LABELS[key]
        arrays.append((lab, arr, unit))
        pth = write_raster(os.path.join(out, "{}.tif".format(key)), arr, grid)
        res.add_layer(LayerSpec(pth, lab, style=S.ramp_style(arr, ramp, mode, 5, unit, fmt=fmt),
                                map_key=map_key or key, map_title=title or "Carte du {}".format(lab), units=unit))

    if "tpi" in idx or "units" in idx:
        r = max(1, int(round(p["tpi_radius_m"] / dx)))
        tp = T.tpi(z * zf, 2 * r + 1)
        if "tpi" in idx:
            add("tpi", tp, "divergent", "diverging", "tpi", "Carte du TPI")
        res.add_param("Rayon du TPI", "{:g} m ({} cellules)".format(p["tpi_radius_m"], r))
    fb.progress(10)
    if "tri" in idx:
        add("tri", T.tri_riley(z * zf), "relief", map_key="tri", title="Carte du TRI")
    if "vrm" in idx:
        w = T.window_cells(p["vrm_window_m"], dx)
        add("vrm", T.vrm(z, dx, dy, w, zf), "relief", map_key="vrm", title="Carte du VRM", fmt="{:.4f}")
        res.add_param("Fenêtre du VRM", "{} × {} cellules".format(w, w))
    if "rsp" in idx:
        w = T.window_cells(p["rsp_window_m"], dx)
        add("rsp", T.relative_position(z, w), "sequentiel", "minmax", "rsp", "Carte de la position relative (RSP)")
        res.add_param("Fenêtre de la position relative", "{:g} m ({} cellules)".format(p["rsp_window_m"], w))
    if "hi" in idx:
        w = T.window_cells(p["hi_window_m"], dx)
        add("hi", T.local_hypsometric_integral(z, w), "sequentiel", "minmax", "hi_local",
            "Carte de l'intégrale hypsométrique locale")
        res.add_param("Fenêtre de l'intégrale hypsométrique", "{:g} m ({} cellules)".format(p["hi_window_m"], w))
    if "dissection" in idx:
        w = T.window_cells(p["dissection_window_m"], dx)
        add("dissection", T.dissection_index(z, w), "relief", map_key="dissection",
            title="Carte de l'indice de dissection", fmt="{:.4f}")
        res.add_param("Fenêtre de l'indice de dissection", "{:g} m ({} cellules)".format(p["dissection_window_m"], w))
    fb.check()
    fb.progress(20)

    if idx & {"twi", "spi", "ls"}:
        a = specific_catchment_area(grid, ctx, p, fb)
        tanb = np.maximum(np.tan(beta), p["min_tan"])
        res.add_param("Routage pour TWI / SPI / LS", p["flow"].upper())
        res.add_param("Tangente de pente minimale", p["min_tan"], "")
        if "twi" in idx:
            add("twi", np.log(a / tanb), "humidite", map_key="twi", title="Carte du TWI")
        if "spi" in idx:
            add("spi", np.log(a * tanb + 1e-12), "chaleur", map_key="spi", title="Carte du SPI (logarithme népérien)")
        if "ls" in idx:
            ls = (a / 22.13) ** p["ls_m"] * (np.sin(beta) / 0.0896) ** p["ls_n"]
            add("ls", ls, "chaleur", map_key="ls", title="Carte du facteur LS")
            res.add_param("Exposants LS (m, n)", "{:g}, {:g}".format(p["ls_m"], p["ls_n"]))
    fb.progress(85)

    if "units" in idx:
        r = max(1, int(round(p["tpi_radius_m"] / dx)))
        units = GM.slope_position(z * zf, dx, dy, r, p["flat_slope_deg"])
        tab = class_table("Unités morphométriques (position sur le versant)", units, GM.SLOPE_POSITION_LABELS, ca)
        res.add_table(tab)
        pth = write_raster(os.path.join(out, "unites_morphometriques.tif"), units, grid, "uint8", 0)
        res.add_layer(LayerSpec(pth, "Unités morphométriques",
                                style=S.classes_style(GM.SLOPE_POSITION_LABELS,
                                                      ["#7f2704", "#d94801", "#fdae6b", "#ffffbf", "#74c476", "#2171b5"]),
                                map_key="unites_morpho", map_title="Carte des unités morphométriques"))
        res.charts += charts.bars(GM.SLOPE_POSITION_LABELS, [r_[4] for r_ in tab.rows],
                                  os.path.join(out, "unites_morphometriques"), "Unités morphométriques",
                                  "Part de la surface (%)")
    res.add_table(describe_table("Statistiques des indices morphométriques", arrays, ca))
    for lab, arr, unit in arrays[:4]:
        res.charts += charts.histogram(arr, os.path.join(out, "histogramme_" + lab.split()[0].lower()),
                                       "Distribution : {}".format(lab), lab + (" ({})".format(unit) if unit else ""))
    res.method = (
        "TPI (Weiss 2001) : z - moyenne d'une fenêtre carrée de côté 2r+1 (centre exclu).\n"
        "TRI (Riley et al. 1999) : racine de la somme des carrés des écarts aux 8 voisins.\n"
        "VRM (Sappington et al. 2007) : 1 - |somme des vecteurs normaux unitaires| / n.\n"
        "Position relative : (z - min) / (max - min) dans la fenêtre (variante fenêtrée de la RSP).\n"
        "Intégrale hypsométrique locale : (moyenne - min) / (max - min) dans la fenêtre (Pike & Wilson 1971).\n"
        "Indice de dissection (Dov Nir 1957) : (max - min) / max dans la fenêtre.\n"
        "TWI (Beven & Kirkby 1979) : ln(a / tan β) ; SPI (Moore et al. 1991) : ln(a × tan β) ; "
        "LS (Moore & Burch 1986) : (a / 22,13)^m × (sin β / 0,0896)^n ; a = aire drainée spécifique (m²/m) "
        "issue d'un MNT comblé et du routage choisi ; tan β bornée à la valeur minimale indiquée.\n"
        "Unités morphométriques : TPI standardisé et pente (Weiss 2001), 6 positions de versant.")
    res.limits = (
        "Les indices de voisinage dépendent de la taille de fenêtre : comparez plusieurs échelles. "
        "Les indices hydrologiques (TWI, SPI, LS) héritent des limites du routage (zones planes, MNS). "
        "Le facteur LS de Moore & Burch suppose un ruissellement diffus ; il n'est pas calibré pour les ravines.")
    fb.progress(100)
    return res
