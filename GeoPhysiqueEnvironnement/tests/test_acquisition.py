# -*- coding: utf-8 -*-
"""Tests hors ligne du module d'acquisition (sans réseau ni QGIS)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from osgeo import ogr  # noqa: E402

from GeoPhysiqueEnvironnement.acquisition import catalogs as C, jobs as J  # noqa: E402


class AcquisitionTests(unittest.TestCase):
    def test_utm(self):
        self.assertEqual(J.utm_epsg(-8.2, 13.3), 32629)
        self.assertEqual(J.utm_epsg(2.35, 48.85), 32631)
        self.assertEqual(J.utm_epsg(-47.9, -15.8), 32723)

    def test_coverage(self):
        aoi = ogr.CreateGeometryFromWkt("POLYGON((0 0,2 0,2 2,0 2,0 0))")
        half = {"type": "Polygon", "coordinates": [[[1, -1], [3, -1], [3, 3], [1, 3], [1, -1]]]}
        self.assertAlmostEqual(J.coverage(half, aoi), 50.0)
        self.assertIsNone(J.coverage(None, aoi))

    def test_cmr_box(self):
        g = C._cmr_geometry({"boxes": ["13 -9 14 -8"]})
        self.assertEqual(g["coordinates"][0][0], [-9.0, 13.0])

    def test_earth_search_href(self):
        h = C.EarthSearch().fix_href("s3://copernicus-dem-30m/A/A.tif")
        self.assertEqual(h, "https://copernicus-dem-30m.s3.amazonaws.com/A/A.tif")

    def test_sources(self):
        ids = [s["id"] for s in C.SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        for s in C.SOURCES:
            self.assertIn(s["catalog"], C.CATALOGS)
            self.assertIn(s["kind"], ("MNT", "Optique", "Radar"))
            if s.get("auth"):
                self.assertIn(s["auth"], C.ACCOUNTS)


if __name__ == "__main__":
    unittest.main()
