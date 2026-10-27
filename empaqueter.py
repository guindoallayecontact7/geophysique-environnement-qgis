"""Construit le zip de l'extension pour plugins.qgis.org dans dist/."""
import configparser
import pathlib
import zipfile

RACINE = pathlib.Path(__file__).resolve().parent
DOSSIER = "GeoPhysiqueEnvironnement"
EXCLUS = {"__pycache__", ".git", ".DS_Store", "Thumbs.db"}


def main():
    meta = configparser.ConfigParser(interpolation=None)
    meta.read(RACINE / DOSSIER / "metadata.txt", encoding="utf-8")
    version = meta["general"]["version"]

    sortie = RACINE / "dist" / "{}-{}.zip".format(DOSSIER, version)
    sortie.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as zf:
        for chemin in sorted((RACINE / DOSSIER).rglob("*")):
            relatif = chemin.relative_to(RACINE)
            if chemin.is_dir() or EXCLUS.intersection(relatif.parts) or chemin.suffix == ".pyc":
                continue
            zf.write(chemin, relatif.as_posix())
    print(sortie)


if __name__ == "__main__":
    main()
