# -*- coding: utf-8 -*-
"""Module des profils topographiques et hydrographiques."""
import csv
import os

import numpy as np

from ..core import profile as PR, vector_io as V
from ..engines import charts
from ..engines.results import LayerSpec, Table
from ..engines.statistics import SETTINGS, fmt
from .common import new_result, check_grid

KINDS = {"topographique": "Profil topographique", "longitudinal": "Profil longitudinal du cours d'eau",
         "transversal": "Profil transversal de vallée"}

STAT_LABELS = [
    ("longueur_m", "Longueur du profil", "m"), ("z_min", "Altitude minimale", "m"), ("z_max", "Altitude maximale", "m"),
    ("z_debut", "Altitude au départ", "m"), ("z_fin", "Altitude à l'arrivée", "m"),
    ("denivele_m", "Dénivelé (max - min)", "m"), ("denivele_debut_fin_m", "Dénivelé départ - arrivée", "m"),
    ("denivele_cumule_positif_m", "Dénivelé cumulé positif", "m"),
    ("denivele_cumule_negatif_m", "Dénivelé cumulé négatif", "m"),
    ("pente_moy_pct", "Pente locale moyenne (valeur absolue)", "%"), ("pente_globale_pct", "Pente globale", "%"),
    ("pente_max_pct", "Pente locale maximale", "%"), ("part_convexe_pct", "Part convexe", "%"),
    ("part_concave_pct", "Part concave", "%"), ("part_rectiligne_pct", "Part rectiligne", "%"),
    ("nb_ruptures", "Nombre de ruptures de pente", ""),
]


def run(params, ctx, fb):
    """params["lines"] : liste de dict(name, xs, ys) dans le SCR du MNT."""
    p = dict({"step_m": None, "smooth_n": 5, "kind": "topographique", "curv_tol": None, "break_tol_deg": None},
             **params)
    grid = ctx.grid(p["dem_path"], p.get("band", 1))
    title = KINDS.get(p["kind"], "Profil")
    plural = {"topographique": "Profils topographiques", "longitudinal": "Profils longitudinaux",
              "transversal": "Profils transversaux"}
    res = new_result("profils", plural.get(p["kind"], "Profils") if len(p["lines"]) > 1 else title, grid)
    check_grid(grid, res)
    out = ctx.module_dir("profils")
    res.folder = out
    step = float(p["step_m"] or grid.dx)
    res.add_param("Pas d'échantillonnage", step, "m")
    res.add_param("Lissage (moyenne mobile)", int(p["smooth_n"]), "points")
    res.add_param("Interpolation", "bilinéaire")
    profiles = []
    stat_rows = []
    line_recs, break_recs = [], []
    for k, ln in enumerate(p["lines"], start=1):
        name = ln.get("name") or "Profil {}".format(k)
        xs, ys, d = PR.densify(ln["xs"], ln["ys"], step)
        z = PR.sample_bilinear(grid, xs, ys)
        ok = np.isfinite(z)
        if ok.sum() < 3:
            res.warnings.append("{} : moins de 3 points valides sur le MNT, ignoré.".format(name))
            continue
        if (~ok).any():
            res.warnings.append("{} : {} points hors MNT ou NoData exclus.".format(name, int((~ok).sum())))
        a = PR.analyse_profile(d, z, int(p["smooth_n"]), p["curv_tol"], p["break_tol_deg"])
        xs_ok, ys_ok = xs[ok], ys[ok]
        a["name"] = name
        a["x"], a["y"] = xs_ok, ys_ok
        profiles.append(a)
        base = os.path.join(out, "profil_{:02d}".format(k))
        with open(base + ".csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=SETTINGS.csv_separator)
            w.writerow(["distance (m)", "x", "y", "altitude (m)", "pente locale (%)", "courbure (1/m)",
                        "forme (1 convexe, -1 concave, 0 rectiligne)", "rupture"])
            br = set(a["breaks"].tolist())
            for i in range(a["distance"].size):
                w.writerow([fmt(a["distance"][i], 3), fmt(xs_ok[i], 3), fmt(ys_ok[i], 3), fmt(a["z"][i], 3),
                            fmt(a["slope_pct"][i], 3), fmt(a["curvature"][i], 6), int(a["form"][i]), int(i in br)])
        res.exports.append(base + ".csv")
        res.charts += charts.profiles([a], base, "{} - {}".format(title, name))
        s = a["stats"]
        stat_rows.append([name] + [s.get(key) for key, _, _ in STAT_LABELS])
        line_recs.append((ln["xs"], ln["ys"], {"id": k, "nom": name, "longueur_m": s["longueur_m"],
                                               "pente_moy_pct": s["pente_moy_pct"], "nb_ruptures": s["nb_ruptures"]}))
        for i in a["breaks"]:
            break_recs.append((float(xs_ok[i]), float(ys_ok[i]), {"profil": k, "distance_m": float(a["distance"][i]),
                                                                  "altitude": float(a["z"][i]),
                                                                  "changement_pente_deg": float(a["slope_change_deg"][i])}))
        segs = PR.segments(a["form"], a["distance"])
        res.add_table(Table("Segments concaves et convexes - {}".format(name),
                            ["Forme", "Début", "Fin", "Longueur"],
                            [[{1: "convexe", -1: "concave", 0: "rectiligne"}[f], d0, d1, d1 - d0] for f, d0, d1 in segs],
                            ["", "m", "m", "m"]))
        if a["breaks"].size:
            res.add_table(Table("Ruptures de pente - {}".format(name), ["Distance", "Altitude", "Changement de pente"],
                                [[float(a["distance"][i]), float(a["z"][i]), float(a["slope_change_deg"][i])]
                                 for i in a["breaks"]], ["m", "m", "°"]))
        fb.progress(10 + 70 * k / max(1, len(p["lines"])))
    if not profiles:
        raise ValueError("Aucun profil exploitable.")
    res.tables.insert(0, Table("Statistiques des profils", ["Profil"] + [lab for _, lab, _ in STAT_LABELS],
                               stat_rows, [""] + [u for _, _, u in STAT_LABELS]))
    if len(profiles) == 1:
        for key, lab, unit in STAT_LABELS:
            res.add_summary(lab, profiles[0]["stats"].get(key), unit)
    else:
        res.charts += charts.profiles(profiles, os.path.join(out, "comparaison_profils"),
                                      "Comparaison des profils", show_forms=False)
        res.add_summary("Nombre de profils", len(profiles), "")
    gpkg = os.path.join(out, "profils.gpkg")
    V.write_lines(gpkg, "profils", grid.wkt, [("id", int), ("nom", str), ("longueur_m", float),
                                              ("pente_moy_pct", float), ("nb_ruptures", int)], line_recs)
    res.add_layer(LayerSpec(gpkg, "Tracés des profils", "vector", "profils", {"type": "lines", "color": "#e31a1c", "width": 0.7},
                            map_key="profils", map_title="Carte des tracés de profils"))
    if break_recs:
        V.write_points(gpkg, "ruptures", grid.wkt, [("profil", int), ("distance_m", float), ("altitude", float),
                                                    ("changement_pente_deg", float)], break_recs)
        res.add_layer(LayerSpec(gpkg, "Ruptures de pente (profils)", "vector", "ruptures",
                                {"type": "points", "color": "#67000d", "size": 2.4}))
    res.extra["profiles"] = profiles
    res.method = (
        "Échantillonnage régulier le long du tracé (pas indiqué, sommets conservés) et interpolation bilinéaire "
        "du MNT. Pente locale : dérivée centrée de l'altitude lissée (moyenne mobile). Courbure du profil : "
        "-d²z/dx² (positive = convexe). Segments concaves, convexes et rectilignes : seuil de ± 0,5 écart-type "
        "de la courbure (ou valeur fournie). Ruptures de pente : maxima locaux du changement d'inclinaison "
        "entre les fenêtres amont et aval, au-delà de 2 écarts-types (minimum 1°) ou du seuil fourni.")
    res.limits = (
        "La précision du profil est celle du MNT : un MNS inclut végétation et bâti, et l'interpolation lisse "
        "les ruptures plus étroites que la résolution. Les seuils de forme et de rupture dépendent du lissage.")
    fb.progress(100)
    return res
