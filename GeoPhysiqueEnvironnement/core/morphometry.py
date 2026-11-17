# -*- coding: utf-8 -*-
"""Paramètres morphométriques des bassins et sous-bassins versants.

Chaque champ est décrit dans FIELDS : clé, libellé, unité, nature (mesuré,
dérivé ou estimé) et formule. Les surfaces et longueurs proviennent du
raster (comptage de cellules) et des polygones issus de sa vectorisation.
"""
import math

import numpy as np
from scipy import ndimage

from .hydrology import step_lengths, trace_main_channel

# (clé, libellé, unité, nature, formule / méthode)
FIELDS = [
    ("id", "Identifiant", "", "mesuré", "Identifiant du bassin"),
    ("aire_km2", "Superficie", "km²", "mesuré", "Nombre de cellules × aire d'une cellule"),
    ("perim_km", "Périmètre", "km", "mesuré",
     "Contour du polygone simplifié (Douglas-Peucker, tolérance = 1 cellule) pour atténuer l'effet d'escalier"),
    ("perim_brut_km", "Périmètre brut", "km", "mesuré", "Contour du polygone vectorisé sans simplification"),
    ("long_km", "Longueur du bassin", "km", "mesuré",
     "Distance maximale en ligne droite entre l'exutoire et une cellule du bassin"),
    ("larg_moy_km", "Largeur moyenne", "km", "dérivé", "A / Lb"),
    ("z_min", "Altitude minimale", "m", "mesuré", "Minimum du MNT dans le bassin"),
    ("z_max", "Altitude maximale", "m", "mesuré", "Maximum du MNT dans le bassin"),
    ("z_moy", "Altitude moyenne", "m", "mesuré", "Moyenne du MNT dans le bassin"),
    ("denivele_m", "Dénivelé total", "m", "dérivé", "H = z_max - z_min"),
    ("kc_gravelius", "Coefficient de compacité de Gravelius", "", "dérivé", "Kc = P / (2 √(π A))"),
    ("rf_forme", "Facteur de forme (Horton)", "", "dérivé", "Rf = A / Lb²"),
    ("re_allong", "Rapport d'allongement (Schumm)", "", "dérivé", "Re = 2 √(A / π) / Lb"),
    ("rc_circul", "Rapport de circularité (Miller)", "", "dérivé", "Rc = 4 π A / P²"),
    ("pente_min", "Pente minimale", "°", "mesuré", "Minimum de la pente (Horn) dans le bassin"),
    ("pente_max", "Pente maximale", "°", "mesuré", "Maximum de la pente dans le bassin"),
    ("pente_moy", "Pente moyenne", "°", "mesuré", "Moyenne de la pente dans le bassin"),
    ("relief_rel", "Relief relatif (Melton)", "", "dérivé", "H / P (même unité)"),
    ("rapport_relief", "Rapport de relief (Schumm)", "", "dérivé", "Rh = H / Lb"),
    ("ruggedness", "Rugosité (ruggedness number)", "", "dérivé", "Rn = H (km) × Dd (km/km²)"),
    ("melton", "Indice de Melton", "", "dérivé", "MRN = H (km) / √A (km²)"),
    ("integ_hyps", "Intégrale hypsométrique", "", "dérivé", "HI = (z_moy - z_min) / (z_max - z_min) (Pike & Wilson 1971)"),
    ("long_reseau_km", "Longueur totale du réseau", "km", "mesuré", "Somme des longueurs D8 des cellules du réseau"),
    ("dens_drain", "Densité de drainage", "km/km²", "dérivé", "Dd = L / A"),
    ("nb_cours_eau", "Nombre de cours d'eau (Strahler)", "", "mesuré", "Σ Nu, segments de même ordre"),
    ("freq_cours_eau", "Fréquence des cours d'eau", "1/km²", "dérivé", "Fs = Σ Nu / A"),
    ("strahler_max", "Ordre maximal de Strahler", "", "mesuré", "Strahler (1957)"),
    ("shreve", "Magnitude de Shreve", "", "mesuré", "Nombre de sources du réseau (Shreve 1966)"),
    ("rb_bifurc", "Rapport de bifurcation moyen", "", "dérivé", "Moyenne de Nu / Nu+1 (Horton 1945)"),
    ("lcp_km", "Longueur du cours d'eau principal", "km", "mesuré",
     "Plus long chemin d'écoulement D8 de la ligne de partage à l'exutoire"),
    ("pente_lcp", "Pente du cours d'eau principal", "m/m", "dérivé", "(z amont - z exutoire) / longueur"),
    ("tc_kirpich_min", "Temps de concentration (Kirpich)", "min", "estimé",
     "Tc = 0,0195 L^0,77 S^-0,385 (L en m, S en m/m) ; formule empirique"),
    ("tc_giandotti_h", "Temps de concentration (Giandotti)", "h", "estimé",
     "Tc = (4 √A + 1,5 L) / (0,8 √(z_moy - z_min)) (A en km², L en km) ; formule empirique"),
    ("exutoire_x", "Exutoire X", "unités du SCR", "mesuré", "Centre de la cellule exutoire"),
    ("exutoire_y", "Exutoire Y", "unités du SCR", "mesuré", "Centre de la cellule exutoire"),
    ("touche_bord", "Touche le bord du MNT", "0/1", "mesuré",
     "1 si le bassin contient des cellules de bord : délimitation probablement incomplète"),
]

FIELD_LABELS = {k: (lab, unit, nature, formula) for k, lab, unit, nature, formula in FIELDS}


def _safe(a, b):
    try:
        if b is None or b != b or b == 0:
            return float("nan")
        return float(a) / float(b)
    except (TypeError, ZeroDivisionError):
        return float("nan")


def basin_parameters(grid, model, labels, ids, outlets, geoms, slope_deg, net=None,
                     ufl_local=None, edge=None, z=None):
    """Calcule les paramètres de chaque label `ids` (labels à plat).

    outlets : dict id → indice de la cellule exutoire.
    geoms   : dict id → géométrie OGR (polygone du bassin).
    z       : altitudes à plat (MNT d'origine, non comblé).
    Renvoie (lignes, chemins principaux), où chemins = dict id → indices.
    """
    nc = grid.ncols
    dx, dy = grid.dx, grid.dy
    lab = labels
    ids = [int(i) for i in ids]
    zf = grid.z.ravel() if z is None else z
    sl = slope_deg.ravel()
    lab2 = lab.reshape(grid.z.shape)
    idx_arr = np.array(ids)
    zmin = ndimage.minimum(zf.reshape(lab2.shape), lab2, idx_arr)
    zmax = ndimage.maximum(zf.reshape(lab2.shape), lab2, idx_arr)
    zmean = ndimage.mean(zf.reshape(lab2.shape), lab2, idx_arr)
    smin = ndimage.minimum(sl.reshape(lab2.shape), lab2, idx_arr)
    smax = ndimage.maximum(sl.reshape(lab2.shape), lab2, idx_arr)
    smean = ndimage.mean(sl.reshape(lab2.shape), lab2, idx_arr)
    cnt = np.bincount(lab, minlength=max(ids) + 1 if ids else 1)

    # distance maximale exutoire → cellule
    inside = np.flatnonzero(lab > 0)
    li = lab[inside]
    o = np.argsort(li, kind="stable")
    inside, li = inside[o], li[o]
    cuts = np.flatnonzero(np.diff(li)) + 1
    groups = {int(g_lab[0]): g for g, g_lab in zip(np.split(inside, cuts), np.split(li, cuts)) if g.size}

    # réseau
    stream_len = {}
    n_by_order = {}
    max_order = {}
    shreve = {}
    if net is not None:
        s = np.flatnonzero(net.mask & (lab > 0))
        r = model.rec[s]
        ok = (r >= 0)
        ok[ok] = lab[r[ok]] == lab[s[ok]]
        seglen = np.zeros(s.size)
        seglen[ok] = step_lengths(s[ok], r[ok], nc, dx, dy)
        tot = np.bincount(lab[s], weights=seglen, minlength=cnt.size)
        mo = np.zeros(cnt.size, np.int64)
        np.maximum.at(mo, lab[s], net.strahler[s].astype(np.int64))
        src = np.bincount(lab[s], weights=net.sources[s], minlength=cnt.size)
        st = s[net.order_start[s]]
        for i in ids:
            stream_len[i] = tot[i]
            max_order[i] = int(mo[i])
            shreve[i] = int(src[i])
        if st.size:
            keys = lab[st] * 100 + net.strahler[st]
            u, c = np.unique(keys, return_counts=True)
            for k, v in zip(u, c):
                n_by_order.setdefault(int(k // 100), {})[int(k % 100)] = int(v)

    edge_f = edge.ravel() if edge is not None else None
    rows, paths = [], {}
    for j, i in enumerate(ids):
        out_idx = int(outlets[i])
        ox, oy = grid.rc_to_xy(out_idx // nc, out_idx % nc)
        g = groups.get(i, np.array([out_idx]))
        gx, gy = grid.rc_to_xy(g // nc, g % nc)
        lb = float(np.max(np.hypot(gx - ox, gy - oy))) + 0.5 * math.hypot(dx, dy)
        area = float(cnt[i]) * dx * dy
        geom = geoms.get(i)
        if geom is not None:
            from .vector_io import polygon_perimeter
            per_raw = polygon_perimeter(geom)
            per = polygon_perimeter(geom.SimplifyPreserveTopology(max(dx, dy)))
        else:
            per_raw = per = float("nan")
        A = area / 1e6
        P = per / 1000.0
        Lb = lb / 1000.0
        H = float(zmax[j] - zmin[j])
        L_net = stream_len.get(i, 0.0) / 1000.0
        Dd = _safe(L_net, A)
        orders = n_by_order.get(i, {})
        n_streams = sum(orders.values())
        ratios = [orders[u] / orders[u + 1] for u in sorted(orders) if orders.get(u + 1)]
        rb = float(np.mean(ratios)) if ratios else float("nan")
        # cours d'eau principal
        lcp = slope_lcp = float("nan")
        if ufl_local is not None:
            path = trace_main_channel(model, out_idx, lab, ufl_local)
            paths[i] = path
            lcp = float(ufl_local[out_idx])
            if lcp > 0:
                slope_lcp = (zf[path[0]] - zf[out_idx]) / lcp
        tc_k = tc_g = float("nan")
        if lcp > 0 and slope_lcp > 0:
            tc_k = 0.0195 * lcp ** 0.77 * slope_lcp ** -0.385
        if lcp > 0 and zmean[j] - zmin[j] > 0:
            tc_g = (4 * math.sqrt(A) + 1.5 * lcp / 1000.0) / (0.8 * math.sqrt(zmean[j] - zmin[j]))
        touche = 0
        if edge_f is not None:
            e = g[edge_f[g]]
            touche = int(np.any(e != out_idx))
        rows.append({
            "id": i, "aire_km2": A, "perim_km": P, "perim_brut_km": per_raw / 1000.0,
            "long_km": Lb, "larg_moy_km": _safe(A, Lb),
            "z_min": float(zmin[j]), "z_max": float(zmax[j]), "z_moy": float(zmean[j]),
            "denivele_m": H,
            "kc_gravelius": _safe(P, 2 * math.sqrt(math.pi * A)),
            "rf_forme": _safe(A, Lb * Lb),
            "re_allong": _safe(2 * math.sqrt(A / math.pi), Lb),
            "rc_circul": _safe(4 * math.pi * A, P * P),
            "pente_min": float(smin[j]), "pente_max": float(smax[j]), "pente_moy": float(smean[j]),
            "relief_rel": _safe(H, per), "rapport_relief": _safe(H, lb),
            "ruggedness": H / 1000.0 * Dd if Dd == Dd else float("nan"),
            "melton": _safe(H / 1000.0, math.sqrt(A)),
            "integ_hyps": _safe(float(zmean[j] - zmin[j]), H),
            "long_reseau_km": L_net, "dens_drain": Dd,
            "nb_cours_eau": n_streams, "freq_cours_eau": _safe(n_streams, A),
            "strahler_max": max_order.get(i, 0), "shreve": shreve.get(i, 0),
            "rb_bifurc": rb, "lcp_km": lcp / 1000.0 if lcp == lcp else float("nan"),
            "pente_lcp": slope_lcp, "tc_kirpich_min": tc_k, "tc_giandotti_h": tc_g,
            "exutoire_x": float(ox), "exutoire_y": float(oy), "touche_bord": touche,
            "_n_par_ordre": orders,
        })
    return rows, paths
