# -*- coding: utf-8 -*-
"""Lecture, écriture et contrôle des MNT (GDAL)."""
import math
import os

import numpy as np
from osgeo import gdal, osr

# Voisinage D8 : (décalage ligne, décalage colonne), dans l'ordre E, SE, S, SO, O, NO, N, NE.
OFFSETS = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
# Codes de direction D8 de type ESRI, dans le même ordre.
D8_CODES = [1, 2, 4, 8, 16, 32, 64, 128]

NODATA_FLOAT = -9999.0


class Canceled(Exception):
    """Levée quand l'utilisateur annule un traitement."""


class Feedback:
    """Retour de progression minimal, utilisable hors de QGIS."""

    def __init__(self, progress=None, message=None, canceled=None):
        self._progress = progress
        self._message = message
        self._canceled = canceled

    def progress(self, value):
        if self._progress:
            self._progress(float(value))

    def info(self, text):
        if self._message:
            self._message(text)

    def is_canceled(self):
        return bool(self._canceled and self._canceled())

    def check(self):
        if self.is_canceled():
            raise Canceled("Traitement annulé par l'utilisateur.")


class DemGrid:
    """MNT chargé en mémoire : altitudes en float64, NoData = NaN."""

    def __init__(self, z, geotransform, wkt, source="", band=1):
        self.z = z
        self.gt = tuple(geotransform)
        self.wkt = wkt or ""
        self.source = source
        self.band = band
        self.nrows, self.ncols = z.shape
        self.dx = abs(self.gt[1])
        self.dy = abs(self.gt[5])

    # --- géométrie -------------------------------------------------------
    @property
    def valid(self):
        return ~np.isnan(self.z)

    @property
    def cell_area(self):
        return self.dx * self.dy

    @property
    def extent(self):
        x0, y0 = self.gt[0], self.gt[3]
        x1 = x0 + self.ncols * self.gt[1]
        y1 = y0 + self.nrows * self.gt[5]
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def rc_to_xy(self, r, c):
        x = self.gt[0] + (np.asarray(c) + 0.5) * self.gt[1]
        y = self.gt[3] + (np.asarray(r) + 0.5) * self.gt[5]
        return x, y

    def xy_to_rc(self, x, y):
        c = int(math.floor((x - self.gt[0]) / self.gt[1]))
        r = int(math.floor((y - self.gt[3]) / self.gt[5]))
        return r, c

    def inside(self, r, c):
        return 0 <= r < self.nrows and 0 <= c < self.ncols

    def srs(self):
        s = osr.SpatialReference()
        if self.wkt:
            s.ImportFromWkt(self.wkt)
        return s

    def crs_description(self):
        s = self.srs()
        if not self.wkt:
            return "non défini"
        name = s.GetAttrValue("PROJCS") or s.GetAttrValue("GEOGCS") or "?"
        code = s.GetAuthorityCode(None)
        auth = s.GetAuthorityName(None)
        return "{} ({}:{})".format(name, auth, code) if code else name

    def copy_with(self, z):
        return DemGrid(z, self.gt, self.wkt, self.source, self.band)


def read_dem(path, band=1):
    ds = gdal.Open(path)
    if ds is None:
        raise IOError("Impossible d'ouvrir le raster : {}".format(path))
    if ds.RasterCount < band:
        raise ValueError("Le raster ne contient pas la bande {}.".format(band))
    gt = ds.GetGeoTransform()
    if abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12:
        raise ValueError("Raster avec rotation : rééchantillonnez-le d'abord (gdalwarp).")
    b = ds.GetRasterBand(band)
    arr = b.ReadAsArray().astype(np.float64)
    nd = b.GetNoDataValue()
    if nd is not None:
        if math.isnan(nd):
            pass
        else:
            arr[arr == nd] = np.nan
    mask_flags = b.GetMaskFlags()
    if not (mask_flags & gdal.GMF_ALL_VALID) and nd is None:
        m = b.GetMaskBand().ReadAsArray()
        arr[m == 0] = np.nan
    arr[~np.isfinite(arr)] = np.nan
    grid = DemGrid(arr, gt, ds.GetProjection(), source=path, band=band)
    ds = None
    return grid


def write_raster(path, array, grid, dtype="float32", nodata=None):
    """Écrit un GeoTIFF compressé aligné sur la grille du MNT."""
    gdt = {
        "float32": gdal.GDT_Float32, "float64": gdal.GDT_Float64,
        "int32": gdal.GDT_Int32, "int16": gdal.GDT_Int16,
        "uint8": gdal.GDT_Byte, "uint16": gdal.GDT_UInt16,
    }[dtype]
    if nodata is None:
        nodata = {"uint8": 0, "uint16": 0}.get(dtype, NODATA_FLOAT if dtype.startswith("float") else -1)
    out = np.array(array, copy=True)
    if out.dtype.kind == "f":
        out[~np.isfinite(out)] = nodata
    out = out.astype(dtype)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if os.path.exists(path):
        gdal.GetDriverByName("GTiff").Delete(path)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, grid.ncols, grid.nrows, 1, gdt,
                    ["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"])
    if ds is None:
        raise IOError("Écriture impossible : {}".format(path))
    ds.SetGeoTransform(grid.gt)
    if grid.wkt:
        ds.SetProjection(grid.wkt)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(out)
    b.FlushCache()
    ds = None
    return path


def utm_epsg_for(grid):
    """Code EPSG UTM WGS 84 adapté au centre du MNT (si le MNT est géographique)."""
    x0, y0, x1, y1 = grid.extent
    lon, lat = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def reproject_to_utm(src_path, dst_path, band=1):
    """Reprojette un MNT géographique vers l'UTM WGS 84 de sa zone (bilinéaire)."""
    grid = read_dem(src_path, band)
    epsg = utm_epsg_for(grid)
    lat = (grid.extent[1] + grid.extent[3]) / 2.0
    res = grid.dx * 111320.0 * math.cos(math.radians(lat))
    res = max(1.0, round(res, 1))
    opts = gdal.WarpOptions(dstSRS="EPSG:{}".format(epsg), xRes=res, yRes=res,
                            resampleAlg="bilinear", dstNodata=NODATA_FLOAT,
                            outputType=gdal.GDT_Float32,
                            creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    ds = gdal.Warp(dst_path, src_path, options=opts)
    if ds is None:
        raise IOError("Reprojection impossible.")
    ds = None
    return dst_path, epsg, res


def clip_to_polygon(src_path, dst_path, cutline_path, cutline_layer=None):
    """Découpe le MNT selon une couche polygonale (masque d'étude)."""
    kwargs = dict(cutlineDSName=cutline_path, cropToCutline=True, dstNodata=NODATA_FLOAT,
                  outputType=gdal.GDT_Float32, creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    if cutline_layer:
        kwargs["cutlineLayer"] = cutline_layer
    ds = gdal.Warp(dst_path, src_path, options=gdal.WarpOptions(**kwargs))
    if ds is None:
        raise IOError("Découpage impossible.")
    ds = None
    return dst_path


def validate_dem(grid, max_cells=60_000_000):
    """Contrôles préalables. Renvoie une liste de dict(niveau, controle, message).

    niveau : « ok », « avertissement » ou « erreur ». Une erreur bloque les
    calculs de distance, de pente et d'hydrologie.
    """
    checks = []

    def add(level, item, msg):
        checks.append({"niveau": level, "controle": item, "message": msg})

    srs = grid.srs()
    if not grid.wkt:
        add("erreur", "Système de coordonnées", "Aucun SCR défini : distances et superficies impossibles.")
    elif srs.IsGeographic():
        add("erreur", "Système de coordonnées",
            "SCR géographique ({}) : les pentes et superficies exigent un SCR projeté métrique. "
            "Utilisez « Reprojeter en UTM ».".format(grid.crs_description()))
    else:
        add("ok", "Système de coordonnées", grid.crs_description())
        unit = (srs.GetLinearUnitsName() or "").lower()
        factor = srs.GetLinearUnits()
        if abs(factor - 1.0) > 1e-9:
            add("erreur", "Unités horizontales",
                "Unité linéaire « {} » ({} m) : reprojetez en mètres.".format(unit, factor))
        else:
            add("ok", "Unités horizontales", "mètre")

    add("ok", "Unités verticales",
        "Supposées en mètres (non vérifiables dans le fichier). Corrigez le facteur Z si besoin.")

    ratio = grid.dx / grid.dy if grid.dy else 0
    if abs(ratio - 1) > 0.01:
        add("avertissement", "Résolution",
            "Cellules non carrées ({:.3f} × {:.3f}) : les calculs D8 en tiennent compte, "
            "mais un rééchantillonnage carré est préférable.".format(grid.dx, grid.dy))
    else:
        add("ok", "Résolution", "{:.3f} × {:.3f} (unités du SCR)".format(grid.dx, grid.dy))

    n = grid.nrows * grid.ncols
    add("ok" if n <= max_cells else "avertissement", "Dimensions",
        "{} colonnes × {} lignes = {:,} cellules".format(grid.ncols, grid.nrows, n).replace(",", " ")
        + ("" if n <= max_cells else " : volume élevé, mémoire et temps de calcul importants."))

    valid = grid.valid
    nvalid = int(valid.sum())
    if nvalid == 0:
        add("erreur", "Valeurs NoData", "Aucune cellule valide.")
        return checks
    pct = 100.0 * (n - nvalid) / n
    add("ok" if pct < 50 else "avertissement", "Valeurs NoData",
        "{:.2f} % de cellules NoData".format(pct))
    zmin, zmax = float(np.nanmin(grid.z)), float(np.nanmax(grid.z))
    if zmin < -500 or zmax > 9000:
        add("avertissement", "Cohérence altimétrique",
            "Altitudes {:.1f} à {:.1f} : hors de la plage terrestre plausible, vérifiez l'unité "
            "et la valeur NoData.".format(zmin, zmax))
    elif zmax - zmin < 1e-6:
        add("erreur", "Cohérence altimétrique", "MNT plat (altitude constante).")
    else:
        add("ok", "Cohérence altimétrique", "Altitudes {:.2f} à {:.2f}".format(zmin, zmax))
    return checks


def has_blocking_error(checks):
    return any(c["niveau"] == "erreur" for c in checks)


def fill_nodata_nearest(z):
    """Copie de z où chaque NaN reçoit la valeur valide la plus proche (bords des dérivées)."""
    nan = np.isnan(z)
    if not nan.any():
        return z
    from scipy import ndimage
    idx = ndimage.distance_transform_edt(nan, return_distances=False, return_indices=True)
    return z[tuple(idx)]


def edge_mask(valid):
    """Cellules valides au bord de la grille ou voisines d'une cellule NoData."""
    nr, nc = valid.shape
    edge = np.zeros_like(valid)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    pad = np.pad(valid, 1, constant_values=False)
    for dr, dc in OFFSETS:
        edge |= ~pad[1 + dr:1 + dr + nr, 1 + dc:1 + dc + nc]
    return edge & valid
