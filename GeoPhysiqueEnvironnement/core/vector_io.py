# -*- coding: utf-8 -*-
"""Écriture des résultats vectoriels en GeoPackage (OGR), sans dépendance QGIS."""
import os

import numpy as np
from osgeo import gdal, ogr, osr

_OGR_TYPES = {int: ogr.OFTInteger64, float: ogr.OFTReal, str: ogr.OFTString}


def _srs(wkt):
    s = osr.SpatialReference()
    if wkt:
        s.ImportFromWkt(wkt)
        try:
            s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        except AttributeError:
            pass
    return s


def _open_gpkg(path):
    drv = ogr.GetDriverByName("GPKG")
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if os.path.exists(path):
        ds = drv.Open(path, 1)
        if ds is not None:
            return ds
        drv.DeleteDataSource(path)
    return drv.CreateDataSource(path)


def _create_layer(ds, name, wkt, geom_type, fields):
    for i in range(ds.GetLayerCount()):
        if ds.GetLayerByIndex(i).GetName() == name:
            ds.DeleteLayer(i)
            break
    lyr = ds.CreateLayer(name, _srs(wkt), geom_type, ["OVERWRITE=YES"])
    for fname, ftype in fields:
        lyr.CreateField(ogr.FieldDefn(fname, _OGR_TYPES.get(ftype, ftype)))
    return lyr


def _set_attrs(feat, attrs):
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, (np.integer,)):
            v = int(v)
        elif isinstance(v, (np.floating,)):
            v = float(v)
        if isinstance(v, float) and not np.isfinite(v):
            continue
        feat.SetField(k, v)


def write_points(path, layer, wkt, fields, records):
    """records : liste de (x, y, dict d'attributs)."""
    ds = _open_gpkg(path)
    lyr = _create_layer(ds, layer, wkt, ogr.wkbPoint, fields)
    lyr.StartTransaction()
    for x, y, attrs in records:
        f = ogr.Feature(lyr.GetLayerDefn())
        g = ogr.Geometry(ogr.wkbPoint)
        g.AddPoint_2D(float(x), float(y))
        f.SetGeometry(g)
        _set_attrs(f, attrs)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None
    return path


def write_lines(path, layer, wkt, fields, records):
    """records : liste de (xs, ys, dict d'attributs)."""
    ds = _open_gpkg(path)
    lyr = _create_layer(ds, layer, wkt, ogr.wkbLineString, fields)
    lyr.StartTransaction()
    for xs, ys, attrs in records:
        if len(xs) < 2:
            continue
        g = ogr.Geometry(ogr.wkbLineString)
        for x, y in zip(xs, ys):
            g.AddPoint_2D(float(x), float(y))
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(g)
        _set_attrs(f, attrs)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None
    return path


def polygonize_labels(labels, grid):
    """Vectorise un raster de labels (> 0) en connexité 8.

    Renvoie un dict label → géométrie OGR (MultiPolygon fusionné).
    """
    nr, nc = grid.nrows, grid.ncols
    lab = labels.reshape(nr, nc).astype(np.int32)
    mem = gdal.GetDriverByName("MEM").Create("", nc, nr, 1, gdal.GDT_Int32)
    mem.SetGeoTransform(grid.gt)
    if grid.wkt:
        mem.SetProjection(grid.wkt)
    band = mem.GetRasterBand(1)
    band.WriteArray(lab)
    band.SetNoDataValue(0)
    vdrv = "MEM" if int(gdal.VersionInfo()) >= 3110000 else "Memory"
    vds = ogr.GetDriverByName(vdrv).CreateDataSource("poly")
    vl = vds.CreateLayer("poly", _srs(grid.wkt), ogr.wkbPolygon)
    vl.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
    gdal.Polygonize(band, band.GetMaskBand(), vl, 0, ["8CONNECTED=8"])
    parts = {}
    for f in vl:
        k = f.GetField(0)
        if k <= 0:
            continue
        parts.setdefault(k, []).append(f.GetGeometryRef().Clone())
    geoms = {}
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        for k, gl in parts.items():
            if len(gl) == 1:
                g = gl[0]
            else:
                mp = ogr.Geometry(ogr.wkbMultiPolygon)
                for g in gl:
                    mp.AddGeometry(g)
                g = mp.UnionCascaded()
            if not g.IsValid():
                # anneaux qui se touchent en un sommet (connexité 8) : correction topologique
                g = g.Buffer(0)
            geoms[k] = g
    finally:
        gdal.PopErrorHandler()
    vds = None
    mem = None
    return geoms


def polygon_perimeter(geom):
    """Périmètre des contours extérieurs (les trous sont ignorés)."""
    total = 0.0
    gt = geom.GetGeometryType()
    polys = [geom] if ogr.GT_Flatten(gt) == ogr.wkbPolygon else [geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]
    for p in polys:
        if p is not None and p.GetGeometryCount():
            total += p.GetGeometryRef(0).Length()
    return total


def write_polygons(path, layer, wkt, fields, records):
    """records : liste de (géométrie OGR, dict d'attributs)."""
    ds = _open_gpkg(path)
    lyr = _create_layer(ds, layer, wkt, ogr.wkbMultiPolygon, fields)
    lyr.StartTransaction()
    for g, attrs in records:
        if ogr.GT_Flatten(g.GetGeometryType()) == ogr.wkbPolygon:
            g = ogr.ForceToMultiPolygon(g)
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(g)
        _set_attrs(f, attrs)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None
    return path


def contours(grid, path, layer, interval, base=0.0, master_every=5):
    """Courbes de niveau (GDAL) avec un champ « maitresse » (1 = courbe maîtresse)."""
    nr, nc = grid.nrows, grid.ncols
    mem = gdal.GetDriverByName("MEM").Create("", nc, nr, 1, gdal.GDT_Float64)
    mem.SetGeoTransform(grid.gt)
    if grid.wkt:
        mem.SetProjection(grid.wkt)
    b = mem.GetRasterBand(1)
    b.WriteArray(np.where(np.isnan(grid.z), -99999.0, grid.z))
    b.SetNoDataValue(-99999.0)
    ds = _open_gpkg(path)
    lyr = _create_layer(ds, layer, grid.wkt, ogr.wkbLineString,
                        [("id", int), ("altitude", float), ("maitresse", int)])
    gdal.ContourGenerate(b, float(interval), float(base), [], 1, -99999.0, lyr, 0, 1)
    master = float(interval) * int(master_every)
    lyr.StartTransaction()
    lyr.ResetReading()
    feats = [f for f in lyr]
    for f in feats:
        alt = f.GetField("altitude")
        is_master = 1 if master > 0 and abs(((alt - base) / master) - round((alt - base) / master)) < 1e-6 else 0
        f.SetField("maitresse", is_master)
        lyr.SetFeature(f)
    lyr.CommitTransaction()
    count = lyr.GetFeatureCount()
    ds = None
    mem = None
    return path, count


def read_points(path, layer=None, selected_fids=None):
    """Lit les points d'une couche OGR : liste de (x, y, fid)."""
    ds = ogr.Open(path)
    if ds is None:
        raise IOError("Couche illisible : {}".format(path))
    lyr = ds.GetLayerByName(layer) if layer else ds.GetLayer(0)
    out = []
    for f in lyr:
        if selected_fids is not None and f.GetFID() not in selected_fids:
            continue
        g = f.GetGeometryRef()
        if g is None:
            continue
        g = g.Centroid() if g.GetGeometryType() != ogr.wkbPoint else g
        out.append((g.GetX(), g.GetY(), f.GetFID()))
    ds = None
    return out
