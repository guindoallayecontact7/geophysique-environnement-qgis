# -*- coding: utf-8 -*-
"""Profils topographiques et hydrographiques le long d'une polyligne."""
import math

import numpy as np


def densify(xs, ys, step):
    """Points régulièrement espacés de `step` le long de la polyligne (sommets conservés)."""
    px, py, pd = [xs[0]], [ys[0]], [0.0]
    total = 0.0
    for i in range(1, len(xs)):
        x0, y0, x1, y1 = xs[i - 1], ys[i - 1], xs[i], ys[i]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        n = max(1, int(math.ceil(seg / step)))
        for k in range(1, n + 1):
            t = k / n
            px.append(x0 + t * (x1 - x0))
            py.append(y0 + t * (y1 - y0))
            pd.append(total + t * seg)
        total += seg
    return np.array(px), np.array(py), np.array(pd)


def sample_bilinear(grid, xs, ys):
    """Interpolation bilinéaire du MNT aux points (NaN hors grille ou NoData)."""
    z = grid.z
    col = (xs - grid.gt[0]) / grid.gt[1] - 0.5
    row = (ys - grid.gt[3]) / grid.gt[5] - 0.5
    c0 = np.floor(col).astype(int)
    r0 = np.floor(row).astype(int)
    fc, fr = col - c0, row - r0
    out = np.full(xs.shape, np.nan)
    for i in range(xs.size):
        r, c = r0[i], c0[i]
        rr = [min(max(r, 0), grid.nrows - 1), min(max(r + 1, 0), grid.nrows - 1)]
        cc = [min(max(c, 0), grid.ncols - 1), min(max(c + 1, 0), grid.ncols - 1)]
        if not (-1 <= r < grid.nrows and -1 <= c < grid.ncols):
            continue
        v = np.array([[z[rr[0], cc[0]], z[rr[0], cc[1]]], [z[rr[1], cc[0]], z[rr[1], cc[1]]]])
        if np.isnan(v).any():
            finite = v[np.isfinite(v)]
            out[i] = finite.mean() if finite.size else np.nan
            continue
        a = v[0, 0] * (1 - fc[i]) + v[0, 1] * fc[i]
        b = v[1, 0] * (1 - fc[i]) + v[1, 1] * fc[i]
        out[i] = a * (1 - fr[i]) + b * fr[i]
    return out


def _smooth(values, n):
    if n <= 1:
        return values.copy()
    k = np.ones(n) / n
    pad = n // 2
    v = np.pad(values, pad, mode="edge")
    return np.convolve(v, k, mode="valid")[:values.size]


def analyse_profile(dist, z, smooth_n=5, curv_tol=None, break_tol_deg=None):
    """Pentes locales, courbure du profil, segments concaves/convexes et ruptures de pente.

    - pente locale (%) : dérivée centrée de z lissé (moyenne mobile de `smooth_n` points) ;
    - courbure (1/m) : dérivée seconde de z lissé ; > 0 convexe, < 0 concave
      (même convention que les courbures raster) ;
    - ruptures : changements de pente (en degrés) entre segments de part et
      d'autre d'un point, maxima locaux supérieurs à `break_tol_deg`.
      Par défaut, le seuil vaut 2 écarts-types des changements de pente.
    """
    ok = np.isfinite(z)
    d = dist[ok]
    zz = z[ok]
    res = {"distance": d, "z": zz}
    if d.size < 3:
        res.update(slope_pct=np.full(d.size, np.nan), curvature=np.full(d.size, np.nan),
                   form=np.zeros(d.size, int), breaks=np.array([], int), stats={})
        return res
    zs = _smooth(zz, smooth_n)
    g = np.gradient(zs, d)
    # -z'' : positif pour une forme convexe (bombée), quel que soit le sens du profil.
    curv = -np.gradient(g, d)
    tol = curv_tol if curv_tol is not None else 0.5 * float(np.nanstd(curv))
    form = np.where(curv > tol, 1, np.where(curv < -tol, -1, 0))
    ang = np.degrees(np.arctan(g))
    w = max(2, smooth_n)
    change = np.full(d.size, 0.0)
    for i in range(w, d.size - w):
        change[i] = abs(np.mean(ang[i:i + w]) - np.mean(ang[i - w:i]))
    bt = break_tol_deg if break_tol_deg is not None else max(1.0, 2.0 * float(np.std(change)))
    breaks = [i for i in range(1, d.size - 1)
              if change[i] >= bt and change[i] >= change[i - 1] and change[i] > change[i + 1]]
    length = float(d[-1] - d[0])
    stats = {
        "longueur_m": length,
        "z_min": float(np.min(zz)), "z_max": float(np.max(zz)),
        "z_debut": float(zz[0]), "z_fin": float(zz[-1]),
        "denivele_m": float(np.max(zz) - np.min(zz)),
        "denivele_debut_fin_m": float(zz[0] - zz[-1]),
        "pente_moy_pct": float(np.mean(np.abs(g)) * 100.0),
        "pente_globale_pct": float(abs(zz[-1] - zz[0]) / length * 100.0) if length > 0 else float("nan"),
        "pente_max_pct": float(np.max(np.abs(g)) * 100.0),
        "denivele_cumule_positif_m": float(np.sum(np.clip(np.diff(zz), 0, None))),
        "denivele_cumule_negatif_m": float(-np.sum(np.clip(np.diff(zz), None, 0))),
        "part_convexe_pct": float(np.mean(form == 1) * 100.0),
        "part_concave_pct": float(np.mean(form == -1) * 100.0),
        "part_rectiligne_pct": float(np.mean(form == 0) * 100.0),
        "nb_ruptures": len(breaks),
        "seuil_courbure": tol, "seuil_rupture_deg": bt,
    }
    res.update(slope_pct=g * 100.0, curvature=curv, form=form, breaks=np.array(breaks, int),
               slope_change_deg=change, stats=stats)
    return res


def segments(form, dist):
    """Regroupe les points consécutifs de même forme : liste de (forme, d_début, d_fin)."""
    out = []
    if form.size == 0:
        return out
    start = 0
    for i in range(1, form.size + 1):
        if i == form.size or form[i] != form[start]:
            out.append((int(form[start]), float(dist[start]), float(dist[i - 1])))
            start = i
    return out
