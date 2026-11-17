# -*- coding: utf-8 -*-
"""Outils de carte : saisie d'un point (exutoire) et tracé d'une ligne (profil)."""
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker
from qgis.core import QgsPointXY, QgsGeometry

try:
    from qgis.core import Qgis
    _LINE = Qgis.GeometryType.Line
except AttributeError:  # QGIS < 3.30
    from qgis.core import QgsWkbTypes
    _LINE = getattr(QgsWkbTypes, "LineGeometry")


class PointTool(QgsMapTool):
    """Clic gauche : émet le point (coordonnées du canevas)."""

    picked = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.marker = None

    def canvasReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pt = e.mapPoint()
        self.show_marker(pt)
        self.picked.emit(QgsPointXY(pt))

    def show_marker(self, pt):
        self.clear()
        m = QgsVertexMarker(self.canvas())
        m.setCenter(QgsPointXY(pt))
        m.setColor(QColor("#e31a1c"))
        m.setIconSize(14)
        m.setIconType(QgsVertexMarker.IconType.ICON_CROSS)
        m.setPenWidth(3)
        self.marker = m

    def clear(self):
        if self.marker is not None:
            self.canvas().scene().removeItem(self.marker)
            self.marker = None

    def deactivate(self):
        super().deactivate()


class LineTool(QgsMapTool):
    """Clic gauche : ajoute un sommet ; clic droit : termine la ligne (≥ 2 sommets)."""

    finished = pyqtSignal(list)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.points = []
        self.band = QgsRubberBand(canvas, _LINE)
        self.band.setColor(QColor(227, 26, 28, 200))
        self.band.setWidth(2)

    def canvasMoveEvent(self, e):
        if self.points:
            self.band.setToGeometry(QgsGeometry.fromPolylineXY(self.points + [QgsPointXY(e.mapPoint())]), None)

    def canvasReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.points.append(QgsPointXY(e.mapPoint()))
            self.band.setToGeometry(QgsGeometry.fromPolylineXY(self.points), None)
        elif e.button() == Qt.MouseButton.RightButton:
            if len(self.points) >= 2:
                pts = list(self.points)
                self.finished.emit(pts)
            self.reset()

    def reset(self):
        self.points = []
        self.band.reset(_LINE)

    def deactivate(self):
        self.reset()
        super().deactivate()


try:
    _POLY = Qgis.GeometryType.Polygon
except (NameError, AttributeError):  # QGIS < 3.30
    from qgis.core import QgsWkbTypes as _W
    _POLY = getattr(_W, "PolygonGeometry")


class RectTool(QgsMapTool):
    """Rectangle tiré à la souris (appui, glisser, relâcher) : émet un QgsRectangle (coordonnées du canevas)."""

    finished = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start = None
        self.band = QgsRubberBand(canvas, _POLY)
        self.band.setColor(QColor(227, 26, 28, 60))
        self.band.setStrokeColor(QColor(227, 26, 28))
        self.band.setWidth(2)

    def _rect(self, p):
        from qgis.core import QgsRectangle
        return QgsRectangle(self.start, QgsPointXY(p))

    def canvasPressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.start = QgsPointXY(e.mapPoint())

    def canvasMoveEvent(self, e):
        if self.start is not None:
            self.band.setToGeometry(QgsGeometry.fromRect(self._rect(e.mapPoint())), None)

    def canvasReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        r = self._rect(e.mapPoint())
        self.start = None
        self.band.reset(_POLY)
        if r.width() > 0 and r.height() > 0:
            self.finished.emit(r)

    def deactivate(self):
        self.band.reset(_POLY)
        super().deactivate()
