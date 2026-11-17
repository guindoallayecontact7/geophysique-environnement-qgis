# -*- coding: utf-8 -*-
"""Exécution des traitements dans une tâche QGIS (sans bloquer l'interface)."""
import traceback

from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import QgsTask

from ..analyses.common import TaskFeedback
from ..core.grid import Canceled


class JobTask(QgsTask):
    """Lance fn(params, ctx, feedback) dans un fil secondaire."""

    message = pyqtSignal(str)

    def __init__(self, description, fn, params, ctx, on_done, on_error):
        super().__init__(description, QgsTask.Flag.CanCancel)
        self.fn = fn
        self.params = params
        self.ctx = ctx
        self.on_done = on_done
        self.on_error = on_error
        self.result_obj = None
        self.error = None
        self.canceled_by_user = False

    def run(self):
        fb = TaskFeedback(progress=self.setProgress, message=self.message.emit, canceled=self.isCanceled)
        try:
            self.result_obj = self.fn(self.params, self.ctx, fb)
            return True
        except Canceled as exc:
            self.canceled_by_user = True
            self.error = str(exc)
            return False
        except MemoryError:
            self.error = ("Mémoire insuffisante pour ce MNT. Découpez la zone d'étude ou rééchantillonnez "
                          "le MNT (rubrique « Gestion des MNT »).")
            return False
        except Exception as exc:  # noqa: BLE001 - toute erreur est rapportée à l'utilisateur
            self.error = "{}\n\n{}".format(exc, traceback.format_exc())
            return False

    def finished(self, ok):
        if ok and self.result_obj is not None:
            self.on_done(self.result_obj)
        else:
            if self.isCanceled() and not self.error:
                self.error = "Traitement annulé."
            self.on_error(self.error or "Erreur inconnue.", self.canceled_by_user or self.isCanceled())
