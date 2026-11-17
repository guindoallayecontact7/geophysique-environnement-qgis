# -*- coding: utf-8 -*-
"""Graphiques scientifiques (Matplotlib, moteur Agg, sans pyplot : sûr en tâche de fond)."""
import os

import numpy as np

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    HAS_MPL = True
except ImportError:  # Matplotlib absent : graphiques désactivés, le reste fonctionne
    HAS_MPL = False

FORMATS = ("png", "svg")


def _new(figsize=(7.5, 4.5)):
    fig = Figure(figsize=figsize, dpi=150)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.grid(True, color="#dddddd", linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return fig, ax


def _save(fig, base, formats=FORMATS):
    os.makedirs(os.path.dirname(base) or ".", exist_ok=True)
    fig.tight_layout()
    out = []
    for f in formats:
        p = "{}.{}".format(base, f)
        fig.savefig(p, format=f)
        out.append(p)
    return out


def histogram(values, base, title, xlabel, bins=50, color="#3b6ea5", formats=FORMATS):
    if not HAS_MPL:
        return []
    v = np.asarray(values).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return []
    lo, hi = np.percentile(v, [0.5, 99.5])
    fig, ax = _new()
    ax.hist(v[(v >= lo) & (v <= hi)], bins=bins, color=color, edgecolor="white", linewidth=0.3)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Nombre de cellules")
    return _save(fig, base, formats)


def bars(labels, values, base, title, ylabel, colors=None, formats=FORMATS):
    if not HAS_MPL or not len(values):
        return []
    fig, ax = _new((8, 4.5))
    x = np.arange(len(values))
    ax.bar(x, values, color=colors or "#3b6ea5", edgecolor="#333333", linewidth=0.3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35 if len(labels) > 4 else 0, ha="right" if len(labels) > 4 else "center",
                       fontsize=8)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    return _save(fig, base, formats)


def hypsometric_curve(h, above, hi, base, title="Courbe hypsométrique", formats=FORMATS):
    if not HAS_MPL:
        return []
    fig, ax = _new((5.5, 5))
    ax.plot(above, h, color="#7d4f2a", linewidth=1.8)
    ax.fill_between(above, 0, h, color="#d9a95b", alpha=0.35)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Surface relative a/A")
    ax.set_ylabel("Hauteur relative h/H")
    ax.set_title("{} (HI = {:.3f})".format(title, hi).replace(".", ","))
    return _save(fig, base, formats)


def rose(values_deg, base, title="Répartition des expositions", formats=FORMATS):
    if not HAS_MPL:
        return []
    v = np.asarray(values_deg).ravel()
    v = v[np.isfinite(v) & (v >= 0)]
    if v.size == 0:
        return []
    fig = Figure(figsize=(5.5, 5.5), dpi=150)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    counts, edges = np.histogram(v, bins=16, range=(0, 360))
    centers = np.radians((edges[:-1] + edges[1:]) / 2)
    ax.bar(centers, counts / counts.sum() * 100, width=np.radians(22.5), color="#3b6ea5", edgecolor="white")
    ax.set_title(title, pad=18)
    return _save(fig, base, formats)


def horton_plot(orders_counts, base, title="Loi des nombres de Horton", formats=FORMATS):
    if not HAS_MPL or not orders_counts:
        return []
    o = sorted(orders_counts)
    n = [orders_counts[k] for k in o]
    fig, ax = _new((6, 4.5))
    ax.semilogy(o, n, "o-", color="#08519c")
    ax.set_xticks(o)
    ax.set_xlabel("Ordre de Strahler")
    ax.set_ylabel("Nombre de cours d'eau (log)")
    ax.set_title(title)
    return _save(fig, base, formats)


def profiles(profiles_list, base, title="Profils topographiques", show_forms=True, formats=("png", "svg", "pdf")):
    """profiles_list : liste de dict(name, distance, z, form, breaks)."""
    if not HAS_MPL:
        return []
    fig = Figure(figsize=(9, 5.5), dpi=150)
    FigureCanvasAgg(fig)
    single = len(profiles_list) == 1
    if single and show_forms:
        ax = fig.add_axes([0.08, 0.32, 0.9, 0.6])
        ax2 = fig.add_axes([0.08, 0.1, 0.9, 0.15], sharex=ax)
    else:
        ax = fig.add_subplot(111)
        ax2 = None
    ax.grid(True, color="#dddddd", linewidth=0.6)
    palette = ["#08519c", "#d94801", "#238b45", "#6a51a3", "#cb181d", "#525252"]
    for i, p in enumerate(profiles_list):
        c = palette[i % len(palette)]
        ax.plot(p["distance"], p["z"], color=c, linewidth=1.5, label=p.get("name", "Profil {}".format(i + 1)))
        b = p.get("breaks")
        if b is not None and len(b):
            ax.plot(p["distance"][b], p["z"][b], "v", color="#cb181d", markersize=5,
                    label="Ruptures de pente" if i == 0 else None)
    ax.set_ylabel("Altitude (m)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    if ax2 is not None:
        p = profiles_list[0]
        f = np.asarray(p.get("form", []))
        d = np.asarray(p["distance"])
        if f.size:
            ax2.fill_between(d, 0, 1, where=f == 1, color="#b2182b", alpha=0.7, step="mid", label="Convexe")
            ax2.fill_between(d, 0, 1, where=f == -1, color="#2166ac", alpha=0.7, step="mid", label="Concave")
            ax2.fill_between(d, 0, 1, where=f == 0, color="#bbbbbb", alpha=0.7, step="mid", label="Rectiligne")
        ax2.set_yticks([])
        ax2.legend(fontsize=7, ncol=3, loc="upper right")
        ax2.set_xlabel("Distance cumulée (m)")
    else:
        ax.set_xlabel("Distance cumulée (m)")
    os.makedirs(os.path.dirname(base) or ".", exist_ok=True)
    out = []
    for f in formats:
        pth = "{}.{}".format(base, f)
        fig.savefig(pth, format=f)
        out.append(pth)
    return out
