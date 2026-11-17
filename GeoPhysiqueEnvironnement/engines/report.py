# -*- coding: utf-8 -*-
"""Fiches techniques PDF (QTextDocument + QPdfWriter, fil principal)."""
import html
import os

from qgis.PyQt.QtCore import QUrl, QMarginsF, QSizeF
from qgis.PyQt.QtGui import QTextDocument, QPdfWriter, QPageSize, QPageLayout

from .statistics import fmt, APP_NAME, AUTHOR

MAX_ROWS = 60


def _h(t):
    return html.escape(str(t))


def result_html(result, max_rows=MAX_ROWS):
    p = ['<html><head><style>'
         'body{font-family:Arial;font-size:9pt;color:#222}'
         'h1{font-size:15pt;color:#1f3b57;margin-bottom:2px}'
         'h2{font-size:11pt;color:#1f3b57;border-bottom:1px solid #1f3b57;margin-top:14px}'
         'table{border-collapse:collapse}'
         'td,th{border:1px solid #999;padding:2px 4px;font-size:7.5pt}'
         'th{background:#e3eaf1}'
         '.small{color:#555;font-size:8pt}'
         '</style></head><body>']
    p.append("<h1>{}</h1>".format(_h(result.title)))
    p.append('<p class="small">{} · {} · {} · {}</p>'.format(
        _h(APP_NAME), _h(result.module_title), result.created.strftime("%d/%m/%Y %H:%M"), _h(AUTHOR)))
    p.append("<h2>Données d'entrée</h2><table>")
    rows = [("MNT", result.dem_source), ("Système de coordonnées", result.crs), ("Résolution", result.resolution)]
    rows += list(result.inputs)
    for k, v in rows:
        if v:
            p.append("<tr><th align='left'>{}</th><td>{}</td></tr>".format(_h(k), _h(v)))
    p.append("</table>")
    if result.params:
        p.append("<h2>Paramètres</h2><table><tr><th>Paramètre</th><th>Valeur</th><th>Unité</th></tr>")
        for k, v, u in result.params:
            p.append("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _h(k), _h(v if isinstance(v, str) else fmt(v)), _h(u)))
        p.append("</table>")
    if result.summary:
        p.append("<h2>Résumé des résultats</h2><table><tr><th>Indicateur</th><th>Valeur</th><th>Unité</th></tr>")
        for k, v, u in result.summary:
            p.append("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _h(k), _h(v if isinstance(v, str) else fmt(v)), _h(u)))
        p.append("</table>")
    for t in result.tables:
        p.append("<h2>{}</h2><table><tr>".format(_h(t.title)))
        for h, u in zip(t.headers, t.units):
            p.append("<th>{}{}</th>".format(_h(h), "<br/>(" + _h(u) + ")" if u else ""))
        p.append("</tr>")
        for r in t.rows[:max_rows]:
            p.append("<tr>" + "".join("<td>{}</td>".format(_h(fmt(v))) for v in r) + "</tr>")
        p.append("</table>")
        if len(t.rows) > max_rows:
            p.append('<p class="small">{} lignes sur {} affichées ; tableau complet dans les fichiers CSV et Excel.</p>'
                     .format(max_rows, len(t.rows)))
        if t.note:
            p.append('<p class="small">{}</p>'.format(_h(t.note)))
    pngs = [c for c in result.charts if c.lower().endswith(".png")]
    if pngs:
        p.append("<h2>Graphiques</h2>")
        for c in pngs:
            p.append('<p><img src="{}" width="460"/></p>'.format(QUrl.fromLocalFile(c).toString()))
    if result.method:
        p.append("<h2>Méthode de calcul</h2><p>{}</p>".format(_h(result.method).replace("\n", "<br/>")))
    if result.limits:
        p.append("<h2>Limites méthodologiques</h2><p>{}</p>".format(_h(result.limits).replace("\n", "<br/>")))
    if result.warnings:
        p.append("<h2>Avertissements</h2><ul>" + "".join("<li>{}</li>".format(_h(w)) for w in result.warnings) + "</ul>")
    p.append("</body></html>")
    return "".join(p)


def write_pdf(html_text, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    writer = QPdfWriter(path)
    writer.setResolution(150)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                     QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter))
    doc = QTextDocument()
    doc.setHtml(html_text)
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    printer = getattr(doc, "print_", None) or getattr(doc, "print")
    printer(writer)
    return path


def result_pdf(result, folder):
    path = os.path.join(folder, "{}_fiche.pdf".format(result.slug[:32]))
    write_pdf(result_html(result), path)
    if path not in result.exports:
        result.exports.append(path)
    return path
