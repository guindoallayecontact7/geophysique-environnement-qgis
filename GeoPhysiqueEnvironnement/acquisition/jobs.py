# -*- coding: utf-8 -*-
"""Recherche et téléchargement exécutés en tâche de fond : fn(params, ctx, feedback).

Découpe et reprojection par GDAL (gdal.Warp). Pour les sources COG, seule la zone d'étude est lue
à distance (/vsicurl/) : on ne télécharge pas la scène entière.
"""
import datetime
import json
import math
import os
import re

from osgeo import gdal, ogr, osr

from . import http as H
from .catalogs import CATALOGS, SOURCE_BY_ID

RASTER_EXT = (".tif", ".tiff", ".jp2", ".hgt", ".img", ".nc")


# --------------------------------------------------------------------------- zone d'étude
def utm_epsg(lon, lat):
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def coverage(scene_geom, aoi_geom):
    """Part de la zone d'étude couverte par l'emprise de la scène (%)."""
    if scene_geom is None or aoi_geom is None:
        return None
    try:
        g = ogr.CreateGeometryFromJson(json.dumps(scene_geom))
        if g is None:
            return None
        if not g.IsValid():
            g = g.Buffer(0)
        inter = g.Intersection(aoi_geom)
        a = aoi_geom.GetArea()
        return 100.0 * inter.GetArea() / a if a > 0 and inter is not None else None
    except Exception:  # noqa: BLE001 - géométrie de catalogue défectueuse : couverture inconnue
        return None


def _aoi_ogr(aoi):
    g = ogr.CreateGeometryFromWkt(aoi["wkt"])
    return g if g.IsValid() else g.Buffer(0)


# --------------------------------------------------------------------------- recherche
def job_search(params, ctx, fb):
    aoi = params["aoi"]
    aoi_g = _aoi_ogr(aoi)
    scenes, errors = [], []
    ids = params["sources"]
    for i, sid in enumerate(ids):
        fb.check()
        src = SOURCE_BY_ID[sid]
        cat = CATALOGS[src["catalog"]]
        fb.info("Recherche : {} ({})".format(src["label"], cat.name))
        try:
            found = cat.search(src, aoi, params["start"], params["end"], params["cloud_max"], params["limit"],
                               params["creds"].get(src.get("auth")), fb)
        except Exception as exc:  # noqa: BLE001 - une source en panne ne bloque pas les autres
            errors.append("{} : {}".format(src["label"], exc))
            continue
        for s in found:
            s["coverage"] = coverage(s.get("geometry"), aoi_g)
            if s["coverage"] is not None and s["coverage"] < params["min_cover"]:
                continue
            scenes.append(s)
        fb.progress(100.0 * (i + 1) / len(ids))
    scenes.sort(key=lambda s: (s.get("date") or "", s["source"]), reverse=True)
    return {"scenes": scenes, "errors": errors}


# --------------------------------------------------------------------------- traitements raster
def _cb(fb):
    def cb(pct, msg, data):
        return 0 if fb.is_canceled() else 1
    return cb


def _dst_srs(mode, aoi, src_ds_wkt=None, project_wkt=None):
    if mode == "project" and project_wkt:
        return project_wkt
    if mode == "utm":
        w, s, e, n = aoi["bbox"]
        sr = osr.SpatialReference()
        sr.ImportFromEPSG(utm_epsg((w + e) / 2.0, (s + n) / 2.0))
        return sr.ExportToWkt()
    return src_ds_wkt


def _cutline_file(aoi, folder):
    path = os.path.join(folder, "_zone_etude.geojson")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": json.loads(_aoi_ogr(aoi).ExportToJson())}]}, f)
    return path


def warp_to_zone(sources, dest, aoi, srs_mode, project_wkt, cut_shape, fb, resampling="bilinear",
                 nodata=None):
    """Découpe (rectangle ou forme exacte), mosaïque et reprojette `sources` dans `dest` (GeoTIFF tuilé)."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    first = gdal.Open(sources[0])
    if first is None:
        raise RuntimeError("GDAL ne peut pas lire {}".format(sources[0]))
    src_wkt = first.GetProjection()
    first = None
    dst = _dst_srs(srs_mode, aoi, src_wkt, project_wkt)
    w, s, e, n = aoi["bbox"]
    kw = dict(format="GTiff", dstSRS=dst, outputBounds=(w, s, e, n), outputBoundsSRS="EPSG:4326",
              resampleAlg=resampling, multithread=True, callback=_cb(fb),
              creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER", "PREDICTOR=2"])
    if nodata is not None:
        kw["dstNodata"] = nodata
    if cut_shape:
        kw["cutlineDSName"] = _cutline_file(aoi, os.path.dirname(dest))
        kw["cropToCutline"] = False
    tmp = dest + ".tmp.tif"
    ds = gdal.Warp(tmp, sources, **kw)
    if ds is None:
        if fb.is_canceled():
            fb.check()
        raise RuntimeError("Échec de la découpe GDAL : {}".format(gdal.GetLastErrorMsg()))
    ds = None
    if os.path.exists(dest):
        os.remove(dest)
    os.replace(tmp, dest)
    return dest


def _gdal_name(url, headers):
    if headers:
        hdr = "\n".join("{}: {}".format(k, v) for k, v in headers.items())
        gdal.SetConfigOption("GDAL_HTTP_HEADERS", hdr)
    else:
        gdal.SetConfigOption("GDAL_HTTP_HEADERS", None)
    return "/vsicurl/" + url


def _readable(path):
    """Chemin GDAL d'un raster téléchargé (y compris un .hgt dans un zip), ou None."""
    low = path.lower()
    if low.endswith(".zip"):
        try:
            import zipfile
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if n.lower().endswith((".hgt", ".tif", ".tiff")):
                        return "/vsizip/{}/{}".format(path.replace("\\", "/"), n)
        except Exception:  # noqa: BLE001 - archive illisible : pas de découpe
            return None
        return None
    if low.endswith(RASTER_EXT):
        return path
    return None


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]


def _ext(url, a):
    base = url.split("?")[0].rsplit("/", 1)[-1]
    if "." in base and len(base.rsplit(".", 1)[1]) <= 5:
        return "." + base.rsplit(".", 1)[1]
    t = a.get("type", "")
    if "tiff" in t:
        return ".tif"
    if "zip" in t:
        return ".zip"
    if "netcdf" in t:
        return ".nc"
    return ".bin"


# --------------------------------------------------------------------------- téléchargement
def job_download(params, ctx, fb):
    """Télécharge les scènes cochées.

    params : scenes, assets (clés choisies), mode (« zone » ou « complet »), clip_after, srs_mode,
             project_wkt, cut_shape, mosaic_dem, folder, aoi, creds.
    """
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "4")
    gdal.SetConfigOption("GDAL_HTTP_RETRY_DELAY", "3")
    gdal.SetConfigOption("CPL_VSIL_CURL_USE_HEAD", "NO")
    try:
        return _download(params, fb)
    finally:
        gdal.SetConfigOption("GDAL_HTTP_HEADERS", None)


def _download(params, fb):
    aoi, scenes = params["aoi"], params["scenes"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    root = params["folder"]
    sess = H.session()
    outputs, rasters, errors, dem_parts = [], [], [], {}
    jobs = []
    for sc in scenes:
        src = SOURCE_BY_ID[sc["source"]]
        keys = [k for k in params["assets"].get(sc["source"], []) if k in sc["assets"]] or \
            [k for k in src["assets"] if k in sc["assets"]]
        for k in keys:
            jobs.append((sc, src, k))
    if not jobs:
        raise RuntimeError("Aucun fichier à télécharger : cochez au moins une scène et une bande.")
    n = len(jobs)
    for i, (sc, src, key) in enumerate(jobs):
        fb.check()
        base_pct = 100.0 * i / n
        folder = os.path.join(root, _safe(src["id"]), _safe(sc["date"] + "_" + sc["title"]) if sc["date"]
                              else _safe(sc["title"]))
        cat = CATALOGS[src["catalog"]]
        label = "{} / {}".format(sc["title"], key)
        try:
            url, headers, domains = cat.resolve(sc, key, params["creds"].get(src.get("auth")), sess)
            asset = sc["assets"][key]
            zone_mode = params["mode"] == "zone" and src.get("cog")
            if zone_mode and src["kind"] == "MNT" and params.get("mosaic_dem"):
                dem_parts.setdefault(src["id"], []).append(_gdal_name(url, headers))
                fb.progress(base_pct + 100.0 / n)
                continue
            if zone_mode:
                fb.info("Lecture de la zone d'étude : {}".format(label))
                dest = os.path.join(folder, _safe(key) + ".tif")
                warp_to_zone([_gdal_name(url, headers)], dest, aoi, params["srs_mode"], params["project_wkt"],
                             params["cut_shape"], fb, resampling=_resampling(key, src))
                outputs.append(dest)
                rasters.append((dest, "{} {} {}".format(src["label"], sc["date"], key).strip(), src["kind"]))
            else:
                fname = asset.get("filename") or (_safe(key) + _ext(url, asset))
                dest = os.path.join(folder, fname)
                fb.info("Téléchargement : {} ({})".format(label, H.human_size(asset.get("size")) or "taille inconnue"))

                def prog(got, total, b=base_pct):
                    if total:
                        fb.progress(b + (100.0 / n) * got / total)
                H.download(url, dest, headers=headers, auth_domains=domains, feedback=fb, progress=prog, sess=sess)
                outputs.append(dest)
                gname = _readable(dest)
                if gname and params.get("clip_after"):
                    fb.info("Découpe et reprojection : {}".format(os.path.basename(dest)))
                    cut = os.path.splitext(dest)[0] + "_zone.tif"
                    warp_to_zone([gname], cut, aoi, params["srs_mode"], params["project_wkt"],
                                 params["cut_shape"], fb, resampling=_resampling(key, src))
                    outputs.append(cut)
                    rasters.append((cut, "{} {} {}".format(src["label"], sc["date"], key).strip(), src["kind"]))
                elif gname:
                    rasters.append((dest, "{} {}".format(src["label"], sc["title"]), src["kind"]))
            _write_meta(folder, sc)
        except Exception as exc:  # noqa: BLE001 - on poursuit avec les fichiers suivants
            if fb.is_canceled():
                fb.check()
            errors.append("{} : {}".format(label, exc))
            fb.info("✘ {} : {}".format(label, exc))
        fb.progress(base_pct + 100.0 / n)
    for sid, parts in dem_parts.items():
        fb.check()
        src = SOURCE_BY_ID[sid]
        dest = os.path.join(root, _safe(sid), "MNT_{}_{}.tif".format(_safe(sid), stamp))
        fb.info("Mosaïque et découpe du MNT {} ({} dalle(s))…".format(src["label"], len(parts)))
        try:
            warp_to_zone(parts, dest, aoi, params["srs_mode"], params["project_wkt"], params["cut_shape"], fb,
                         resampling="bilinear", nodata=-9999)
            outputs.append(dest)
            rasters.append((dest, "MNT {}".format(src["label"]), "MNT"))
        except Exception as exc:  # noqa: BLE001
            if fb.is_canceled():
                fb.check()
            errors.append("MNT {} : {}".format(src["label"], exc))
    _write_journal(root, stamp, params, outputs, errors)
    return {"outputs": outputs, "rasters": rasters, "errors": errors, "folder": root}


def _resampling(key, src):
    k = key.lower()
    if any(t in k for t in ("qa", "scl", "mask", "cloud", "date", "linci", "num")):
        return "near"
    return "bilinear"


def _write_meta(folder, scene):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "metadonnees.json")
    if os.path.exists(path):
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scene, f, indent=2, ensure_ascii=False, default=str)


def _write_journal(root, stamp, params, outputs, errors):
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "journal_acquisition_{}.txt".format(stamp))
    with open(path, "w", encoding="utf-8") as f:
        f.write("TGS - TerraGeo Science : acquisition du {}\n".format(stamp))
        f.write("Zone d'étude (WGS 84) : {}\n".format(params["aoi"]["bbox"]))
        f.write("Mode : {} ; SCR : {}\n\n".format(params["mode"], params["srs_mode"]))
        for sc in params["scenes"]:
            f.write("Scène {} ({}, {})\n".format(sc["title"], sc["source"], sc["date"]))
        f.write("\nFichiers produits :\n")
        for o in outputs:
            f.write("  {}\n".format(o))
        if errors:
            f.write("\nErreurs :\n")
            for e in errors:
                f.write("  {}\n".format(e))
