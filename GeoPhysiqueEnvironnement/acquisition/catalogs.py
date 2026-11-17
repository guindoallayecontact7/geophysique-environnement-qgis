# -*- coding: utf-8 -*-
"""Catalogues en ligne et sources de données (MNT, Landsat, Sentinel, ALOS PALSAR).

Chaque scène est un dict :
    id, title, source, date (AAAA-MM-JJ), datetime, cloud (% ou None), geometry (GeoJSON, WGS 84),
    assets {clé: {href, title, type, size}}, properties (métadonnées brutes), platform.

Les catalogues STAC publics (Microsoft Planetary Computer, Earth Search) ne demandent aucun compte.
Copernicus Data Space, NASA Earthdata (ASF, LP DAAC) et USGS M2M demandent un compte gratuit :
les identifiants sont lus dans le gestionnaire d'authentification de QGIS, jamais écrits sur disque
par l'extension.
"""
import json
import re

from . import http as H

# --------------------------------------------------------------------------- catalogues
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_SAS_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{}"
ES_STAC = "https://earth-search.aws.element84.com/v1"
CDSE_STAC = "https://stac.dataspace.copernicus.eu/v1"
CDSE_ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
CDSE_DOWNLOAD = "https://download.dataspace.copernicus.eu/odata/v1/Products({})/$value"
CDSE_IDENTITY = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ASF_SEARCH = "https://api.daac.asf.alaska.edu/services/search/param"
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
USGS_M2M = "https://m2m.cr.usgs.gov/api/api/json/stable/"

EARTHDATA_DOMAINS = ["earthdata.nasa.gov", "earthdatacloud.nasa.gov", "asf.alaska.edu"]
CDSE_DOMAINS = ["dataspace.copernicus.eu"]

ACCOUNTS = {
    "cdse": ("Copernicus Data Space", "Identifiant (courriel) et mot de passe du compte "
             "https://dataspace.copernicus.eu"),
    "earthdata": ("NASA Earthdata (ASF, LP DAAC)", "Mot de passe = jeton personnel créé sur "
                  "https://urs.earthdata.nasa.gov (Generate Token) ; identifiant libre"),
    "usgs": ("USGS EarthExplorer (M2M)", "Identifiant USGS et jeton d'application M2M "
             "(https://ers.cr.usgs.gov, Application Token), accès M2M à demander une fois"),
}


def _date(s):
    return (s or "")[:10]


# --------------------------------------------------------------------------- STAC
class StacCatalog:
    name = "STAC"
    base = ""
    max_page = 100

    def search(self, src, aoi, start, end, cloud_max, limit, creds, fb):
        body = {"collections": [src["collection"]], "bbox": aoi["bbox"], "limit": min(limit, self.max_page)}
        if src.get("dated", True):
            body["datetime"] = "{}T00:00:00Z/{}T23:59:59Z".format(start, end)
        query = {}
        if src.get("cloud") and cloud_max < 100:
            query["eo:cloud_cover"] = {"lte": cloud_max}
        if src.get("platforms"):
            query["platform"] = {"in": src["platforms"]}
        if query:
            body["query"] = query
        if src.get("sort", True) and src.get("dated", True):
            body["sortby"] = [{"field": "properties.datetime", "direction": "desc"}]
        url = self.base + "/search"
        out = []
        sess = H.session()
        method_post = True
        while url and len(out) < limit:
            fb.check()
            d = H.post_json(url, body, sess=sess) if method_post else H.get_json(url, sess=sess)
            for f in d.get("features", []):
                out.append(self.to_scene(src, f))
            url = None
            for link in d.get("links", []):
                if link.get("rel") == "next":
                    url = link.get("href")
                    if link.get("method", "GET").upper() == "POST":
                        body = link.get("body") or body
                        method_post = True
                    else:
                        method_post = False
                    break
        return out[:limit]

    def to_scene(self, src, f):
        p = f.get("properties", {})
        assets = {}
        for k, a in f.get("assets", {}).items():
            href = self.fix_href(a.get("href", ""))
            if not href.startswith("http"):
                continue
            assets[k] = {"href": href, "title": a.get("title") or k, "type": a.get("type", ""),
                         "size": a.get("file:size") or 0, "roles": a.get("roles", [])}
        return {"id": f.get("id"), "title": f.get("id"), "source": src["id"],
                "date": _date(p.get("datetime") or p.get("start_datetime")),
                "datetime": p.get("datetime") or p.get("start_datetime") or "",
                "cloud": p.get("eo:cloud_cover"), "geometry": f.get("geometry"),
                "assets": assets, "properties": p, "platform": p.get("platform", "")}

    def fix_href(self, href):
        return href

    def resolve(self, scene, key, creds, sess):
        """Renvoie (url, en-têtes, domaines autorisés pour ces en-têtes)."""
        return scene["assets"][key]["href"], None, None


class PlanetaryComputer(StacCatalog):
    name = "Microsoft Planetary Computer"
    base = PC_STAC

    def __init__(self):
        self._tokens = {}

    def sign(self, href, collection, sess):
        if "blob.core.windows.net" not in href or "?" in href:
            return href
        tok = self._tokens.get(collection)
        if tok is None:
            tok = H.get_json(PC_SAS_URL.format(collection), sess=sess)["token"]
            self._tokens[collection] = tok
        return href + "?" + tok

    def resolve(self, scene, key, creds, sess):
        coll = scene["properties"].get("_collection") or scene.get("collection")
        return self.sign(scene["assets"][key]["href"], coll, sess), None, None

    def to_scene(self, src, f):
        s = super().to_scene(src, f)
        s["collection"] = src["collection"]
        return s


class EarthSearch(StacCatalog):
    name = "Earth Search (Element 84, AWS)"
    base = ES_STAC

    def fix_href(self, href):
        m = re.match(r"s3://(copernicus-dem-(?:30|90)m)/(.*)", href)
        if m:
            return "https://{}.s3.amazonaws.com/{}".format(m.group(1), m.group(2))
        return href


class CopernicusDataSpace(StacCatalog):
    """Recherche STAC publique ; téléchargement du produit complet (.SAFE zippé) avec un compte."""

    name = "Copernicus Data Space Ecosystem"
    base = CDSE_STAC

    def to_scene(self, src, f):
        s = super().to_scene(src, f)
        s["assets"] = {"produit": {"href": "", "title": "Produit complet (zip SAFE)", "type": "application/zip",
                                   "size": 0, "roles": ["data"]}}
        return s

    def token(self, creds, sess):
        if not creds or not creds.get("username") or not creds.get("password"):
            raise H.HttpError("Compte Copernicus Data Space non configuré (rubrique Acquisition, « Comptes »).")
        if creds.get("_token"):
            return creds["_token"]
        d = H.post_form(CDSE_IDENTITY, {"grant_type": "password", "username": creds["username"],
                                        "password": creds["password"], "client_id": "cdse-public"}, sess=sess)
        creds["_token"] = d["access_token"]
        return creds["_token"]

    def resolve(self, scene, key, creds, sess):
        tok = self.token(creds, sess)
        flt = "startswith(Name,'{}')".format(scene["id"].replace("'", ""))
        d = H.get_json(CDSE_ODATA, params={"$filter": flt, "$top": 1}, sess=sess)
        vals = d.get("value") or []
        if not vals:
            raise H.HttpError("Produit introuvable dans le catalogue Copernicus : {}".format(scene["id"]))
        scene["assets"][key]["size"] = vals[0].get("ContentLength") or 0
        scene["assets"][key]["filename"] = vals[0]["Name"].replace(".SAFE", "") + ".zip"
        return CDSE_DOWNLOAD.format(vals[0]["Id"]), {"Authorization": "Bearer " + tok}, CDSE_DOMAINS


# --------------------------------------------------------------------------- NASA / ASF
def _earthdata_headers(creds):
    if not creds or not creds.get("password"):
        raise H.HttpError("Compte NASA Earthdata non configuré : créez un jeton sur urs.earthdata.nasa.gov "
                          "et enregistrez-le dans « Comptes ».")
    return {"Authorization": "Bearer " + creds["password"]}


class AsfVertex:
    name = "ASF Vertex (Alaska Satellite Facility)"

    def search(self, src, aoi, start, end, cloud_max, limit, creds, fb):
        w, s, e, n = aoi["bbox"]
        params = {"platform": src["platform"], "bbox": "{},{},{},{}".format(w, s, e, n), "output": "geojson",
                  "maxResults": limit, "start": start + "T00:00:00Z", "end": end + "T23:59:59Z"}
        if src.get("level"):
            params["processingLevel"] = src["level"]
        d = H.get_json(ASF_SEARCH, params=params)
        out = []
        for f in d.get("features", []):
            p = f.get("properties", {})
            size = 0
            b = p.get("bytes")
            if isinstance(b, (int, float)):
                size = int(b)
            name = p.get("fileName") or (p.get("url", "").rsplit("/", 1)[-1])
            out.append({"id": p.get("fileID") or p.get("sceneName"), "title": p.get("sceneName") or name,
                        "source": src["id"], "date": _date(p.get("startTime")), "datetime": p.get("startTime", ""),
                        "cloud": None, "geometry": f.get("geometry"), "platform": p.get("platform", ""),
                        "assets": {"produit": {"href": p.get("url", ""), "title": name, "type": "application/zip",
                                               "size": size, "roles": ["data"]}},
                        "properties": p})
        return out

    def resolve(self, scene, key, creds, sess):
        return scene["assets"][key]["href"], _earthdata_headers(creds), EARTHDATA_DOMAINS


class NasaCmr:
    """Granules LP DAAC (SRTM GL1, ASTER GDEM) trouvés par le Common Metadata Repository."""

    name = "NASA Earthdata (CMR, LP DAAC)"

    def search(self, src, aoi, start, end, cloud_max, limit, creds, fb):
        w, s, e, n = aoi["bbox"]
        params = {"short_name": src["short_name"], "version": src["version"],
                  "bounding_box": "{},{},{},{}".format(w, s, e, n), "page_size": min(limit, 2000)}
        d = H.get_json(CMR_GRANULES, params=params)
        out = []
        for g in d.get("feed", {}).get("entry", []):
            assets = {}
            for link in g.get("links", []):
                href = link.get("href", "")
                if not link.get("rel", "").endswith("/data#") or not href.startswith("https"):
                    continue
                base = href.rsplit("/", 1)[-1]
                if base.endswith(".cmr.xml"):
                    continue
                key = "num" if base.endswith("_num.tif") else "mnt"
                assets[key] = {"href": href, "title": base, "type": "", "size": 0, "roles": ["data"]}
            out.append({"id": g.get("title"), "title": g.get("title"), "source": src["id"],
                        "date": _date(g.get("time_start")), "datetime": g.get("time_start", ""), "cloud": None,
                        "geometry": _cmr_geometry(g), "platform": src["short_name"], "assets": assets,
                        "properties": {k: v for k, v in g.items() if k != "links"}})
        return out

    def resolve(self, scene, key, creds, sess):
        return scene["assets"][key]["href"], _earthdata_headers(creds), EARTHDATA_DOMAINS


def _cmr_geometry(g):
    if g.get("boxes"):
        s, w, n, e = [float(v) for v in g["boxes"][0].split()]
        return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    if g.get("polygons"):
        v = [float(x) for x in g["polygons"][0][0].split()]
        ring = [[v[i + 1], v[i]] for i in range(0, len(v), 2)]
        return {"type": "Polygon", "coordinates": [ring]}
    return None


# --------------------------------------------------------------------------- USGS M2M
class UsgsM2M:
    """USGS EarthExplorer par l'API Machine-to-Machine (compte et jeton d'application)."""

    name = "USGS EarthExplorer (M2M)"

    def __init__(self):
        self._key = None

    def login(self, creds, sess):
        if self._key:
            return self._key
        if not creds or not creds.get("username") or not creds.get("password"):
            raise H.HttpError("Compte USGS non configuré (identifiant + jeton d'application M2M).")
        d = H.post_json(USGS_M2M + "login-token", {"username": creds["username"], "token": creds["password"]},
                        sess=sess)
        if d.get("errorCode"):
            raise H.HttpError("USGS : {}".format(d.get("errorMessage")))
        self._key = d["data"]
        return self._key

    def call(self, endpoint, body, creds, sess):
        key = self.login(creds, sess)
        d = H.post_json(USGS_M2M + endpoint, body, headers={"X-Auth-Token": key}, sess=sess)
        if d.get("errorCode"):
            raise H.HttpError("USGS {} : {}".format(endpoint, d.get("errorMessage")))
        return d.get("data")

    def search(self, src, aoi, start, end, cloud_max, limit, creds, fb):
        sess = H.session()
        w, s, e, n = aoi["bbox"]
        flt = {"spatialFilter": {"filterType": "mbr", "lowerLeft": {"latitude": s, "longitude": w},
                                 "upperRight": {"latitude": n, "longitude": e}},
               "acquisitionFilter": {"start": start, "end": end}}
        if src.get("cloud"):
            flt["cloudCoverFilter"] = {"min": 0, "max": int(cloud_max), "includeUnknown": False}
        data = self.call("scene-search", {"datasetName": src["dataset"], "maxResults": limit,
                                          "sceneFilter": flt}, creds, sess)
        out = []
        for r in (data or {}).get("results", []):
            date = _date((r.get("temporalCoverage") or {}).get("startDate"))
            cc = r.get("cloudCover")
            try:
                cc = float(cc)
                cc = None if cc < 0 else cc
            except (TypeError, ValueError):
                cc = None
            out.append({"id": r.get("entityId"), "title": r.get("displayId") or r.get("entityId"),
                        "source": src["id"], "date": date, "datetime": date, "cloud": cc,
                        "geometry": r.get("spatialCoverage"), "platform": src["dataset"],
                        "assets": {"produit": {"href": "", "title": "Produit complet (archive)", "type": "",
                                               "size": 0, "roles": ["data"]}},
                        "properties": {k: v for k, v in r.items() if k not in ("browse",)}})
        return out

    def resolve(self, scene, key, creds, sess):
        ds = scene["platform"]
        opts = self.call("download-options", {"datasetName": ds, "entityIds": [scene["id"]]}, creds, sess) or []
        opts = [o for o in opts if o.get("available") and o.get("downloadSystem") != "folder"]
        if not opts:
            raise H.HttpError("Aucun téléchargement disponible chez l'USGS pour {}".format(scene["title"]))
        best = max(opts, key=lambda o: o.get("filesize") or 0)
        req = self.call("download-request", {"downloads": [{"entityId": scene["id"], "productId": best["id"]}],
                                             "label": "tgs"}, creds, sess) or {}
        avail = req.get("availableDownloads") or []
        if not avail:
            raise H.HttpError("L'USGS prépare le fichier de {} : relancez le téléchargement dans quelques "
                              "minutes.".format(scene["title"]))
        scene["assets"][key]["size"] = best.get("filesize") or 0
        return avail[0]["url"], None, None


# --------------------------------------------------------------------------- sources
CATALOGS = {"pc": PlanetaryComputer(), "es": EarthSearch(), "cdse": CopernicusDataSpace(), "asf": AsfVertex(),
            "cmr": NasaCmr(), "usgs": UsgsM2M()}

# kind : MNT, Optique, Radar ; res en mètres ; cog : lecture partielle possible (découpe sans tout télécharger)
SOURCES = [
    # ---- MNT
    dict(id="cop30", label="Copernicus DEM GLO-30", kind="MNT", res=30, catalog="pc", collection="cop-dem-glo-30",
         dated=False, assets=["data"], cog=True),
    dict(id="cop90", label="Copernicus DEM GLO-90", kind="MNT", res=90, catalog="pc", collection="cop-dem-glo-90",
         dated=False, assets=["data"], cog=True),
    dict(id="cop30_es", label="Copernicus DEM GLO-30 (miroir AWS)", kind="MNT", res=30, catalog="es",
         collection="cop-dem-glo-30", dated=False, assets=["data"], cog=True),
    dict(id="nasadem", label="NASADEM (SRTM retraité)", kind="MNT", res=30, catalog="pc", collection="nasadem",
         dated=False, assets=["elevation"], cog=True),
    dict(id="srtm", label="SRTM GL1 v3 (1 seconde d'arc)", kind="MNT", res=30, catalog="cmr", short_name="SRTMGL1",
         version="003", dated=False, assets=["mnt"], cog=False, auth="earthdata"),
    dict(id="aster", label="ASTER GDEM v3", kind="MNT", res=30, catalog="cmr", short_name="ASTGTM",
         version="003", dated=False, assets=["mnt"], cog=False, auth="earthdata"),
    dict(id="alosdem", label="ALOS World 3D AW3D30", kind="MNT", res=30, catalog="pc", collection="alos-dem",
         dated=False, assets=["data"], cog=True),
    # ---- Optique
    dict(id="s2", label="Sentinel-2 L2A (réflectance de surface)", kind="Optique", res=10, catalog="pc",
         collection="sentinel-2-l2a", cloud=True, assets=["B02", "B03", "B04", "B08"], cog=True),
    dict(id="s2_es", label="Sentinel-2 L2A (miroir AWS)", kind="Optique", res=10, catalog="es",
         collection="sentinel-2-c1-l2a", cloud=True, assets=["blue", "green", "red", "nir"], cog=True),
    dict(id="s2_cdse", label="Sentinel-2 L2A, produit SAFE complet", kind="Optique", res=10, catalog="cdse",
         collection="sentinel-2-l2a", cloud=True, assets=["produit"], cog=False, auth="cdse"),
    dict(id="l89", label="Landsat 8 et 9 C2 L2", kind="Optique", res=30, catalog="pc", collection="landsat-c2-l2",
         platforms=["landsat-8", "landsat-9"], cloud=True,
         assets=["blue", "green", "red", "nir08", "swir16", "swir22"], cog=True),
    dict(id="l7", label="Landsat 7 ETM+ C2 L2", kind="Optique", res=30, catalog="pc", collection="landsat-c2-l2",
         platforms=["landsat-7"], cloud=True, assets=["blue", "green", "red", "nir08", "swir16", "swir22"], cog=True),
    dict(id="l5", label="Landsat 4 et 5 TM C2 L2", kind="Optique", res=30, catalog="pc", collection="landsat-c2-l2",
         platforms=["landsat-4", "landsat-5"], cloud=True,
         assets=["blue", "green", "red", "nir08", "swir16", "swir22"], cog=True),
    dict(id="l89_usgs", label="Landsat 8 et 9 C2 L2, archive USGS", kind="Optique", res=30, catalog="usgs",
         dataset="landsat_ot_c2_l2", cloud=True, assets=["produit"], cog=False, auth="usgs"),
    dict(id="l7_usgs", label="Landsat 7 C2 L2, archive USGS", kind="Optique", res=30, catalog="usgs",
         dataset="landsat_etm_c2_l2", cloud=True, assets=["produit"], cog=False, auth="usgs"),
    dict(id="l5_usgs", label="Landsat 4 et 5 C2 L2, archive USGS", kind="Optique", res=30, catalog="usgs",
         dataset="landsat_tm_c2_l2", cloud=True, assets=["produit"], cog=False, auth="usgs"),
    dict(id="s3", label="Sentinel-3 OLCI L2 terres (NetCDF)", kind="Optique", res=300, catalog="pc",
         collection="sentinel-3-olci-lfr-l2-netcdf", assets=["gifapar", "otci", "iwv"], cog=False),
    # ---- Radar
    dict(id="s1rtc", label="Sentinel-1 RTC (rétrodiffusion corrigée)", kind="Radar", res=10, catalog="pc",
         collection="sentinel-1-rtc", assets=["vv", "vh"], cog=True),
    dict(id="s1grd", label="Sentinel-1 GRD", kind="Radar", res=10, catalog="pc", collection="sentinel-1-grd",
         assets=["vv", "vh"], cog=True),
    dict(id="s1_cdse", label="Sentinel-1 GRD, produit SAFE complet", kind="Radar", res=10, catalog="cdse",
         collection="sentinel-1-grd", assets=["produit"], cog=False, auth="cdse"),
    dict(id="palsar_mos", label="ALOS PALSAR mosaïque annuelle (HH, HV)", kind="Radar", res=25, catalog="pc",
         collection="alos-palsar-mosaic", dated=False, assets=["HH", "HV"], cog=True),
    dict(id="palsar_rtc", label="ALOS PALSAR RTC 12,5 m (ASF)", kind="Radar", res=12.5, catalog="asf",
         platform="ALOS", level="RTC_HI_RES", assets=["produit"], cog=False, auth="earthdata"),
    dict(id="palsar_l15", label="ALOS PALSAR niveau 1.5 (ASF)", kind="Radar", res=12.5, catalog="asf",
         platform="ALOS", level="L1.5", assets=["produit"], cog=False, auth="earthdata"),
]
SOURCE_BY_ID = {s["id"]: s for s in SOURCES}


def source_line(src):
    cat = CATALOGS[src["catalog"]].name
    acc = " - compte {}".format(ACCOUNTS[src["auth"]][0]) if src.get("auth") else ""
    return "{} ({:g} m) - {}{}".format(src["label"], src["res"], cat, acc)


def metadata_text(scene):
    """Métadonnées lisibles (JSON indenté) d'une scène."""
    keep = {k: scene[k] for k in ("id", "title", "source", "datetime", "cloud", "platform")}
    keep["fichiers"] = {k: {"titre": a["title"], "url": a["href"], "taille": H.human_size(a.get("size"))}
                        for k, a in scene["assets"].items()}
    keep["propriétés"] = scene.get("properties", {})
    return json.dumps(keep, indent=2, ensure_ascii=False, default=str)
