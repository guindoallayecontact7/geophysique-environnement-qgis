# -*- coding: utf-8 -*-
"""GeoPhysique Statistics Engine.

Statistiques descriptives, répartitions par classe, comparaisons de zones et
exportations TXT, CSV et XLSX communes à tous les modules. Sans dépendance
QGIS : utilisable dans une tâche d'arrière-plan.
"""
import csv
import datetime
import math
import os
import zipfile
from html import escape as _escape

import numpy as np

from .results import Table, MODULE_DIRS, slugify

APP_NAME = "GeoPhysique & Environnement 2.0"
AUTHOR = "Allaye GUINDO"


class ExportSettings:
    csv_separator = ";"
    decimal = ","
    precision = 4


SETTINGS = ExportSettings()


# --------------------------------------------------------------------------
# Calculs
# --------------------------------------------------------------------------
def describe(values, cell_area=None):
    """Statistiques descriptives des valeurs finies."""
    v = np.asarray(values, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"n": 0}
    d = {
        "n": int(v.size),
        "min": float(v.min()), "max": float(v.max()),
        "moyenne": float(v.mean()), "mediane": float(np.median(v)),
        "ecart_type": float(v.std()), "variance": float(v.var()),
        "p05": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95)),
    }
    if cell_area:
        d["superficie_km2"] = v.size * cell_area / 1e6
    return d


DESCRIBE_LABELS = [
    ("n", "Nombre de cellules", ""), ("min", "Minimum", None), ("max", "Maximum", None),
    ("moyenne", "Moyenne", None), ("mediane", "Médiane", None), ("ecart_type", "Écart-type", None),
    ("variance", "Variance", "²"), ("p05", "5e centile", None), ("p95", "95e centile", None),
    ("superficie_km2", "Superficie analysée", "km²"),
]


def describe_table(title, named_arrays, cell_area=None):
    """Tableau comparatif : une ligne par indicateur (nom, tableau, unité)."""
    headers = ["Indicateur", "Unité", "Cellules", "Min", "Max", "Moyenne", "Médiane",
               "Écart-type", "Variance", "P5", "P95"]
    rows = []
    for name, arr, unit in named_arrays:
        d = describe(arr, cell_area)
        if d.get("n", 0) == 0:
            continue
        rows.append([name, unit, d["n"], d["min"], d["max"], d["moyenne"], d["mediane"],
                     d["ecart_type"], d["variance"], d["p05"], d["p95"]])
    return Table(title, headers, rows)


def class_table(title, classes, labels, cell_area, codes=None, extra_cols=None):
    """Répartition des cellules par classe : effectif, superficie et pourcentage."""
    c = np.asarray(classes).ravel()
    c = c[c > 0]
    total = c.size
    codes = codes or list(range(1, len(labels) + 1))
    counts = np.bincount(c.astype(np.int64), minlength=max(codes) + 1) if c.size else np.zeros(max(codes) + 1)
    rows = []
    for code, lab in zip(codes, labels):
        n = int(counts[code]) if code < counts.size else 0
        row = [code, lab, n, n * cell_area / 1e6, 100.0 * n / total if total else 0.0]
        if extra_cols:
            row.extend(extra_cols.get(code, []))
        rows.append(row)
    headers = ["Code", "Classe", "Cellules", "Superficie (km²)", "Part (%)"]
    return Table(title, headers, rows)


def compare_zones(title, rows_by_zone, fields):
    """Tableau comparatif de zones (bassins, sous-bassins) sur une liste de champs."""
    headers = [lab for _, lab, _ in fields]
    units = [u for _, _, u in fields]
    rows = [[r.get(k) for k, _, _ in fields] for r in rows_by_zone]
    return Table(title, headers, rows, units)


# --------------------------------------------------------------------------
# Mise en forme
# --------------------------------------------------------------------------
def fmt(v, precision=None, decimal=None):
    precision = SETTINGS.precision if precision is None else precision
    decimal = SETTINGS.decimal if decimal is None else decimal
    if v is None:
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "oui" if v else "non"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        if not math.isfinite(v):
            return "n.d."
        if v != 0 and (abs(v) >= 1e7 or abs(v) < 10 ** -precision):
            s = "{:.{p}e}".format(v, p=precision - 1)
        else:
            s = "{:.{p}f}".format(v, p=precision).rstrip("0").rstrip(".")
            if s in ("-0", ""):
                s = "0"
        return s.replace(".", decimal) if decimal != "." else s
    return str(v)


def _txt_table(t):
    head = [h + (" ({})".format(u) if u else "") for h, u in zip(t.headers, t.units)]
    body = [[fmt(v) for v in r] for r in t.rows]
    widths = [max([len(h)] + [len(r[i]) for r in body]) for i, h in enumerate(head)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(head, widths)),
             "  ".join("-" * w for w in widths)]
    for r in body:
        lines.append("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    return lines


def result_text(result):
    """Contenu du fichier TXT d'une analyse."""
    L = []
    bar = "=" * 78
    L += [bar, "{} — {}".format(APP_NAME, result.title), bar]
    L.append("Module            : {}".format(result.module_title))
    L.append("Date de traitement: {}".format(result.created.strftime("%d/%m/%Y %H:%M")))
    L.append("Auteur du logiciel: {}".format(AUTHOR))
    L.append("")
    L.append("DONNÉES D'ENTRÉE")
    L.append("-" * 78)
    if result.dem_source:
        L.append("MNT               : {}".format(result.dem_source))
    if result.crs:
        L.append("Système de coord. : {}".format(result.crs))
    if result.resolution:
        L.append("Résolution        : {}".format(result.resolution))
    for lab, val in result.inputs:
        L.append("{:<18}: {}".format(lab, val))
    L.append("")
    L.append("PARAMÈTRES")
    L.append("-" * 78)
    for lab, val, unit in result.params:
        L.append("- {} : {}{}".format(lab, fmt(val) if not isinstance(val, str) else val,
                                     " " + unit if unit else ""))
    if result.summary:
        L.append("")
        L.append("RÉSUMÉ DES RÉSULTATS")
        L.append("-" * 78)
        for lab, val, unit in result.summary:
            L.append("- {} : {}{}".format(lab, fmt(val) if not isinstance(val, str) else val,
                                         " " + unit if unit else ""))
    for t in result.tables:
        L.append("")
        L.append(t.title.upper())
        L.append("-" * 78)
        L.extend(_txt_table(t))
        if t.note:
            L.append("Note : " + t.note)
    if result.layers:
        L.append("")
        L.append("FICHIERS PRODUITS")
        L.append("-" * 78)
        for s in result.layers:
            L.append("- {} : {}{}".format(s.name, s.path, " (couche {})".format(s.layer) if s.layer else ""))
    if result.method:
        L.append("")
        L.append("MÉTHODE DE CALCUL")
        L.append("-" * 78)
        L.extend(result.method.strip().splitlines())
    if result.limits:
        L.append("")
        L.append("LIMITES MÉTHODOLOGIQUES")
        L.append("-" * 78)
        L.extend(result.limits.strip().splitlines())
    if result.warnings:
        L.append("")
        L.append("AVERTISSEMENTS")
        L.append("-" * 78)
        L.extend("- " + w for w in result.warnings)
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Exportations
# --------------------------------------------------------------------------
def write_txt(result, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(result_text(result))
    return path


def write_csv(table, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=SETTINGS.csv_separator)
        w.writerow([h + (" ({})".format(u) if u else "") for h, u in zip(table.headers, table.units)])
        for r in table.rows:
            w.writerow([fmt(v, precision=10) if isinstance(v, (float, np.floating)) else fmt(v) for v in r])
    return path


def _sheet_name(title, used):
    bad = '[]:*?/\\'
    name = "".join("_" if ch in bad else ch for ch in title)[:31] or "Feuille"
    base, i = name, 2
    while name in used:
        suffix = " ({})".format(i)
        name = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


def write_xlsx(result_or_tables, path, info_rows=None):
    """Classeur Excel : une feuille « Informations » puis une feuille par tableau."""
    if hasattr(result_or_tables, "tables"):
        res = result_or_tables
        tables = res.tables
        info_rows = info_rows or (
            [("Analyse", res.title), ("Module", res.module_title),
             ("Date", res.created.strftime("%d/%m/%Y %H:%M")), ("MNT", res.dem_source),
             ("SCR", res.crs), ("Résolution", res.resolution)]
            + [(lab, v) for lab, v in res.inputs]
            + [("Paramètre : " + lab, "{}{}".format(v, " " + u if u else "")) for lab, v, u in res.params]
            + [("Résultat : " + lab, "{}{}".format(fmt(v) if not isinstance(v, str) else v, " " + u if u else ""))
               for lab, v, u in res.summary])
    else:
        tables = result_or_tables
        info_rows = info_rows or []
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    sheets = [("Informations", ["Élément", "Valeur"], [list(r) for r in info_rows])]
    for t in tables:
        sheets.append((t.title, [h + (" ({})".format(u) if u else "") for h, u in zip(t.headers, t.units)], t.rows))
    try:
        import openpyxl
        from openpyxl.styles import Font
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        used = set()
        for title, headers, rows in sheets:
            ws = wb.create_sheet(_sheet_name(title, used))
            ws.append(headers)
            for c in ws[1]:
                c.font = Font(bold=True)
            for r in rows:
                ws.append([_xl_value(v) for v in r])
            for i, h in enumerate(headers, start=1):
                width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:200] if i - 1 < len(r)])
                ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = min(60, width + 2)
        wb.save(path)
    except ImportError:
        _write_xlsx_minimal(path, sheets)
    return path


def _xl_value(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, (dict, list, tuple)):
        return str(v)
    return v


def _write_xlsx_minimal(path, sheets):
    """Écriture XLSX sans dépendance (repli si openpyxl est absent)."""
    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    used = set()
    names = [_sheet_name(t, used) for t, _, _ in sheets]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join('<Override PartName="/xl/worksheets/sheet{}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(i + 1) for i in range(len(sheets)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join('<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(_escape(n, quote=True), i + 1, i + 1) for i, n in enumerate(names))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join('<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{0}.xml"/>'.format(i + 1) for i in range(len(sheets)))
                   + "</Relationships>")
        for si, (_, headers, rows) in enumerate(sheets):
            xml = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
            for ri, row in enumerate([headers] + list(rows)):
                xml.append('<row r="{}">'.format(ri + 1))
                for ci, v in enumerate(row):
                    v = _xl_value(v)
                    ref = "{}{}".format(col(ci), ri + 1)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        xml.append('<c r="{}"><v>{}</v></c>'.format(ref, v))
                    elif v is not None:
                        xml.append('<c r="{}" t="inlineStr"><is><t>{}</t></is></c>'.format(ref, _escape(str(v), quote=False)))
                xml.append("</row>")
            xml.append("</sheetData></worksheet>")
            z.writestr("xl/worksheets/sheet{}.xml".format(si + 1), "".join(xml))


def export_result(result, folder, formats=("txt", "csv", "xlsx")):
    """Exporte les statistiques d'une analyse dans `folder`. Renvoie la liste des fichiers."""
    os.makedirs(folder, exist_ok=True)
    # noms courts : les chemins Windows sont limités à 260 caractères
    base = os.path.join(folder, result.slug[:32])
    out = []
    if "txt" in formats:
        out.append(write_txt(result, base + "_statistiques.txt"))
    if "csv" in formats:
        for i, t in enumerate(result.tables, start=1):
            out.append(write_csv(t, os.path.join(folder, "tableau_{:02d}_{}.csv".format(i, slugify(t.title)[:32]))))
    if "xlsx" in formats:
        out.append(write_xlsx(result, base + "_statistiques.xlsx"))
    for p in out:
        if p not in result.exports:
            result.exports.append(p)
    return out


def module_folder(root, module):
    return os.path.join(root, MODULE_DIRS.get(module, module))


def now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
