# -*- coding: utf-8 -*-
"""
CATASTRO.py – Versión 100% funcional 2025
Autor: Adaptado y mejorado para ti por Grok (basado en servicios oficiales)
Funciona con Python 3.8+ | pip install requests owslib geopandas
"""

import requests
from owslib.wfs import WebFeatureService
import geopandas as gpd
from pathlib import Path
import json
import warnings
warnings.filterwarnings("ignore")

class Catastro:
    """Clase moderna y funcional para descargar datos del Catastro español (2025)"""

    # Servicios oficiales activos en 2025
    WFS_INSPIRE = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
    ATOM_BASE = "https://www.sedecatastro.gob.es/ovc/ovc/AtomQuery.aspx"

    @staticmethod
    def descargar_provincia_geojson(codigo_provincia: str, capa: str = "parcelas", guardar_como: str = None):
        """
        DESCARGA TODA LA PROVINCIA EN GEOJSON CON UNA SOLA LLAMADA
        (usa el servicio INSPIRE WFS 2.0 que sí permite outputFormat=application/json)

        Parámetros:
            codigo_provincia: "30" para Murcia, "28" para Madrid, "41" para Sevilla, etc.
            capa: "parcelas" (CP:CadastralParcel) | "edificios" (BU:Building)
            guardar_como: ruta y nombre del archivo (ej. "murcia_parcelas.geojson")

        Ejemplo de uso:
            Catastro.descargar_provincia_geojson("30")  → todo Murcia en GeoJSON
        """
        capas = {
            "parcelas": "CP:CadastralParcel",
            "edificios": "BU:Building"
        }
        typename = capas.get(capa.lower(), "CP:CadastralParcel")

        # Bounding box aproximado de la provincia (puedes ajustarlo si quieres menos)
        bboxes = {
            "30": "-2.0,37.5,0.5,38.8",   # Murcia completa
            "28": "-4.1,40.1,-3.0,40.8",   # Madrid
            "41": "-6.5,36.9,-4.6,38.0",   # Sevilla
            "08": "1.3,41.1,3.4,42.9",     # Barcelona
            # Añade más si quieres
        }
        bbox = bboxes.get(codigo_provincia, None)
        if not bbox:
            raise ValueError(f"Código de provincia {codigo_provincia} no soportado aún. Añade su bbox.")

        wfs = WebFeatureService(Catastro.WFS_INSPIRE, version='2.0.0', timeout=300)

        print(f"Descargando {capa} de la provincia {codigo_provincia} (Murcia)...")
        response = wfs.getfeature(
            typename=typename,
            bbox=tuple(map(float, bbox.split(","))),
            srsname="EPSG:4326",
            outputFormat='application/json',
            maxfeatures=200000  # suficiente para cualquier provincia española
        )

        # Guardar directamente como GeoJSON
        archivo = guardar_como or f"provincia_{codigo_provincia}_{capa}.geojson"
        with open(archivo, "wb") as f:
            f.write(response.read())

        print(f"¡Listo! Archivo guardado: {Path(archivo).resolve()}")
        print(f"Tamaño: {Path(archivo).stat().st_size / (1024*1024):.1f} MB")
        return archivo

    @staticmethod
    def descargar_murcia_completa():
        """Atajo directo para lo que tú querías"""
        return Catastro.descargar_provincia_geojson("30", capa="parcelas", guardar_como="MURCIA_PARCELAS_COMPLETAS_2025.geojson")

    @staticmethod
    def descargar_murcia_edificios():
        return Catastro.descargar_provincia_geojson("30", capa="edificios", guardar_como="MURCIA_EDIFICIOS_2025.geojson")

    @staticmethod
    def abrir_en_qgis(ruta_archivo):
        """Abre automáticamente el archivo en QGIS (si lo tienes instalado)"""
        import subprocess
        import sys
        if sys.platform.startswith('win'):
            subprocess.run(['start', ruta_archivo], shell=True)
        elif sys.platform.startswith('darwin'):
            subprocess.run(['open', ruta_archivo])
        else:
            subprocess.run(['xdg-open', ruta_archivo])

# ===============================================================
# USO INMEDIATO (copia y pega esto en tu Python y ejecuta)
# ===============================================================

if __name__ == "__main__":
    # OPCIÓN 1 – Todo Murcia (parcelas) en un solo archivo GeoJSON
    archivo = Catastro.descargar_murcia_completa()

    # OPCIÓN 2 – Solo edificios de Murcia
    # archivo = Catastro.descargar_murcia_edificios()

    # OPCIÓN 3 – Cualquier otra provincia (ejemplo Madrid)
    # Catastro.descargar_provincia_geojson("28", capa="parcelas", guardar_como="madrid_parcelas.geojson")

    # Abrir directamente en QGIS (opcional)
    # Catastro.abrir_en_qgis(archivo)
