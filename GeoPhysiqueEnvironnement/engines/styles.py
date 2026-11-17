# -*- coding: utf-8 -*-
"""Styles cartographiques.

Les tâches de calcul décrivent le style sous forme de dict (sans Qt) ;
`apply_style` le traduit en moteur de rendu QGIS dans le fil principal.
"""
import numpy as np

RAMPS = {
    "hypsometrie": ["#0b6e34", "#4fa847", "#a9cf6a", "#efe7a0", "#e3bf75", "#c08b4f", "#8c5a33", "#6b4127", "#f4f1ec"],
    "pente": ["#1a9641", "#a6d96a", "#ffffbf", "#fdae61", "#d7191c"],
    "divergent": ["#2166ac", "#67a9cf", "#f7f7f7", "#ef8a62", "#b2182b"],
    "sequentiel": ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"],
    "humidite": ["#fff7ec", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    "chaleur": ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
    "ecoulement": ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    "gris": ["#000000", "#ffffff"],
    "relief": ["#f7f4f9", "#d4b9da", "#df65b0", "#ce1256", "#67001f"],
}

ASPECT_COLORS = ["#c8c8c8", "#ff0000", "#ffa500", "#ffff00", "#00ff00",
                 "#00ffff", "#00a5ff", "#0000ff", "#ff00ff"]
FORM_COLORS = ["#2166ac", "#f0f0f0", "#b2182b"]


def _interp(colors, t):
    """Couleur hex à la position t ∈ [0, 1] d'une rampe."""
    t = min(1.0, max(0.0, float(t)))
    pos = t * (len(colors) - 1)
    i = int(np.floor(pos))
    if i >= len(colors) - 1:
        return colors[-1]
    f = pos - i
    a = [int(colors[i][k:k + 2], 16) for k in (1, 3, 5)]
    b = [int(colors[i + 1][k:k + 2], 16) for k in (1, 3, 5)]
    c = [round(a[j] + (b[j] - a[j]) * f) for j in range(3)]
    return "#{:02x}{:02x}{:02x}".format(*c)


def _ramp(ramp):
    return list(ramp) if isinstance(ramp, (list, tuple)) else list(RAMPS.get(ramp, RAMPS["sequentiel"]))


def palette_colors(n, ramp="sequentiel"):
    colors = _ramp(ramp)
    return [_interp(colors, i / max(1, n - 1)) for i in range(n)]


def ramp_style(values, ramp="sequentiel", mode="minmax", n=5, unit="", invert=False, opacity=1.0,
               fmt="{:.2f}"):
    """Style continu calculé à partir des données (stops valeur → couleur)."""
    v = np.asarray(values).ravel()
    v = v[np.isfinite(v)]
    colors = _ramp(ramp)
    if invert:
        colors = colors[::-1]
    if v.size == 0:
        return {"type": "ramp", "stops": [], "opacity": opacity}
    if mode == "diverging":
        m = float(np.percentile(np.abs(v), 98)) or float(np.max(np.abs(v))) or 1.0
        vals = list(np.linspace(-m, m, n))
    elif mode == "quantile":
        vals = list(np.unique(np.percentile(v, np.linspace(2, 98, n))))
    elif mode == "log":
        pos = v[v > 0]
        lo = float(np.percentile(pos, 50)) if pos.size else 1.0
        hi = float(pos.max()) if pos.size else 10.0
        vals = list(np.geomspace(max(lo, 1e-9), max(hi, lo * 10), n))
    elif mode == "p2p98":
        lo, hi = np.percentile(v, [2, 98])
        vals = list(np.linspace(lo, hi if hi > lo else lo + 1, n))
    else:
        lo, hi = float(v.min()), float(v.max())
        vals = list(np.linspace(lo, hi if hi > lo else lo + 1, n))
    k = len(vals)
    stops = [(float(x), _interp(colors, i / max(1, k - 1)),
              (fmt.format(x) + (" " + unit if unit else "")).replace(".", ","))
             for i, x in enumerate(vals)]
    return {"type": "ramp", "stops": stops, "opacity": opacity}


def classes_style(labels, colors=None, ramp="sequentiel", codes=None, opacity=1.0):
    codes = codes or list(range(1, len(labels) + 1))
    colors = colors or palette_colors(len(labels), ramp)
    return {"type": "palette", "entries": list(zip(codes, colors, labels)), "opacity": opacity}


def gray_style(lo=0, hi=255, opacity=1.0):
    return {"type": "gray", "min": lo, "max": hi, "opacity": opacity}


# --------------------------------------------------------------------------
# Application dans QGIS (fil principal uniquement)
# --------------------------------------------------------------------------
def apply_style(layer, style):
    if not style or layer is None:
        return
    from qgis.core import QgsRasterLayer
    t = style.get("type")
    if isinstance(layer, QgsRasterLayer):
        if t == "ramp":
            _raster_ramp(layer, style)
        elif t == "palette":
            _raster_palette(layer, style)
        elif t == "gray":
            _raster_gray(layer, style)
        layer.setOpacity(style.get("opacity", 1.0))
    else:
        _vector(layer, style)
    layer.triggerRepaint()


def _qcolor(h):
    from qgis.PyQt.QtGui import QColor
    return QColor(h)


def _raster_ramp(layer, style):
    from qgis.core import (QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer)
    stops = style.get("stops") or []
    if not stops:
        return
    shader = QgsColorRampShader()
    interp = QgsColorRampShader.Type.Discrete if style.get("discrete") else QgsColorRampShader.Type.Interpolated
    shader.setColorRampType(interp)
    shader.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, _qcolor(c), lab) for v, c, lab in stops])
    shader.setMinimumValue(stops[0][0])
    shader.setMaximumValue(stops[-1][0])
    rs = QgsRasterShader()
    rs.setRasterShaderFunction(shader)
    r = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, rs)
    r.setClassificationMin(stops[0][0])
    r.setClassificationMax(stops[-1][0])
    layer.setRenderer(r)


def _raster_palette(layer, style):
    from qgis.core import QgsPalettedRasterRenderer
    classes = [QgsPalettedRasterRenderer.Class(int(code), _qcolor(col), lab)
               for code, col, lab in style.get("entries", [])]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, classes))


def _raster_gray(layer, style):
    from qgis.core import QgsSingleBandGrayRenderer, QgsContrastEnhancement
    r = QgsSingleBandGrayRenderer(layer.dataProvider(), 1)
    ce = QgsContrastEnhancement(layer.dataProvider().dataType(1))
    ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum)
    ce.setMinimumValue(style.get("min", 0))
    ce.setMaximumValue(style.get("max", 255))
    r.setContrastEnhancement(ce)
    layer.setRenderer(r)


def _vector(layer, style):
    from qgis.core import (QgsGraduatedSymbolRenderer, QgsRendererRange, QgsSymbol,
                           QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsRuleBasedRenderer,
                           QgsWkbTypes, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
                           QgsTextFormat)
    t = style.get("type")
    gtype = layer.geometryType()
    if t == "streams":
        field = style.get("field", "strahler")
        idx = layer.fields().indexOf(field)
        maxo = int(layer.maximumValue(idx) or 1) if idx >= 0 else 1
        ranges = []
        cols = palette_colors(maxo + 2, ["#9ecae1", "#08306b"])[2:] if maxo > 0 else ["#2171b5"]
        for o in range(1, maxo + 1):
            sym = QgsSymbol.defaultSymbol(gtype)
            sym.setColor(_qcolor(cols[min(o - 1, len(cols) - 1)]))
            sym.setWidth(0.2 + 0.35 * (o - 1))
            ranges.append(QgsRendererRange(o - 0.5, o + 0.5, sym, "{} {}".format(style.get("label", "Ordre"), o)))
        layer.setRenderer(QgsGraduatedSymbolRenderer(field, ranges))
    elif t == "streams_bins":
        field = style.get("field", "shreve")
        idx = layer.fields().indexOf(field)
        vmax = float(layer.maximumValue(idx) or 1) if idx >= 0 else 1.0
        bins = [b for b in style.get("bins", [1, 10, 100, 10 ** 9])]
        used = [(a, b) for a, b in zip(bins[:-1], bins[1:]) if a <= vmax]
        cols = palette_colors(len(used) + 2, ["#9ecae1", "#08306b"])[2:]
        ranges = []
        for i, (a, b) in enumerate(used):
            sym = QgsSymbol.defaultSymbol(gtype)
            sym.setColor(_qcolor(cols[i]))
            sym.setWidth(0.2 + 0.3 * i)
            lab = "{} {}-{}".format(style.get("label", ""), a, b - 1) if b < 10 ** 9 else "{} ≥ {}".format(style.get("label", ""), a)
            ranges.append(QgsRendererRange(a - 0.5, b - 0.5, sym, lab.strip()))
        layer.setRenderer(QgsGraduatedSymbolRenderer(field, ranges))
    elif t == "categories":
        field = style.get("field", "id")
        idx = layer.fields().indexOf(field)
        values = sorted(layer.uniqueValues(idx)) if idx >= 0 else []
        cols = palette_colors(max(len(values), 2), ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d"])
        rng = np.random.default_rng(7)
        order = rng.permutation(len(values)) if values else []
        cats = []
        for k, v in enumerate(values):
            sym = QgsSymbol.defaultSymbol(gtype)
            c = _qcolor(cols[order[k] % len(cols)])
            c.setAlpha(150)
            sym.setColor(c)
            if gtype == QgsWkbTypes.GeometryType.PolygonGeometry:
                sym.symbolLayer(0).setStrokeColor(_qcolor("#222222"))
                sym.symbolLayer(0).setStrokeWidth(0.4)
            cats.append(QgsRendererCategory(v, sym, "{} {}".format(style.get("label", ""), v).strip()))
        layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))
    elif t == "outline":
        sym = QgsSymbol.defaultSymbol(gtype)
        sl = sym.symbolLayer(0)
        sl.setColor(_qcolor("#00000000"))
        sl.setStrokeColor(_qcolor(style.get("color", "#000000")))
        sl.setStrokeWidth(style.get("width", 0.8))
        layer.renderer().setSymbol(sym)
    elif t == "points":
        sym = QgsSymbol.defaultSymbol(gtype)
        sym.setColor(_qcolor(style.get("color", "#d7191c")))
        sym.setSize(style.get("size", 3.0))
        layer.renderer().setSymbol(sym)
    elif t == "lines":
        sym = QgsSymbol.defaultSymbol(gtype)
        sym.setColor(_qcolor(style.get("color", "#08519c")))
        sym.setWidth(style.get("width", 0.5))
        layer.renderer().setSymbol(sym)
    elif t == "contours":
        root = QgsRuleBasedRenderer.Rule(None)
        for expr, width, color, label in (('"maitresse" = 1', 0.45, "#5a3a1a", "Courbe maîtresse"),
                                          ('"maitresse" = 0', 0.18, "#a0785a", "Courbe intermédiaire")):
            sym = QgsSymbol.defaultSymbol(gtype)
            sym.setColor(_qcolor(color))
            sym.setWidth(width)
            root.appendChild(QgsRuleBasedRenderer.Rule(sym, 0, 0, expr, label))
        layer.setRenderer(QgsRuleBasedRenderer(root))
        pal = QgsPalLayerSettings()
        pal.fieldName = 'format_number("altitude", 0)'
        pal.isExpression = True
        try:
            pal.placement = QgsPalLayerSettings.Placement.Line
        except AttributeError:
            pal.placement = QgsPalLayerSettings.Line
        fmt = QgsTextFormat()
        fmt.setSize(7)
        fmt.setColor(_qcolor("#5a3a1a"))
        pal.setFormat(fmt)
        try:
            from qgis.core import QgsRuleBasedLabeling
            r = QgsRuleBasedLabeling.Rule(pal)
            r.setFilterExpression('"maitresse" = 1')
            root_l = QgsRuleBasedLabeling.Rule(None)
            root_l.appendChild(r)
            layer.setLabeling(QgsRuleBasedLabeling(root_l))
        except Exception:  # noqa: BLE001
            layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        layer.setLabelsEnabled(True)
    layer.setOpacity(style.get("opacity", 1.0))
