# -*- coding: utf-8 -*-
"""Accès HTTP : requêtes JSON et téléchargements reprenables (fichier .part + en-tête Range)."""
import os
import time
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # requests est fourni avec QGIS ; message clair sinon
    requests = None

USER_AGENT = "TGS-TerraGeoScience-QGIS"
TIMEOUT = (30, 120)
CHUNK = 1 << 20


class HttpError(Exception):
    pass


def _need():
    if requests is None:
        raise HttpError("Le module Python « requests » est absent de cette installation de QGIS.")


def session():
    _need()
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _check(r, url):
    if r.status_code in (401, 403):
        raise HttpError("Accès refusé ({}) par {}. Vérifiez l'identifiant du compte dans « Comptes ».".format(
            r.status_code, urlparse(url).netloc))
    if r.status_code >= 400:
        txt = r.text[:300].replace("\n", " ") if r.text else ""
        raise HttpError("Erreur {} sur {} : {}".format(r.status_code, urlparse(url).netloc, txt))


def _request(method, url, sess=None, tries=3, **kw):
    """Requête avec nouvel essai après une coupure réseau ou une erreur 5xx passagère."""
    s = sess or session()
    for attempt in range(tries):
        try:
            r = s.request(method, url, timeout=TIMEOUT, **kw)
            if r.status_code in (429, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 + 3 * attempt)
                continue
            _check(r, url)
            return r.json()
        except (requests.ConnectionError, requests.Timeout):
            if attempt >= tries - 1:
                raise
            time.sleep(2 + 3 * attempt)
    return None


def get_json(url, params=None, headers=None, sess=None):
    return _request("GET", url, sess=sess, params=params, headers=headers)


def post_json(url, body, headers=None, sess=None):
    return _request("POST", url, sess=sess, json=body, headers=headers)


def post_form(url, data, sess=None):
    return _request("POST", url, sess=sess, tries=1, data=data)


def _host_ok(url, domains):
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in domains)


def _open(s, url, headers, auth_domains, pos):
    """GET en suivant les redirections ; l'en-tête d'authentification n'est renvoyé qu'aux domaines prévus."""
    for _ in range(10):
        h = {}
        if headers and (not auth_domains or _host_ok(url, auth_domains)):
            h.update(headers)
        if pos:
            h["Range"] = "bytes={}-".format(pos)
        r = s.get(url, headers=h, stream=True, timeout=TIMEOUT, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = requests.compat.urljoin(url, r.headers["Location"])
            r.close()
            continue
        return r, url
    raise HttpError("Trop de redirections pour {}".format(url))


def download(url, dest, headers=None, auth_domains=None, feedback=None, progress=None, sess=None, retries=4):
    """Télécharge `url` dans `dest`, reprend un fichier .part existant, réessaie après coupure.

    progress(octets_reçus, octets_totaux_ou_0) est appelé régulièrement.
    """
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    s = sess or session()
    part = dest + ".part"
    for attempt in range(retries + 1):
        pos = os.path.getsize(part) if os.path.exists(part) else 0
        try:
            r, final = _open(s, url, headers, auth_domains, pos)
            with r:
                if r.status_code == 416 and pos:   # fichier déjà complet
                    break
                _check(r, final)
                mode = "ab" if (pos and r.status_code == 206) else "wb"
                if mode == "wb":
                    pos = 0
                total = int(r.headers.get("Content-Length") or 0)
                total = total + pos if total else 0
                got = pos
                last = 0.0
                with open(part, mode) as f:
                    for chunk in r.iter_content(CHUNK):
                        if feedback is not None:
                            feedback.check()
                        if chunk:
                            f.write(chunk)
                            got += len(chunk)
                            now = time.time()
                            if progress and now - last > 0.3:
                                progress(got, total)
                                last = now
                if total and got < total:
                    raise HttpError("Téléchargement incomplet ({} / {} octets)".format(got, total))
                if progress:
                    progress(got, total)
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError,
                HttpError) as exc:
            if isinstance(exc, HttpError) and "incomplet" not in str(exc):
                raise
            if attempt >= retries:
                raise HttpError("Téléchargement interrompu après {} essais : {}. Relancez : il reprendra où il "
                                "s'est arrêté.".format(retries + 1, exc))
            if feedback is not None:
                feedback.info("Connexion interrompue, reprise ({}/{})…".format(attempt + 1, retries))
            time.sleep(2 + 3 * attempt)
    os.replace(part, dest)
    return dest


def human_size(n):
    if not n:
        return ""
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return "{:.0f} {}".format(n, unit)
        n /= 1024.0
    return "{:.1f} To".format(n)
