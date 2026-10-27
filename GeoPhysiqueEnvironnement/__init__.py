def classFactory(iface):
    from .plugin import GeoPhysiquePlugin
    return GeoPhysiquePlugin(iface)
