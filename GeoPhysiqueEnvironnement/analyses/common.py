# -*- coding: utf-8 -*-
"""Contexte de session partagé par les chaînes de traitement."""
import datetime
import os
import tempfile

import numpy as np

from ..core import grid as G
from ..core import hydrology as hy
from ..engines.results import AnalysisResult, MODULE_DIRS


class HydroState:
    """Résultat hydrologique réutilisable par les modules bassins et sous-bassins."""

    def __init__(self, key, grid, filled, model, acc_d8, net, params):
        self.key = key
        self.grid = grid
        self.filled = filled
        self.model = model
        self.acc_d8 = acc_d8
        self.net = net
        self.params = params
        self._edge = None

    @property
    def edge(self):
        if self._edge is None:
            self._edge = G.edge_mask(self.grid.valid)
        return self._edge


class Context:
    """Espace de travail, cache des MNT et de l'état hydrologique."""

    def __init__(self, workspace=None):
        self.workspace = workspace or os.path.join(tempfile.gettempdir(), "GeoPhysique_travail")
        self._grid_key = None
        self._grid = None
        self.hydro = None
        self.last_basin = None   # dict : labels, ids, outlets, rows, grid key

    def module_dir(self, module, stamp=None):
        stamp = stamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        d = os.path.join(self.workspace, MODULE_DIRS[module], stamp)
        os.makedirs(d, exist_ok=True)
        return d

    def grid(self, path, band=1):
        key = (os.path.abspath(path), band, os.path.getmtime(path))
        if key != self._grid_key:
            self._grid = G.read_dem(path, band)
            self._grid_key = key
        return self._grid

    def clear(self):
        self._grid_key = self._grid = None
        self.hydro = None
        self.last_basin = None


def new_result(module, title, grid, zfactor=1.0):
    r = AnalysisResult(module, title, dem_source=grid.source, crs=grid.crs_description(),
                       resolution="{:g} × {:g} m".format(grid.dx, grid.dy))
    if zfactor != 1.0:
        r.add_param("Facteur Z", zfactor, "")
    return r


def check_grid(grid, result=None, require_projected=True):
    """Contrôles préalables ; lève ValueError sur erreur bloquante."""
    checks = G.validate_dem(grid)
    errors = [c for c in checks if c["niveau"] == "erreur"]
    if result is not None:
        for c in checks:
            if c["niveau"] == "avertissement":
                result.warnings.append("{} : {}".format(c["controle"], c["message"]))
    if errors and require_projected:
        raise ValueError("MNT non conforme :\n" + "\n".join("- {} : {}".format(c["controle"], c["message"])
                                                            for c in errors))
    return checks


def hydro_key(grid, p):
    md = p.get("max_depth") if p.get("fill", "fill") == "fill_depth" else None
    return (grid.source, grid.band, p.get("fill", "fill"), md)


def ensure_hydro(ctx, grid, p, feedback, progress=(0, 60)):
    """Calcule (ou réutilise) comblement, directions D8, accumulation D8 et réseau."""
    key = hydro_key(grid, p)
    thr = p.get("threshold_cells") or suggest_threshold_cells(grid)
    st = ctx.hydro
    if st is not None and st.key == key and st.grid is grid:
        feedback.info("Réutilisation des directions d'écoulement de la session.")
        if st.net.threshold_cells != thr:
            feedback.info("Nouvelle extraction du réseau (seuil {:g} cellules)…".format(thr))
            st.net = hy.extract_streams(st.model, st.acc_d8, thr, feedback)
            st.params["threshold_cells"] = thr
        return st
    a, b = progress
    fill = p.get("fill", "fill")
    valid = grid.valid
    if fill == "none":
        feedback.info("Dépressions conservées (aucune correction).")
        filled, sinks = grid.z.copy(), None
    else:
        md = p.get("max_depth") if fill == "fill_depth" else None
        feedback.info("Comblement des dépressions{}…".format(
            "" if md is None else " (profondeur max. {} m)".format(md)))
        sub = G.Feedback(lambda v: feedback.progress(a + (b - a) * 0.5 * v / 100.0),
                         feedback.info, feedback.is_canceled)
        filled, sinks, _ = hy.fill_depressions(grid.z, valid, grid.dx, grid.dy, md, sub)
    feedback.check()
    feedback.progress(a + (b - a) * 0.5)
    feedback.info("Directions d'écoulement D8 et tri topologique…")
    model = hy.route_d8(filled, valid, grid.dx, grid.dy, sinks, feedback)
    feedback.progress(a + (b - a) * 0.8)
    acc = hy.accumulate_d8(model)
    feedback.info("Extraction du réseau (seuil {:g} cellules)…".format(thr))
    net = hy.extract_streams(model, acc, thr, feedback)
    feedback.progress(b)
    ctx.hydro = HydroState(key, grid, filled, model, acc, net, dict(p, threshold_cells=thr))
    return ctx.hydro


def suggest_threshold_cells(grid):
    """Seuil de départ : 1/2000 de la surface valide, au moins 50 cellules.

    Ce n'est pas une valeur « universelle » : il dépend de l'emprise et de la
    résolution du MNT et doit être ajusté (densité de drainage observée,
    cartes topographiques, terrain).
    """
    nvalid = int(grid.valid.sum())
    return float(max(50, round(nvalid / 2000.0)))


def cells_to_km2(cells, grid):
    return cells * grid.dx * grid.dy / 1e6


def km2_to_cells(km2, grid):
    return km2 * 1e6 / (grid.dx * grid.dy)


class TaskFeedback(G.Feedback):
    """Retour de progression branché sur une tâche (fonctions passées par l'interface)."""

    pass


def masked(arr, mask):
    out = np.array(arr, dtype=np.float64, copy=True)
    out[~mask] = np.nan
    return out
