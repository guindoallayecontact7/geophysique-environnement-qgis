# -*- coding: utf-8 -*-
"""Courbures et classifications géomorphologiques.

Convention de signe : courbure positive = convexe (bombée vers le haut),
négative = concave. Unité : 1/m (inverse du rayon de courbure).
Formules : Florinsky (2016), Digital Terrain Analysis in Soil Science and
Geology, chap. 2 ; Wood (1996) pour les courbures longitudinale et transversale.
"""
import numpy as np
from scipy import ndimage

from .grid import fill_nodata_nearest
from .terrain import derivatives_evans, slope, tpi

CURVATURE_NAMES = {
    "general": "Courbure générale",
    "profile": "Courbure de profil",
    "plan": "Courbure planaire",
    "longitudinal": "Courbure longitudinale",
    "cross": "Courbure transversale",
    "minimum": "Courbure minimale",
    "maximum": "Courbure maximale",
}


def smooth_surface(z, cells):
    """Lissage moyen de côté `cells` (> 1) pour calculer les courbures à une échelle plus large."""
    if cells <= 1:
        return z
    zf = fill_nodata_nearest(z)
    out = ndimage.uniform_filter(zf, cells, mode="nearest")
    out[np.isnan(z)] = np.nan
    return out


def curvatures(z, dx, dy, zfactor=1.0, scale_cells=1, which=None):
    """Calcule les courbures demandées. Renvoie un dict nom → tableau (1/m)."""
    which = which or list(CURVATURE_NAMES)
    zs = smooth_surface(z, scale_cells)
    p, q, r, t, s = derivatives_evans(zs, dx, dy, zfactor)
    p2, q2 = p * p, q * q
    g2 = p2 + q2
    w = 1.0 + g2
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        g2s = np.where(g2 > 1e-12, g2, np.nan)
        if "general" in which:
            out["general"] = -(r + t)
        if "profile" in which:
            out["profile"] = -(p2 * r + 2 * p * q * s + q2 * t) / (g2s * w ** 1.5)
        if "plan" in which:
            out["plan"] = -(q2 * r - 2 * p * q * s + p2 * t) / (g2s ** 1.5)
        if "longitudinal" in which:
            out["longitudinal"] = -(p2 * r + q2 * t + 2 * p * q * s) / g2s
        if "cross" in which:
            out["cross"] = -(q2 * r + p2 * t - 2 * p * q * s) / g2s
        if "minimum" in which or "maximum" in which:
            H = -((1 + q2) * r - 2 * p * q * s + (1 + p2) * t) / (2 * w ** 1.5)
            K = (r * t - s * s) / (w * w)
            root = np.sqrt(np.maximum(H * H - K, 0))
            if "minimum" in which:
                out["minimum"] = H - root
            if "maximum" in which:
                out["maximum"] = H + root
    # Sur une cellule plane, profil et plan sont indéfinis : valeur 0.
    for key in ("profile", "plan", "longitudinal", "cross"):
        if key in out:
            a = out[key]
            a[np.isnan(a) & ~np.isnan(z)] = 0.0
    nan = np.isnan(z)
    for a in out.values():
        a[nan] = np.nan
    return out


def auto_tolerance(curv, factor=0.5):
    """Seuil de planéité adapté aux données : factor × écart-type robuste (1,4826 × MAD)."""
    v = curv[np.isfinite(curv)]
    if v.size == 0:
        return 0.0
    mad = np.median(np.abs(v - np.median(v)))
    sd = 1.4826 * mad
    if sd == 0:
        sd = float(np.std(v))
    return float(factor * sd)


def sign_classes(curv, tol):
    """1 = concave, 2 = plane, 3 = convexe ; 0 = NoData."""
    out = np.zeros(curv.shape, dtype=np.uint8)
    f = np.isfinite(curv)
    out[f & (curv < -tol)] = 1
    out[f & (np.abs(curv) <= tol)] = 2
    out[f & (curv > tol)] = 3
    return out


SIGN_LABELS = ["Concave", "Plane", "Convexe"]


def slope_forms(profile_c, plan_c, tol_profile, tol_plan):
    """Formes de versant (Dikau 1989) : profil × plan, 9 classes.

    Code = 3 × (classe de profil - 1) + classe planaire, avec
    profil : 1 concave, 2 rectiligne, 3 convexe ;
    plan : 1 convergent (concave), 2 rectiligne, 3 divergent (convexe).
    """
    a = sign_classes(profile_c, tol_profile).astype(np.int16)
    b = sign_classes(plan_c, tol_plan).astype(np.int16)
    out = np.where((a > 0) & (b > 0), 3 * (a - 1) + b, 0).astype(np.uint8)
    return out


SLOPE_FORM_LABELS = [
    "Versant concave convergent", "Versant concave rectiligne", "Versant concave divergent",
    "Versant rectiligne convergent", "Versant rectiligne", "Versant rectiligne divergent",
    "Versant convexe convergent", "Versant convexe rectiligne", "Versant convexe divergent",
]


def slope_breaks(profile_c, slope_deg, tol, min_slope=0.5):
    """Ruptures de pente : 1 = rupture concave, 2 = rupture convexe, 0 = aucune / NoData."""
    out = np.zeros(profile_c.shape, dtype=np.uint8)
    f = np.isfinite(profile_c) & (slope_deg >= min_slope)
    out[f & (profile_c < -tol)] = 1
    out[f & (profile_c > tol)] = 2
    return out


def wood_features(slope_deg, cross_c, kmin, kmax, slope_tol, curv_tol):
    """Éléments morphométriques de Wood (1996).

    1 plan, 2 sommet, 3 crête, 4 col, 5 talweg (chenal), 6 dépression ; 0 = NoData.
    """
    out = np.zeros(slope_deg.shape, dtype=np.uint8)
    f = np.isfinite(slope_deg) & np.isfinite(kmin) & np.isfinite(kmax)
    steep = f & (slope_deg > slope_tol)
    flat = f & ~steep
    out[steep] = 1
    out[steep & (cross_c > curv_tol)] = 3
    out[steep & (cross_c < -curv_tol)] = 5
    out[flat] = 1
    pos_max = kmax > curv_tol
    neg_max = kmax < -curv_tol
    pos_min = kmin > curv_tol
    neg_min = kmin < -curv_tol
    out[flat & pos_max & pos_min] = 2
    out[flat & pos_max & neg_min] = 4
    out[flat & neg_max & neg_min] = 6
    out[flat & pos_max & ~pos_min & ~neg_min] = 3
    out[flat & neg_min & ~pos_max & ~neg_max] = 5
    return out


WOOD_LABELS = ["Plan", "Sommet", "Crête", "Col", "Talweg", "Dépression"]


def _standardize(a):
    v = a[np.isfinite(a)]
    sd = float(np.std(v)) if v.size else 1.0
    return (a - float(np.mean(v))) / (sd if sd > 0 else 1.0)


def slope_position(z, dx, dy, radius_cells, flat_slope_deg=5.0):
    """Position sur le versant, 6 classes (Weiss 2001) d'après le TPI standardisé.

    1 crête/sommet, 2 haut de versant, 3 mi-versant, 4 replat, 5 bas de versant, 6 vallée.
    """
    t = _standardize(tpi(z, 2 * radius_cells + 1))
    slp = slope(z, dx, dy)
    out = np.zeros(z.shape, dtype=np.uint8)
    f = np.isfinite(t)
    out[f & (t > 1)] = 1
    out[f & (t > 0.5) & (t <= 1)] = 2
    mid = f & (t >= -0.5) & (t <= 0.5)
    out[mid & (slp > flat_slope_deg)] = 3
    out[mid & (slp <= flat_slope_deg)] = 4
    out[f & (t >= -1) & (t < -0.5)] = 5
    out[f & (t < -1)] = 6
    return out


SLOPE_POSITION_LABELS = ["Crête, sommet", "Haut de versant", "Mi-versant",
                         "Replat", "Bas de versant", "Vallée"]


def weiss_landforms(z, dx, dy, small_cells, large_cells, flat_slope_deg=5.0):
    """Unités géomorphologiques, 10 classes (Weiss 2001), TPI à deux échelles."""
    sn = _standardize(tpi(z, 2 * small_cells + 1))
    ln = _standardize(tpi(z, 2 * large_cells + 1))
    slp = slope(z, dx, dy)
    out = np.zeros(z.shape, dtype=np.uint8)
    f = np.isfinite(sn) & np.isfinite(ln)
    s_lo, s_mid, s_hi = sn <= -1, (sn > -1) & (sn < 1), sn >= 1
    l_lo, l_mid, l_hi = ln <= -1, (ln > -1) & (ln < 1), ln >= 1
    out[f & s_lo & l_lo] = 1
    out[f & s_lo & l_mid] = 2
    out[f & s_lo & l_hi] = 3
    out[f & s_mid & l_lo] = 4
    out[f & s_mid & l_mid & (slp <= flat_slope_deg)] = 5
    out[f & s_mid & l_mid & (slp > flat_slope_deg)] = 6
    out[f & s_mid & l_hi] = 7
    out[f & s_hi & l_lo] = 8
    out[f & s_hi & l_mid] = 9
    out[f & s_hi & l_hi] = 10
    return out


WEISS_LABELS = [
    "Vallées encaissées, talwegs profonds", "Talwegs de mi-versant, vallons",
    "Talwegs d'amont, têtes de vallon", "Vallées en U", "Plaines", "Versants",
    "Hauts de versant, replats sommitaux", "Crêtes locales, buttes en vallée",
    "Crêtes de mi-versant, interfluves", "Sommets, crêtes majeures",
]


def ridges_thalwegs(z, dx, dy, radius_cells, plan_c, plan_tol):
    """Crêtes et talwegs : 1 talweg, 2 crête, 0 autre.

    Crête : TPI standardisé > 1 et courbure planaire divergente (> seuil).
    Talweg : TPI standardisé < -1 et courbure planaire convergente (< -seuil).
    """
    t = _standardize(tpi(z, 2 * radius_cells + 1))
    out = np.zeros(z.shape, dtype=np.uint8)
    out[np.isfinite(t) & (t < -1) & (plan_c < -plan_tol)] = 1
    out[np.isfinite(t) & (t > 1) & (plan_c > plan_tol)] = 2
    return out


def convergence_index(z, dx, dy):
    """Indice de convergence (Köthe & Lehmeier 1996), en % : -100 convergent, +100 divergent.

    Moyenne, sur les 8 voisins, de l'écart angulaire entre l'exposition du voisin
    et la direction voisin → centre, ramenée à [-100, 100].
    """
    from .terrain import gradient_horn
    from .grid import OFFSETS
    p, q = gradient_horn(z, dx, dy)
    asp = np.arctan2(-p, -q)
    nr, nc = z.shape
    ap = np.pad(asp, 1, mode="edge")
    total = np.zeros_like(asp)
    for dr, dc in OFFSETS:
        a_n = ap[1 + dr:1 + dr + nr, 1 + dc:1 + dc + nc]
        # direction du voisin vers le centre : (-dc vers l'est, +dr vers le nord)
        to_centre = np.arctan2(-dc * dx, dr * dy)
        d = np.abs((a_n - to_centre + np.pi) % (2 * np.pi) - np.pi)
        total += d
    mean_deg = np.degrees(total / 8.0)
    ci = (mean_deg - 90.0) / 90.0 * 100.0
    ci[np.isnan(z)] = np.nan
    return ci
