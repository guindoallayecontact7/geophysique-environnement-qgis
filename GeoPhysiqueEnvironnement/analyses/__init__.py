# -*- coding: utf-8 -*-
"""Chaînes de traitement des modules (exécutées dans une tâche d'arrière-plan).

Chaque fonction `run(params, ctx, feedback)` lit le MNT depuis son chemin,
calcule avec le noyau `core`, écrit ses fichiers dans l'espace de travail et
renvoie un AnalysisResult. Aucune couche QGIS n'est manipulée ici.
"""
