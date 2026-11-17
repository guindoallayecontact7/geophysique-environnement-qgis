# -*- coding: utf-8 -*-
"""Analyse topographique et indices morphométriques locaux (NumPy/SciPy).

Conventions :
- p = dz/dx (vers l'est), q = dz/dy (vers le nord), en m/m.
- Exposition : azimut de la ligne de plus grande pente descendante, en degrés,
  mesuré depuis le nord dans le sens horaire ; -1 pour une cellule plane.
- Les tailles de fenêtre sont données en mètres et converties en cellules
  impaires selon la résolution du MNT.
"""
import math

import numpy as np
from scipy import ndimage

from .grid import fill_nodata_nearest

# Classes de pente FAO (2006), Guidelines for soil description, en %.
FAO_SLOPE_BREAKS = [2, 5, 10, 15, 30, 60]
FAO_SLOPE_LABELS = ["Plat (0-2 %)", "Faible (2-5 %)", "Modérée (5-10 %)", "Forte (10-15 %)",
                    "Modérément raide (15-30 %)", "Raide (30-60 %)", "Très raide (> 60 %)"]


def window_cells(size_m, dx, minimum=3):
    """Convertit une taille de fenêtre en mètres en nombre impair de cellules."""
    n = int(round(size_m / dx))
    n = max(minimum, n)
    if n % 2 == 0:
        n += 1
    return n


def _neighbours(z, zfactor=1.0):
    zp = np.pad(fill_nodata_nearest(z) * zfactor, 1, mode="edge")
    return (zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:],
            zp[1:-1, :-2], zp[1:-1, 1:-1], zp[1:-1, 2:],
            zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:])


def gradient_horn(z, dx, dy, zfactor=1.0):
    """Dérivées premières, méthode de Horn (1981), comme gdaldem."""
    z1, z2, z3, z4, _, z6, z7, z8, z9 = _neighbours(z, zfactor)
    p = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8.0 * dx)
    q = ((z1 + 2 * z2 + z3) - (z7 + 2 * z8 + z9)) / (8.0 * dy)
    nan = np.isnan(z)
    p[nan] = np.nan
    q[nan] = np.nan
    return p, q


def derivatives_evans(z, dx, dy, zfactor=1.0):
    """Dérivées premières et secondes, polynôme d'Evans-Young (Florinsky 2016)."""
    z1, z2, z3, z4, z5, z6, z7, z8, z9 = _neighbours(z, zfactor)
    p = ((z3 + z6 + z9) - (z1 + z4 + z7)) / (6.0 * dx)
    q = ((z1 + z2 + z3) - (z7 + z8 + z9)) / (6.0 * dy)
    r = ((z1 + z3 + z4 + z6 + z7 + z9) - 2.0 * (z2 + z5 + z8)) / (3.0 * dx * dx)
    t = ((z1 + z2 + z3 + z7 + z8 + z9) - 2.0 * (z4 + z5 + z6)) / (3.0 * dy * dy)
    s = (z3 + z7 - z1 - z9) / (4.0 * dx * dy)
    nan = np.isnan(z)
    for a in (p, q, r, t, s):
        a[nan] = np.nan
    return p, q, r, t, s


def slope(z, dx, dy, zfactor=1.0, unit="degrees"):
    p, q = gradient_horn(z, dx, dy, zfactor)
    g = np.hypot(p, q)
    if unit == "percent":
        return 100.0 * g
    return np.degrees(np.arctan(g))


def aspect(z, dx, dy, zfactor=1.0, flat_tol=1e-8):
    p, q = gradient_horn(z, dx, dy, zfactor)
    a = (np.degrees(np.arctan2(-p, -q)) + 360.0) % 360.0
    flat = np.hypot(p, q) < flat_tol
    a[flat] = -1.0
    a[np.isnan(z)] = np.nan
    return a


def hillshade(z, dx, dy, azimuth=315.0, altitude=45.0, zfactor=1.0):
    """Ombrage 0-255 (modèle lambertien, comme gdaldem)."""
    p, q = gradient_horn(z, dx, dy, zfactor)
    return _shade(p, q, azimuth, altitude)


def _shade(p, q, azimuth, altitude):
    g = np.hypot(p, q)
    slp = np.arctan(g)
    asp = np.arctan2(-p, -q)  # azimut descendant (rad), sens horaire depuis le nord
    zen = math.radians(90.0 - altitude)
    az = math.radians(azimuth)
    hs = math.cos(zen) * np.cos(slp) + math.sin(zen) * np.sin(slp) * np.cos(az - asp)
    return np.clip(hs, 0, 1) * 255.0


def hillshade_multidirectional(z, dx, dy, altitude=45.0, zfactor=1.0):
    """Ombrage multidirectionnel (Mark 1992, formule de gdaldem -multidirectional).

    Quatre éclairages (225°, 270°, 315°, 360°) pondérés par sin²(exposition - azimut).
    """
    p, q = gradient_horn(z, dx, dy, zfactor)
    asp = np.arctan2(-p, -q)
    total = np.zeros_like(p)
    for az in (225.0, 270.0, 315.0, 360.0):
        w = np.sin(asp - math.radians(az)) ** 2
        total += w * _shade(p, q, az, altitude)
    return total / 2.0


# --- statistiques focales tolérantes au NoData ----------------------------
def focal_mean(z, size):
    valid = ~np.isnan(z)
    num = ndimage.uniform_filter(np.where(valid, z, 0.0), size, mode="nearest")
    den = ndimage.uniform_filter(valid.astype(np.float64), size, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        m = num / den
    m[~valid] = np.nan
    return m


def focal_std(z, size):
    valid = ~np.isnan(z)
    zz = np.where(valid, z, 0.0)
    den = ndimage.uniform_filter(valid.astype(np.float64), size, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        m = ndimage.uniform_filter(zz, size, mode="nearest") / den
        m2 = ndimage.uniform_filter(zz * zz, size, mode="nearest") / den
    sd = np.sqrt(np.maximum(m2 - m * m, 0))
    sd[~valid] = np.nan
    return sd


def focal_max(z, size):
    out = ndimage.maximum_filter(np.where(np.isnan(z), -np.inf, z), size, mode="nearest")
    out[np.isnan(z)] = np.nan
    return out


def focal_min(z, size):
    out = ndimage.minimum_filter(np.where(np.isnan(z), np.inf, z), size, mode="nearest")
    out[np.isnan(z)] = np.nan
    return out


def local_relief(z, size):
    """Relief relatif local : altitude max - min dans la fenêtre (m)."""
    return focal_max(z, size) - focal_min(z, size)


def roughness(z):
    """Rugosité (gdaldem) : écart max - min dans la fenêtre 3 × 3 (m)."""
    return local_relief(z, 3)


def tri_riley(z):
    """Terrain Ruggedness Index de Riley et al. (1999) : racine de la somme des carrés des écarts (m)."""
    z1, z2, z3, z4, z5, z6, z7, z8, z9 = _neighbours(z)
    acc = np.zeros_like(z5)
    for zn in (z1, z2, z3, z4, z6, z7, z8, z9):
        acc += (zn - z5) ** 2
    out = np.sqrt(acc)
    out[np.isnan(z)] = np.nan
    return out


def tpi(z, outer, inner=0):
    """Topographic Position Index (Weiss 2001) : z - moyenne du voisinage (m).

    Fenêtre carrée de côté `outer` cellules, éventuellement en anneau (côté
    intérieur `inner`). La cellule centrale est exclue de la moyenne.
    """
    valid = ~np.isnan(z)
    zz = np.where(valid, z, 0.0)
    v = valid.astype(np.float64)

    def box_sum(a, n):
        return ndimage.uniform_filter(a, n, mode="nearest") * (n * n)

    s_out = box_sum(zz, outer)
    c_out = box_sum(v, outer)
    if inner and inner >= 1:
        s_in = box_sum(zz, inner)
        c_in = box_sum(v, inner)
    else:
        s_in, c_in = zz, v
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (s_out - s_in) / (c_out - c_in)
    out = z - mean
    out[~valid] = np.nan
    return out


def vrm(z, dx, dy, size=3, zfactor=1.0):
    """Vector Ruggedness Measure (Sappington et al. 2007), sans unité (0-1)."""
    p, q = gradient_horn(z, dx, dy, zfactor)
    slp = np.arctan(np.hypot(p, q))
    asp = np.arctan2(-p, -q)
    xy = np.sin(slp)
    comps = [xy * np.sin(asp), xy * np.cos(asp), np.cos(slp)]
    means = [focal_mean(c, size) for c in comps]
    r = np.sqrt(means[0] ** 2 + means[1] ** 2 + means[2] ** 2)
    out = 1.0 - r
    out[np.isnan(z)] = np.nan
    return out


def relative_position(z, size):
    """Position relative locale (z - min) / (max - min) dans la fenêtre (0 = bas, 1 = haut).

    Variante fenêtrée de la Relative Slope Position : elle ne s'appuie pas sur
    le réseau de crêtes et de talwegs comme la version SAGA.
    """
    zmin, zmax = focal_min(z, size), focal_max(z, size)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (z - zmin) / (zmax - zmin)
    out[(zmax - zmin) <= 0] = 0.5
    out[np.isnan(z)] = np.nan
    return out


def local_hypsometric_integral(z, size):
    """Intégrale hypsométrique locale (Pike & Wilson 1971) : (moy - min) / (max - min)."""
    zmin, zmax = focal_min(z, size), focal_max(z, size)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (focal_mean(z, size) - zmin) / (zmax - zmin)
    out[(zmax - zmin) <= 0] = np.nan
    out[np.isnan(z)] = np.nan
    return out


def dissection_index(z, size):
    """Indice de dissection (Dov Nir 1957) : (max - min) / max dans la fenêtre (0-1)."""
    zmin, zmax = focal_min(z, size), focal_max(z, size)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (zmax - zmin) / zmax
    out[zmax <= 0] = np.nan
    out[np.isnan(z)] = np.nan
    return out


# --- classifications ------------------------------------------------------
def class_breaks(values, n, method="equal"):
    v = values[np.isfinite(values)]
    if v.size == 0:
        return []
    if method == "quantile":
        b = np.unique(np.quantile(v, np.linspace(0, 1, n + 1)))
    else:
        b = np.linspace(v.min(), v.max(), n + 1)
    return [float(x) for x in b]


def classify(values, breaks):
    """Classe 1..n selon des bornes croissantes [b0, b1, ..., bn] ; 0 = NoData."""
    out = np.zeros(values.shape, dtype=np.uint8)
    finite = np.isfinite(values)
    inner = np.asarray(breaks[1:-1], dtype=np.float64)
    out[finite] = (np.searchsorted(inner, values[finite], side="right") + 1).astype(np.uint8)
    return out


def classify_open(values, thresholds):
    """Classes ouvertes : ]-inf, t1[, [t1, t2[, ..., [tn, +inf[ → 1..n+1 ; 0 = NoData."""
    out = np.zeros(values.shape, dtype=np.uint8)
    finite = np.isfinite(values)
    out[finite] = (np.searchsorted(np.asarray(thresholds, float), values[finite], side="right") + 1)
    return out


def aspect_classes(asp):
    """Exposition en 9 classes : 1 = plat, 2..9 = N, NE, E, SE, S, SO, O, NO."""
    out = np.zeros(asp.shape, dtype=np.uint8)
    finite = np.isfinite(asp)
    flat = finite & (asp < 0)
    a = asp[finite & ~flat]
    out[finite & ~flat] = (((a + 22.5) % 360) // 45).astype(np.uint8) + 2
    out[flat] = 1
    return out


ASPECT_LABELS = ["Plat", "Nord", "Nord-est", "Est", "Sud-est", "Sud", "Sud-ouest", "Ouest", "Nord-ouest"]


def hypsometric_curve(z, nbins=100):
    """Courbe hypsométrique (Strahler 1952) : surface relative au-dessus de chaque hauteur relative."""
    v = z[np.isfinite(z)]
    zmin, zmax = v.min(), v.max()
    h = np.linspace(0, 1, nbins + 1)
    levels = zmin + h * (zmax - zmin)
    vs = np.sort(v)
    above = 1.0 - np.searchsorted(vs, levels, side="left") / vs.size
    hi = float((v.mean() - zmin) / (zmax - zmin)) if zmax > zmin else float("nan")
    return h, above, hi
