# -*- coding: utf-8 -*-
"""Moteur hydrologique natif (NumPy) : dépressions, directions, accumulations,
réseau hydrographique, bassins et sous-bassins.

Les cellules sont repérées par leur indice à plat i = ligne × ncols + colonne.
`rec[i]` donne la cellule réceptrice D8 de i, ou -1 pour une cellule
terminale (sortie de grille, bord NoData ou dépression conservée).

Méthodes et références :
- Comblement : Priority-Flood (Barnes et al. 2014) appliqué au graphe des
  bassins de dépressions, ce qui donne exactement le résultat du
  Priority-Flood cellule par cellule avec moins d'opérations Python.
- Zones planes : écoulement vers le point de déversement le plus proche
  (parcours en largeur sur les cellules de même altitude).
- Directions : D8 (O'Callaghan & Mark 1984), MFD (Freeman 1991),
  D-Infinity (Tarboton 1997).
- Ordres : Strahler (1957), Shreve (1966).
"""
import heapq
import math

import numpy as np
from scipy import ndimage

from .grid import OFFSETS, D8_CODES, Feedback, edge_mask

_OFF = np.array(OFFSETS, dtype=np.int64)


def _dists(dx, dy):
    return np.array([math.hypot(dr * dy, dc * dx) for dr, dc in OFFSETS])


def _neighbours_of(idx, k, nr, nc):
    """Indice du voisin k des cellules idx ; -1 hors grille."""
    r = idx // nc + OFFSETS[k][0]
    c = idx % nc + OFFSETS[k][1]
    ok = (r >= 0) & (r < nr) & (c >= 0) & (c < nc)
    out = np.where(ok, r * nc + c, -1)
    return out


def step_lengths(src, dst, nc, dx, dy):
    dr = dst // nc - src // nc
    dc = dst % nc - src % nc
    return np.hypot(dr * dy, dc * dx)


# --------------------------------------------------------------------------
# D8 brut
# --------------------------------------------------------------------------
def d8_steepest(z, valid, dx, dy):
    """Récepteur D8 de plus grande pente strictement descendante.

    Renvoie (rec, has_lower) à plat ; rec = -1 si aucune voisine plus basse.
    """
    nr, nc = z.shape
    zz = np.where(valid, z, np.nan)
    zp = np.pad(zz, 1, constant_values=np.nan)
    best = np.zeros(z.shape)
    bestk = np.full(z.shape, -1, np.int8)
    dists = _dists(dx, dy)
    with np.errstate(invalid="ignore"):
        for k, (dr, dc) in enumerate(OFFSETS):
            zn = zp[1 + dr:1 + dr + nr, 1 + dc:1 + dc + nc]
            s = (zz - zn) / dists[k]
            upd = s > best
            best[upd] = s[upd]
            bestk[upd] = k
    rec = np.full(nr * nc, -1, np.int64)
    flat_k = bestk.ravel()
    idx = np.flatnonzero(flat_k >= 0)
    offs = _OFF[:, 0] * nc + _OFF[:, 1]
    rec[idx] = idx + offs[flat_k[idx]]
    return rec, flat_k >= 0


def topo_waves(rec, valid_flat, feedback=None, progress_range=None):
    """Tri topologique par vagues (algorithme de Kahn), de l'amont vers l'aval.

    Chaque vague contient les cellules dont tous les donneurs ont été traités.
    """
    n = rec.size
    has = rec >= 0
    indeg = np.bincount(rec[has], minlength=n).astype(np.int32)
    frontier = np.flatnonzero(valid_flat & (indeg == 0))
    waves = []
    done = 0
    total = int(valid_flat.sum())
    while frontier.size:
        waves.append(frontier)
        done += frontier.size
        r = rec[frontier]
        r = r[r >= 0]
        if r.size == 0:
            break
        u, cnt = np.unique(r, return_counts=True)
        indeg[u] -= cnt.astype(np.int32)
        frontier = u[indeg[u] == 0]
        if feedback is not None and len(waves) % 200 == 0:
            feedback.check()
            if progress_range:
                a, b = progress_range
                feedback.progress(a + (b - a) * done / max(total, 1))
    return waves


# --------------------------------------------------------------------------
# Dépressions
# --------------------------------------------------------------------------
def _label_from_terminals(rec, waves, term_idx, term_lab, n):
    lab = np.full(n, -1, np.int64)
    lab[term_idx] = term_lab
    for w in reversed(waves):
        r = rec[w]
        m = r >= 0
        if m.any():
            ww = w[m]
            lab[ww] = lab[r[m]]
    return lab


def _depression_graph(z, valid, edge, lab, nlab):
    """Arêtes (a, b, hauteur de col) entre bassins adjacents ; nœud 0 = extérieur."""
    nr, nc = z.shape
    zf = z.ravel()
    labg = lab.reshape(z.shape)
    keys, heights = [], []
    for dr, dc in ((0, 1), (1, 1), (1, 0), (1, -1)):
        r0, r1 = 0, nr - dr
        c0, c1 = max(0, -dc), nc - max(0, dc)
        a_lab = labg[r0:r1, c0:c1]
        b_lab = labg[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
        a_ok = valid[r0:r1, c0:c1]
        b_ok = valid[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
        m = a_ok & b_ok & (a_lab != b_lab)
        if not m.any():
            continue
        za = z[r0:r1, c0:c1][m]
        zb = z[r0 + dr:r1 + dr, c0 + dc:c1 + dc][m]
        la, lb = a_lab[m], b_lab[m]
        lo, hi = np.minimum(la, lb), np.maximum(la, lb)
        keys.append(lo * (nlab + 1) + hi)
        heights.append(np.maximum(za, zb))
    e = np.flatnonzero(edge.ravel())
    le = lab[e]
    m = le != 0
    keys.append(le[m] * 0 + le[m])  # arête (0, l)
    heights.append(zf[e][m])
    keys = np.concatenate(keys)
    heights = np.concatenate(heights)
    order = np.lexsort((heights, keys))
    keys, heights = keys[order], heights[order]
    first = np.ones(keys.size, bool)
    first[1:] = keys[1:] != keys[:-1]
    keys, heights = keys[first], heights[first]
    a = keys // (nlab + 1)
    b = keys % (nlab + 1)
    return a, b, heights


def _flood_graph(nlab, a, b, h, sources):
    """Priority-Flood sur le graphe : niveau d'eau minimax depuis les sources."""
    deg = np.bincount(np.concatenate([a, b]), minlength=nlab + 1)
    start = np.zeros(nlab + 2, np.int64)
    np.cumsum(deg, out=start[1:])
    nb = np.empty(start[-1], np.int64)
    hh = np.empty(start[-1])
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    hgt = np.concatenate([h, h])
    o = np.argsort(src, kind="stable")
    nb[:] = dst[o]
    hh[:] = hgt[o]
    nb_l, hh_l, st = nb.tolist(), hh.tolist(), start.tolist()
    level = [math.inf] * (nlab + 1)
    done = [False] * (nlab + 1)
    heap = []
    for s in sources:
        level[s] = -math.inf
        heap.append((-math.inf, s))
    heapq.heapify(heap)
    while heap:
        lv, node = heapq.heappop(heap)
        if done[node]:
            continue
        done[node] = True
        for j in range(st[node], st[node + 1]):
            m = nb_l[j]
            if done[m]:
                continue
            nl = hh_l[j] if hh_l[j] > lv else lv
            if nl < level[m]:
                level[m] = nl
                heapq.heappush(heap, (nl, m))
    return np.array(level)


def fill_depressions(z, valid, dx, dy, max_depth=None, feedback=None):
    """Comble les dépressions.

    max_depth (m) : si fourni, une dépression dont le comblement dépasserait
    cette profondeur est conservée comme puits naturel (non comblée) ; les
    petites dépressions qu'elle contient s'écoulent vers son point le plus bas.

    Renvoie (z_comblé, masque des puits conservés, nombre de dépressions).
    """
    fb = feedback or Feedback()
    nr, nc = z.shape
    n = nr * nc
    vflat = valid.ravel()
    edge = edge_mask(valid)
    fb.info("Directions D8 sur le MNT brut…")
    rec, has_lower = d8_steepest(z, valid, dx, dy)
    term = vflat & ~has_lower
    pits = term & ~edge.ravel()
    outlets = term & edge.ravel()
    pit_idx = np.flatnonzero(pits)
    npits = pit_idx.size
    fb.info("{} cellules de dépression ou de zone plane détectées.".format(npits))
    if npits == 0:
        return z.copy(), np.zeros(z.shape, bool), 0
    fb.progress(5)
    waves = topo_waves(rec, vflat, fb, (5, 25))
    out_idx = np.flatnonzero(outlets)
    term_idx = np.concatenate([out_idx, pit_idx])
    term_lab = np.concatenate([np.zeros(out_idx.size, np.int64), np.arange(1, npits + 1)])
    lab = _label_from_terminals(rec, waves, term_idx, term_lab, n)
    del waves
    fb.check()
    fb.progress(35)
    fb.info("Graphe des cols entre bassins de dépression…")
    a, b, h = _depression_graph(z, valid, edge, lab, npits)
    fb.progress(45)
    level = _flood_graph(npits, a, b, h, [0])
    zf = z.ravel()
    labv = np.where(lab >= 0, lab, 0)
    filled = np.where(vflat, np.maximum(zf, level[labv]), np.nan)
    sinks = np.zeros(n, bool)
    if max_depth is not None and max_depth >= 0:
        fb.info("Recherche des dépressions plus profondes que {} m…".format(max_depth))
        raised = (filled > zf) & vflat
        regions, nreg = ndimage.label(raised.reshape(z.shape), structure=np.ones((3, 3)))
        if nreg:
            regf = regions.ravel()
            ridx = np.flatnonzero(regf)
            rl = regf[ridx]
            depth = filled[ridx] - zf[ridx]
            maxdepth = np.zeros(nreg + 1)
            np.maximum.at(maxdepth, rl, depth)
            # cellule la plus basse de chaque région
            order = np.lexsort((zf[ridx], rl))
            first = np.ones(order.size, bool)
            first[1:] = rl[order][1:] != rl[order][:-1]
            low_cells = ridx[order][first]
            low_regions = rl[order][first]
            keep = maxdepth[low_regions] > max_depth
            seed_cells = low_cells[keep]
            seeds = sorted(set(int(x) for x in labv[seed_cells] if x > 0))
            if seeds:
                fb.info("{} dépression(s) conservée(s) comme puits naturels.".format(len(seeds)))
                level = _flood_graph(npits, a, b, h, [0] + seeds)
                filled = np.where(vflat, np.maximum(zf, level[labv]), np.nan)
                sinks[seed_cells] = True
    fb.progress(55)
    return filled.reshape(z.shape), sinks.reshape(z.shape), npits


# --------------------------------------------------------------------------
# Directions d'écoulement
# --------------------------------------------------------------------------
class FlowModel:
    """Résultat du routage D8 : récepteurs, vagues topologiques et masques."""

    def __init__(self, shape, dx, dy, z, rec, waves, has_lower, sinks):
        self.shape = shape
        self.nr, self.nc = shape
        self.dx, self.dy = dx, dy
        self.z = z                  # MNT routé (comblé ou non), à plat
        self.rec = rec
        self.waves = waves
        self.has_lower = has_lower  # cellule avec une voisine strictement plus basse
        self.sinks = sinks          # cellules terminales intérieures (puits)
        self._rank = None
        self._donors = None

    @property
    def n(self):
        return self.nr * self.nc

    @property
    def rank(self):
        if self._rank is None:
            rk = np.full(self.n, -1, np.int64)
            for i, w in enumerate(self.waves):
                rk[w] = i
            self._rank = rk
        return self._rank

    def donors(self):
        """Index CSR des donneurs : donneurs de x = src[start[x]:start[x+1]]."""
        if self._donors is None:
            has = np.flatnonzero(self.rec >= 0)
            r = self.rec[has]
            o = np.argsort(r, kind="stable")
            src = has[o]
            cnt = np.bincount(r, minlength=self.n)
            start = np.zeros(self.n + 1, np.int64)
            np.cumsum(cnt, out=start[1:])
            self._donors = (start, src)
        return self._donors

    def d8_codes(self):
        out = np.zeros(self.n, np.uint8)
        has = np.flatnonzero(self.rec >= 0)
        dr = self.rec[has] // self.nc - has // self.nc
        dc = self.rec[has] % self.nc - has % self.nc
        lut = {(a, b): code for (a, b), code in zip(OFFSETS, D8_CODES)}
        for (a, b), code in lut.items():
            m = (dr == a) & (dc == b)
            out[has[m]] = code
        return out.reshape(self.shape)


def route_d8(zr, valid, dx, dy, sinks=None, feedback=None):
    """Directions D8 avec résolution des zones planes, puis tri topologique.

    zr : MNT à router (comblé, ou brut si les dépressions sont conservées).
    sinks : cellules à traiter comme puits terminaux.
    """
    fb = feedback or Feedback()
    nr, nc = zr.shape
    n = nr * nc
    vflat = valid.ravel()
    edge = edge_mask(valid).ravel()
    rec, has_lower = d8_steepest(zr, valid, dx, dy)
    sinkf = np.zeros(n, bool) if sinks is None else sinks.ravel().copy()
    rec[sinkf] = -1
    flat = vflat & ~has_lower & ~edge & ~sinkf
    nflat = int(flat.sum())
    fb.info("{} cellules planes à drainer.".format(nflat))
    if nflat:
        zf = zr.ravel()
        unres = flat.copy()
        grow = ndimage.binary_dilation(flat.reshape(zr.shape), structure=np.ones((3, 3), bool)).ravel()
        frontier = np.flatnonzero(grow & vflat & ~flat)
        it = 0
        while frontier.size:
            new_cells = []
            for k in range(8):
                nb = _neighbours_of(frontier, k, nr, nc)
                ok = nb >= 0
                f2, nb2 = frontier[ok], nb[ok]
                m = unres[nb2] & (zf[nb2] == zf[f2])
                if m.any():
                    rec[nb2[m]] = f2[m]
                    new_cells.append(nb2[m])
            if not new_cells:
                break
            cells = np.unique(np.concatenate(new_cells))
            unres[cells] = False
            frontier = cells
            it += 1
            if it % 200 == 0:
                fb.check()
        left = np.flatnonzero(unres)
        if left.size:
            fb.info("{} cellules planes sans exutoire : traitées comme puits.".format(left.size))
            rec[left] = -1
            sinkf[left] = True
    sinkf |= vflat & (rec < 0) & ~edge
    fb.info("Tri topologique des écoulements…")
    waves = topo_waves(rec, vflat, fb)
    return FlowModel(zr.shape, dx, dy, zr.ravel().copy(), rec, waves, has_lower, sinkf)


# --------------------------------------------------------------------------
# Accumulations
# --------------------------------------------------------------------------
def accumulate_d8(model, weight=None):
    acc = np.ones(model.n) if weight is None else weight.ravel().astype(np.float64).copy()
    acc[np.isnan(model.z)] = np.nan
    rec = model.rec
    for w in model.waves:
        r = rec[w]
        m = r >= 0
        if m.any():
            np.add.at(acc, r[m], acc[w[m]])
    return acc.reshape(model.shape)


def _kahn_accumulate(model, indeg, receivers_of, weight, feedback=None):
    n = model.n
    valid = ~np.isnan(model.z)
    acc = np.ones(n) if weight is None else weight.ravel().astype(np.float64).copy()
    acc[~valid] = np.nan
    indeg = indeg.astype(np.int32)
    frontier = np.flatnonzero(valid & (indeg == 0))
    it = 0
    while frontier.size:
        all_dst = []
        for dst, frac, src in receivers_of(frontier):
            if dst.size:
                np.add.at(acc, dst, acc[src] * frac)
                all_dst.append(dst)
        if not all_dst:
            break
        d = np.concatenate(all_dst)
        u, cnt = np.unique(d, return_counts=True)
        indeg[u] -= cnt.astype(np.int32)
        frontier = u[indeg[u] == 0]
        it += 1
        if feedback is not None and it % 200 == 0:
            feedback.check()
    return acc.reshape(model.shape)


def accumulate_mfd(model, exponent=1.1, weight=None, feedback=None):
    """Accumulation multidirectionnelle (Freeman 1991) : partage vers toutes les
    voisines plus basses selon tan(β)^p ; zones planes et puits suivent le D8 résolu."""
    nr, nc, n = model.nr, model.nc, model.n
    z = model.z
    valid = ~np.isnan(z)
    dists = _dists(model.dx, model.dy)
    mfd = model.has_lower & valid & (model.rec >= 0)
    # degrés entrants
    indeg = np.zeros(n, np.int64)
    all_idx = np.flatnonzero(mfd)
    for k in range(8):
        nb = _neighbours_of(all_idx, k, nr, nc)
        ok = nb >= 0
        s, d = all_idx[ok], nb[ok]
        m = valid[d] & (z[d] < z[s])
        np.add.at(indeg, d[m], 1)
    d8_only = np.flatnonzero(valid & ~mfd & (model.rec >= 0))
    np.add.at(indeg, model.rec[d8_only], 1)

    def receivers_of(f):
        out = []
        fm = f[mfd[f]]
        if fm.size:
            ws, nbs = [], []
            for k in range(8):
                nb = _neighbours_of(fm, k, nr, nc)
                ok = nb >= 0
                nbc = np.where(ok, nb, 0)
                drop = np.where(ok & valid[nbc], z[fm] - z[nbc], 0.0)
                w = np.where(drop > 0, (np.maximum(drop, 0) / dists[k]) ** exponent, 0.0)
                ws.append(w)
                nbs.append(nbc)
            ws = np.array(ws)
            tot = ws.sum(axis=0)
            for k in range(8):
                m = ws[k] > 0
                if m.any():
                    out.append((nbs[k][m], ws[k][m] / tot[m], fm[m]))
        fd = f[~mfd[f] & (model.rec[f] >= 0)]
        if fd.size:
            out.append((model.rec[fd], np.ones(fd.size), fd))
        return out

    return _kahn_accumulate(model, indeg, receivers_of, weight, feedback)


def dinf_receivers(model):
    """Récepteurs D-Infinity (Tarboton 1997) : deux voisines et proportion vers la première."""
    nr, nc, n = model.nr, model.nc, model.n
    dx, dy = model.dx, model.dy
    z = model.z.reshape(model.shape)
    zp = np.pad(z, 1, constant_values=np.nan)

    def nbz(k):
        dr, dc = OFFSETS[k]
        return zp[1 + dr:1 + dr + nr, 1 + dc:1 + dc + nc]

    # facettes (cardinale, diagonale)
    facets = [(0, 7), (6, 7), (6, 5), (4, 5), (4, 3), (2, 3), (2, 1), (0, 1)]
    best_s = np.zeros(model.shape)
    best_f = np.full(model.shape, -1, np.int8)
    best_r = np.zeros(model.shape)
    with np.errstate(invalid="ignore", divide="ignore"):
        for fi, (k1, k2) in enumerate(facets):
            d1 = dx if OFFSETS[k1][0] == 0 else dy
            d2 = dy if OFFSETS[k1][0] == 0 else dx
            e1, e2 = nbz(k1), nbz(k2)
            s1 = (z - e1) / d1
            s2 = (e1 - e2) / d2
            r = np.arctan2(s2, s1)
            s = np.hypot(s1, s2)
            rmax = math.atan2(d2, d1)
            low = r < 0
            r = np.where(low, 0.0, r)
            s = np.where(low, s1, s)
            high = r > rmax
            s = np.where(high, (z - e2) / math.hypot(d1, d2), s)
            r = np.where(high, rmax, r)
            upd = np.isfinite(s) & (s > best_s)
            best_s[upd] = s[upd]
            best_f[upd] = fi
            best_r[upd] = r[upd]
    recA = np.full(n, -1, np.int64)
    recB = np.full(n, -1, np.int64)
    pA = np.zeros(n)
    bf = best_f.ravel()
    br = best_r.ravel()
    idx = np.flatnonzero(bf >= 0)
    offs = _OFF[:, 0] * nc + _OFF[:, 1]
    k1 = np.array([f[0] for f in facets])[bf[idx]]
    k2 = np.array([f[1] for f in facets])[bf[idx]]
    d1 = np.where(_OFF[k1, 0] == 0, dx, dy)
    d2 = np.where(_OFF[k1, 0] == 0, dy, dx)
    rmax = np.arctan2(d2, d1)
    frac1 = 1.0 - br[idx] / rmax
    recA[idx] = idx + offs[k1]
    recB[idx] = idx + offs[k2]
    pA[idx] = frac1
    # ne garder que des récepteurs strictement plus bas (graphe acyclique)
    zf = model.z
    for rr in (recA, recB):
        bad = (rr >= 0)
        bi = np.flatnonzero(bad)
        lower = zf[rr[bi]] < zf[bi]
        rr[bi[~lower]] = -1
    pB = 1.0 - pA
    pA = np.where(recA >= 0, pA, 0.0)
    pB = np.where(recB >= 0, pB, 0.0)
    tot = pA + pB
    ok = tot > 1e-12
    pA = np.where(ok, pA / np.where(ok, tot, 1), 0.0)
    pB = np.where(ok, pB / np.where(ok, tot, 1), 0.0)
    recA = np.where(pA > 0, recA, -1)
    recB = np.where(pB > 0, recB, -1)
    # repli D8 (zones planes, bords)
    none = ~ok & (model.rec >= 0)
    recA[none] = model.rec[none]
    pA[none] = 1.0
    return recA, recB, pA, pB


def accumulate_dinf(model, weight=None, feedback=None):
    recA, recB, pA, pB = dinf_receivers(model)
    n = model.n
    indeg = np.bincount(recA[recA >= 0], minlength=n) + np.bincount(recB[recB >= 0], minlength=n)

    def receivers_of(f):
        out = []
        for rr, pp in ((recA, pA), (recB, pB)):
            m = rr[f] >= 0
            if m.any():
                out.append((rr[f[m]], pp[f[m]], f[m]))
        return out

    return _kahn_accumulate(model, indeg, receivers_of, weight, feedback)


def flow_length_downstream(model):
    """Distance d'écoulement jusqu'à la sortie (m), le long des directions D8."""
    out = np.zeros(model.n)
    rec = model.rec
    for w in reversed(model.waves):
        r = rec[w]
        m = r >= 0
        if m.any():
            ww, rr = w[m], r[m]
            out[ww] = out[rr] + step_lengths(ww, rr, model.nc, model.dx, model.dy)
    out[np.isnan(model.z)] = np.nan
    return out.reshape(model.shape)


def flow_length_upstream(model, labels=None):
    """Plus long chemin d'écoulement depuis la ligne de partage (m).

    Si `labels` est fourni (à plat), le chemin s'arrête aux limites de label
    (longueur interne à chaque sous-bassin).
    """
    out = np.zeros(model.n)
    rec = model.rec
    for w in model.waves:
        r = rec[w]
        m = r >= 0
        if labels is not None:
            m &= labels[w] == labels[np.where(r >= 0, r, 0)]
        if m.any():
            ww, rr = w[m], r[m]
            np.maximum.at(out, rr, out[ww] + step_lengths(ww, rr, model.nc, model.dx, model.dy))
    out[np.isnan(model.z)] = np.nan
    return out


# --------------------------------------------------------------------------
# Réseau hydrographique
# --------------------------------------------------------------------------
class StreamNetwork:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def extract_streams(model, acc_cells, threshold_cells, feedback=None):
    """Réseau D8 : cellules dont l'accumulation ≥ seuil, ordres de Strahler et
    de Shreve, tronçons (liens entre confluences) et confluences."""
    n = model.n
    accf = acc_cells.ravel()
    stream = np.nan_to_num(accf, nan=0) >= threshold_cells
    rec = model.rec
    strahler = np.zeros(n, np.int16)
    shreve = np.zeros(n, np.int64)
    ndon = np.zeros(n, np.int32)
    maxo = np.zeros(n, np.int16)
    cntmax = np.zeros(n, np.int32)
    link = np.zeros(n, np.int64)
    link_from = np.zeros(n, np.int64)
    order_start = np.zeros(n, bool)
    next_link = 1
    for wi, w in enumerate(model.waves):
        c = w[stream[w]]
        if c.size == 0:
            continue
        src = ndon[c] == 0
        strahler[c] = np.where(src, 1, np.where(cntmax[c] >= 2, maxo[c] + 1, maxo[c]))
        shreve[c] = np.where(src, 1, shreve[c])
        order_start[c] = src | (cntmax[c] >= 2)
        starts = src | (ndon[c] >= 2)
        ns = int(starts.sum())
        if ns:
            link[c[starts]] = np.arange(next_link, next_link + ns)
            next_link += ns
        link[c[~starts]] = link_from[c[~starts]]
        r = rec[c]
        m = r >= 0
        if not m.any():
            continue
        cc, rr = c[m], r[m]
        np.add.at(ndon, rr, 1)
        np.add.at(shreve, rr, shreve[cc])
        link_from[rr] = link[cc]
        u, inv = np.unique(rr, return_inverse=True)
        o = strahler[cc].astype(np.int16)
        wmax = np.full(u.size, -1, np.int16)
        np.maximum.at(wmax, inv, o)
        wcnt = np.bincount(inv, weights=(o == wmax[inv])).astype(np.int32)
        cur = maxo[u]
        gt = wmax > cur
        eq = wmax == cur
        maxo[u] = np.where(gt, wmax, cur)
        cntmax[u] = np.where(gt, wcnt, np.where(eq, cntmax[u] + wcnt, cntmax[u]))
        if feedback is not None and wi % 500 == 0:
            feedback.check()
    sidx = np.flatnonzero(stream)
    r = rec[sidx]
    rr = np.where(r >= 0, r, 0)
    seg_outlet = np.zeros(n, bool)
    seg_outlet[sidx] = (r < 0) | (ndon[rr] >= 2)
    junction = np.zeros(n, bool)
    junction[sidx] = ndon[sidx] >= 2
    sources = np.zeros(n, bool)
    sources[sidx] = ndon[sidx] == 0
    return StreamNetwork(mask=stream, strahler=strahler, shreve=shreve, link=link,
                         n_links=next_link - 1, seg_outlet=seg_outlet, junction=junction,
                         sources=sources, order_start=order_start, threshold_cells=threshold_cells)


def link_polylines(model, net, x_of, y_of):
    """Géométries des tronçons : liste de (link_id, indices de cellules ordonnés amont→aval)."""
    sidx = np.flatnonzero(net.mask)
    lk = net.link[sidx]
    rk = model.rank[sidx]
    o = np.lexsort((rk, lk))
    sidx, lk = sidx[o], lk[o]
    cuts = np.flatnonzero(np.diff(lk)) + 1
    groups = np.split(sidx, cuts)
    out = []
    for g in groups:
        if g.size == 0:
            continue
        last = g[-1]
        r = model.rec[last]
        cells = np.append(g, r) if r >= 0 else g
        out.append((int(net.link[g[0]]), cells))
    return out


# --------------------------------------------------------------------------
# Bassins versants
# --------------------------------------------------------------------------
def snap_outlet(model, acc_cells, r, c, radius_cells, stream_mask=None):
    """Cellule d'accumulation maximale dans un carré de rayon `radius_cells` autour de (r, c).

    Si `stream_mask` est fourni et contient des cellules dans la fenêtre, la
    recherche se limite au réseau hydrographique.
    """
    nr, nc = model.shape
    r0, r1 = max(0, r - radius_cells), min(nr, r + radius_cells + 1)
    c0, c1 = max(0, c - radius_cells), min(nc, c + radius_cells + 1)
    win = np.nan_to_num(acc_cells[r0:r1, c0:c1], nan=-1).copy()
    rr, cc = np.mgrid[r0:r1, c0:c1]
    inside = (rr - r) ** 2 + (cc - c) ** 2 <= radius_cells ** 2
    win[~inside] = -1
    if stream_mask is not None:
        sm = stream_mask.reshape(model.shape)[r0:r1, c0:c1] & inside
        if sm.any():
            win[~sm] = -1
    k = int(np.argmax(win))
    if win.flat[k] < 0:
        return r, c
    return r0 + k // (c1 - c0), c0 + k % (c1 - c0)


def label_basins(model, seeds, ids=None):
    """Bassins contributifs des cellules `seeds` (indices à plat).

    Un seed situé en aval d'un autre s'arrête à la limite de ce dernier : on
    obtient ainsi des sous-bassins emboîtés sans recouvrement.
    """
    lab = np.zeros(model.n, np.int64)
    seeds = np.asarray(seeds, np.int64)
    if ids is None:
        ids = np.arange(1, seeds.size + 1)
    lab[seeds] = ids
    rec = model.rec
    for w in reversed(model.waves):
        r = rec[w]
        m = (r >= 0) & (lab[w] == 0)
        if m.any():
            lab[w[m]] = lab[r[m]]
    return lab


def terminal_cells(model):
    valid = ~np.isnan(model.z)
    return np.flatnonzero(valid & (model.rec < 0))


def auto_basins(model, min_area_cells):
    """Bassins de toutes les sorties (bords et puits) d'au moins `min_area_cells` cellules."""
    term = terminal_cells(model)
    lab = label_basins(model, term)
    cnt = np.bincount(lab, minlength=term.size + 1)
    keep = np.flatnonzero(cnt[1:] >= min_area_cells) + 1
    remap = np.zeros(term.size + 1, np.int64)
    remap[keep] = np.arange(1, keep.size + 1)
    lab2 = remap[lab]
    return lab2, term[keep - 1]


def subbasin_seeds(model, net, basin_mask, outlet, method, acc_cells=None, param=None,
                   user_cells=None):
    """Exutoires des sous-bassins selon la méthode choisie (indices à plat).

    method :
      "liens"      : chaque tronçon entre confluences (exutoire de chaque lien) ;
      "strahler"   : chaque cours d'eau d'ordre de Strahler ≥ param ;
      "seuil"      : liens d'un réseau extrait au seuil `param` (cellules) ;
      "points"     : cellules fournies par l'utilisateur (déjà recalées).
    L'exutoire principal est toujours inclus.
    """
    bm = basin_mask.ravel()
    if method == "liens":
        seeds = np.flatnonzero(net.seg_outlet & bm)
    elif method == "strahler":
        k = int(param or 1)
        s = np.flatnonzero(net.mask & bm & (net.strahler >= k))
        r = model.rec[s]
        rr = np.where(r >= 0, r, 0)
        change = (r < 0) | (net.strahler[rr] != net.strahler[s]) | ~bm[rr]
        seeds = s[change]
    elif method == "seuil":
        net2 = extract_streams(model, acc_cells, float(param))
        seeds = np.flatnonzero(net2.seg_outlet & bm)
    elif method == "points":
        seeds = np.asarray(user_cells if user_cells is not None else [], np.int64)
        seeds = seeds[bm[seeds]] if seeds.size else seeds
    else:
        raise ValueError("Méthode inconnue : {}".format(method))
    seeds = np.unique(np.append(seeds, outlet)).astype(np.int64)
    return seeds


def merge_small_subbasins(model, seeds, outlet, min_cells):
    """Retire itérativement l'exutoire du plus petit sous-bassin sous le seuil
    (il fusionne avec le sous-bassin aval), jusqu'à ce que tous atteignent le seuil."""
    seeds = list(int(s) for s in seeds)
    while True:
        lab = label_basins(model, np.array(seeds))
        cnt = np.bincount(lab, minlength=len(seeds) + 1)[1:]
        cand = [(cnt[i], i) for i, s in enumerate(seeds) if s != outlet and cnt[i] < min_cells]
        if not cand:
            return np.array(seeds, np.int64), lab
        _, i = min(cand)
        seeds.pop(i)


def trace_main_channel(model, outlet, labels, ufl_local):
    """Chemin d'écoulement le plus long, de la ligne de partage jusqu'à l'exutoire."""
    start, src = model.donors()
    path = [int(outlet)]
    cur = int(outlet)
    nc, dx, dy = model.nc, model.dx, model.dy
    lab = labels[cur]
    for _ in range(model.n):
        d = src[start[cur]:start[cur + 1]]
        if d.size == 0:
            break
        d = d[labels[d] == lab]
        if d.size == 0:
            break
        score = ufl_local[d] + step_lengths(d, np.full(d.size, cur), nc, dx, dy)
        cur = int(d[int(np.argmax(score))])
        path.append(cur)
    return path[::-1]
