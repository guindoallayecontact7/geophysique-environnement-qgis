# -*- coding: utf-8 -*-
"""Tests du noyau de calcul (sans QGIS).

Lancement depuis la racine du dépôt, avec le Python de QGIS :
    python-qgis-ltr.bat GeoPhysiqueEnvironnement/tests/test_core.py
"""
import heapq
import math
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from GeoPhysiqueEnvironnement.core import geomorph, hydrology as hy, terrain  # noqa: E402
from GeoPhysiqueEnvironnement.core.grid import DemGrid, edge_mask  # noqa: E402
from GeoPhysiqueEnvironnement.core.profile import analyse_profile  # noqa: E402


def reference_priority_flood(z, valid):
    """Priority-Flood cellule par cellule (Barnes et al. 2014), sans epsilon."""
    nr, nc = z.shape
    out = z.copy()
    done = ~valid.copy()
    heap = []
    edge = edge_mask(valid)
    for r, c in zip(*np.nonzero(edge)):
        heapq.heappush(heap, (z[r, c], r, c))
        done[r, c] = True
    while heap:
        h, r, c = heapq.heappop(heap)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, c + dc
                if (dr or dc) and 0 <= rr < nr and 0 <= cc < nc and not done[rr, cc]:
                    done[rr, cc] = True
                    out[rr, cc] = max(z[rr, cc], h)
                    heapq.heappush(heap, (out[rr, cc], rr, cc))
    return out


class TestFill(unittest.TestCase):
    def test_random_surfaces_match_reference(self):
        rng = np.random.default_rng(42)
        for trial in range(6):
            z = rng.normal(100, 5, (40, 55)).round(1)
            valid = np.ones(z.shape, bool)
            if trial % 2:
                valid[10:14, 20:30] = False
                z[~valid] = np.nan
            filled, sinks, n = hy.fill_depressions(z, valid, 30, 30)
            ref = reference_priority_flood(np.where(valid, z, np.nan), valid)
            np.testing.assert_allclose(filled[valid], ref[valid])
            self.assertFalse(sinks.any())

    def test_every_cell_drains_after_fill(self):
        rng = np.random.default_rng(1)
        z = rng.normal(50, 3, (60, 60))
        valid = np.ones(z.shape, bool)
        filled, sinks, _ = hy.fill_depressions(z, valid, 10, 10)
        model = hy.route_d8(filled, valid, 10, 10)
        acc = hy.accumulate_d8(model)
        # aucune cellule intérieure terminale
        self.assertFalse(model.sinks.any())
        # la somme des accumulations aux sorties = nombre de cellules
        term = model.rec < 0
        self.assertAlmostEqual(acc.ravel()[term].sum(), valid.sum())

    def test_depth_limited_fill_keeps_deep_pit(self):
        x, y = np.meshgrid(np.arange(41), np.arange(41))
        z = 100 - 30 * np.exp(-((x - 20) ** 2 + (y - 20) ** 2) / 50.0) + 0.01 * x
        valid = np.ones(z.shape, bool)
        filled, sinks, _ = hy.fill_depressions(z, valid, 10, 10, max_depth=5)
        self.assertTrue(sinks[20, 20])
        self.assertAlmostEqual(filled[20, 20], z[20, 20])
        full, _, _ = hy.fill_depressions(z, valid, 10, 10)
        self.assertGreater(full[20, 20], z[20, 20] + 20)


class TestFlow(unittest.TestCase):
    def setUp(self):
        # plan incliné vers le sud avec un talweg central
        x, y = np.meshgrid(np.arange(31), np.arange(41))
        self.z = 200.0 - 2.0 * y + 0.5 * np.abs(x - 15)
        self.valid = np.ones(self.z.shape, bool)
        self.model = hy.route_d8(self.z, self.valid, 10, 10)

    def test_mass_conservation_all_methods(self):
        n = self.valid.sum()
        for acc in (hy.accumulate_d8(self.model), hy.accumulate_mfd(self.model),
                    hy.accumulate_dinf(self.model)):
            term = self.model.rec < 0
            self.assertAlmostEqual(np.nansum(acc.ravel()[term]), n, places=6)

    def test_streams_and_basin(self):
        acc = hy.accumulate_d8(self.model)
        net = hy.extract_streams(self.model, acc, 20)
        self.assertTrue(net.mask.reshape(self.z.shape)[35, 15])
        self.assertGreaterEqual(net.strahler.max(), 2)
        outlet = 39 * 31 + 15
        lab = hy.label_basins(self.model, [outlet])
        self.assertEqual(lab.sum(), acc.ravel()[outlet])

    def test_flow_length(self):
        dfl = hy.flow_length_downstream(self.model)
        self.assertEqual(dfl[40, 15], 0)
        self.assertAlmostEqual(dfl[30, 15], 100.0)


class TestTerrain(unittest.TestCase):
    def test_slope_aspect_plane(self):
        x, y = np.meshgrid(np.arange(20) * 10.0, np.arange(20) * 10.0)
        z = 0.1 * x  # monte vers l'est, rangées vers le sud
        s = terrain.slope(z, 10, 10)
        a = terrain.aspect(z, 10, 10)
        self.assertAlmostEqual(s[10, 10], math.degrees(math.atan(0.1)), places=6)
        self.assertAlmostEqual(a[10, 10], 270.0, places=6)  # descend vers l'ouest
        z2 = -0.2 * y  # rangées vers le sud plus basses : descend vers le sud
        self.assertAlmostEqual(terrain.aspect(z2, 10, 10)[10, 10], 180.0, places=6)

    def test_curvature_signs(self):
        x, y = np.meshgrid(np.arange(-10, 11) * 5.0, np.arange(-10, 11) * 5.0)
        dome = 100 - 0.01 * (x ** 2 + y ** 2)
        bowl = 100 + 0.01 * (x ** 2 + y ** 2)
        cd = geomorph.curvatures(dome, 5, 5)
        cb = geomorph.curvatures(bowl, 5, 5)
        self.assertGreater(cd["general"][10, 10], 0)
        self.assertLess(cb["general"][10, 10], 0)
        self.assertGreater(cd["minimum"][10, 10], 0)
        self.assertLess(cb["maximum"][10, 10], 0)
        # col : x² - y²
        saddle = 100 + 0.01 * (x ** 2 - y ** 2)
        cs = geomorph.curvatures(saddle, 5, 5)
        self.assertLess(cs["minimum"][10, 10], 0)
        self.assertGreater(cs["maximum"][10, 10], 0)
        # profil convexe sur le flanc d'un dôme
        self.assertGreater(cd["profile"][10, 15], 0)
        self.assertGreater(cd["plan"][10, 15], 0)

    def test_tpi_vrm(self):
        z = np.zeros((21, 21))
        z[10, 10] = 10
        self.assertGreater(terrain.tpi(z, 3)[10, 10], 9.9)
        self.assertLess(terrain.vrm(np.zeros((9, 9)), 1, 1)[4, 4], 1e-12)

    def test_profile_forms(self):
        d = np.linspace(0, 1000, 201)
        z = 100 - (d / 100.0) ** 2  # convexe
        res = analyse_profile(d, z, smooth_n=1)
        self.assertGreater(res["stats"]["part_convexe_pct"], 50)
        z2 = (d / 100.0) ** 2
        res2 = analyse_profile(d, z2, smooth_n=1)
        self.assertGreater(res2["stats"]["part_concave_pct"], 50)


class TestMorphometry(unittest.TestCase):
    def test_disc_basin_gravelius(self):
        from GeoPhysiqueEnvironnement.core import morphometry, vector_io
        n = 201
        yy, xx = np.mgrid[0:n, 0:n]
        r = np.hypot(xx - 100, yy - 100)
        z = 10 + 0.5 * r  # entonnoir : tout converge au centre
        z[r > 95] = np.nan
        valid = np.isfinite(z)
        grid = DemGrid(z, (0, 10, 0, n * 10, 0, -10), "")
        model = hy.route_d8(z, valid, 10, 10)
        outlet = 100 * n + 100
        lab = hy.label_basins(model, [outlet])
        geoms = vector_io.polygonize_labels(lab, grid)
        slope = terrain.slope(z, 10, 10)
        rows, _ = morphometry.basin_parameters(grid, model, lab, [1], {1: outlet}, geoms, slope)
        kc = rows[0]["kc_gravelius"]
        self.assertTrue(0.98 < kc < 1.08, kc)
        self.assertAlmostEqual(rows[0]["aire_km2"], valid.sum() * 100 / 1e6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
