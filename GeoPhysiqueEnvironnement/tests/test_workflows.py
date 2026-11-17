# -*- coding: utf-8 -*-
"""Test de bout en bout des chaînes de traitement sur un MNT réel.

Usage : python-qgis-ltr.bat tests/test_workflows.py <mnt.tif> <dossier_de_travail>
Sans argument, un MNT synthétique (deux vallées) est généré.
"""
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from osgeo import gdal  # noqa: E402

from GeoPhysiqueEnvironnement.analyses import (topography, morphometry_indices, geomorphology,  # noqa: E402
                                               hydrology, basins, profiles)
from GeoPhysiqueEnvironnement.analyses.common import Context  # noqa: E402
from GeoPhysiqueEnvironnement.core.grid import Feedback, DemGrid, write_raster  # noqa: E402
from GeoPhysiqueEnvironnement.engines import statistics as ST  # noqa: E402


def synthetic_dem(path):
    n = 300
    y, x = np.mgrid[0:n, 0:n] * 20.0
    z = 400 - 0.04 * y + 25 * np.abs(np.sin(x / 1500.0)) + 3 * np.sin(x / 90.0) * np.cos(y / 120.0)
    g = DemGrid(z, (500000, 20, 0, 1500000, 0, -20), _utm_wkt())
    write_raster(path, z, g)
    return path


def _utm_wkt():
    from osgeo import osr
    s = osr.SpatialReference()
    s.ImportFromEPSG(32629)
    return s.ExportToWkt()


def main():
    if len(sys.argv) >= 3:
        dem, work = sys.argv[1], sys.argv[2]
    else:
        work = os.path.join(os.environ.get("TEMP", "/tmp"), "geophysique_test")
        os.makedirs(work, exist_ok=True)
        dem = synthetic_dem(os.path.join(work, "mnt_synthetique.tif"))
    ctx = Context(os.path.join(work, "espace"))
    fb = Feedback(message=lambda m: print("    ·", m))
    results = []

    def step(name, fn, params):
        t = time.time()
        r = fn(dict(params, dem_path=dem), ctx, fb)
        files = ST.export_result(r, os.path.join(r.folder, "statistiques"))
        missing = [s.path for s in r.layers if not os.path.exists(s.path)]
        assert not missing, missing
        print("[OK] {:<28} {:5.1f} s  couches={:2d} tableaux={:2d} graphiques={:2d} exports={}".format(
            name, time.time() - t, len(r.layers), len(r.tables), len(r.charts), len(files)))
        for w in r.warnings:
            print("     avertissement :", w)
        results.append(r)
        return r

    step("Topographie", topography.run, {})
    step("Morphométrie", morphometry_indices.run, {"flow": "mfd"})
    step("Géomorphologie", geomorphology.run, {"scale_m": 90})
    h = step("Hydrologie", hydrology.run, {"flow": "dinf", "fill": "fill_depth", "max_depth": 3.0})
    st = ctx.hydro
    acc = st.acc_d8
    nr, nc = acc.shape
    m = 60
    inner = np.full(acc.shape, -1.0)
    inner[m:nr - m, m:nc - m] = acc[m:nr - m, m:nc - m]
    k = int(np.argmax(inner))
    r, c = divmod(k, nc)
    x, y = st.grid.rc_to_xy(r + 2, c + 1)  # point légèrement décalé : teste le recalage
    if len(sys.argv) >= 5:
        x, y = float(sys.argv[3]), float(sys.argv[4])
    b = step("Bassin (exutoire)", basins.run_outlets, {"outlets": [(float(x), float(y), "Exutoire test")],
                                                      "fill": "fill_depth", "max_depth": 3.0, "snap_radius_m": 200})
    row = b.extra["basin_rows"] if "basin_rows" in b.extra else b.extra["state"]["rows"]
    print("     bassin : {:.2f} km², Kc = {:.3f}, Strahler max = {}, Lcp = {:.2f} km, Tc Kirpich = {:.1f} min".format(
        row[0]["aire_km2"], row[0]["kc_gravelius"], row[0]["strahler_max"], row[0]["lcp_km"], row[0]["tc_kirpich_min"]))
    for method, extra in (("liens", {}), ("strahler", {"strahler_min": 2}), ("superficie", {"min_area_km2": 2.0}),
                          ("seuil", {"threshold_km2": 1.0})):
        sb = step("Sous-bassins ({})".format(method), basins.run_subbasins, dict({"method": method}, **extra))
        topo = [t for t in sb.tables if t.title.startswith("Contrôle")][0]
        bad = [r_ for r_ in topo.rows if r_[3] not in ("", "conforme")]
        print("     {} sous-bassins ; contrôles non conformes : {}".format(len(sb.extra["state"]["ids"]), bad or "aucun"))
        assert not bad, bad
    # sous-bassins par points : exutoires corrigés au milieu du cours principal
    path = ctx.last_basin["paths"][1]
    mid = path[len(path) // 2]
    px, py = st.grid.rc_to_xy(mid // nc, mid % nc)
    step("Sous-bassins (points)", basins.run_subbasins, {"method": "points", "points": [(float(px), float(py))]})
    step("Bassins automatiques", basins.run_auto, {"min_area_km2": 5.0, "fill": "fill_depth", "max_depth": 3.0})
    # profils : cours principal + un transect
    xs, ys = st.grid.rc_to_xy(np.array(path) // nc, np.array(path) % nc)
    x0, y0, x1, y1 = st.grid.extent
    step("Profils", profiles.run, {"lines": [
        {"name": "Cours principal", "xs": list(xs), "ys": list(ys)},
        {"name": "Transect", "xs": [x0 + 0.2 * (x1 - x0), x0 + 0.8 * (x1 - x0)], "ys": [(y0 + y1) / 2] * 2}],
        "kind": "longitudinal"})
    print("Dossier de travail :", ctx.workspace)
    return results


if __name__ == "__main__":
    main()
