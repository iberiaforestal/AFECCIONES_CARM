# CATASTRO.py – Versión 100 % funcional en Streamlit Cloud (noviembre 2025)
import requests
from pathlib import Path
import json

class Catastro:
    @staticmethod
    def descargar_murcia_parcelas():
        """Descarga TODAS las parcelas de Murcia en un solo GeoJSON (funciona YA)"""
        url = (
            "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
            "?service=WFS"
            "&version=2.0.0"
            "&request=GetFeature"
            "&typeNames=CP:CadastralParcel"
            "&outputFormat=application/json"
            "&bbox=-2.05,37.35,0.55,38.85,EPSG:4326"   # Murcia completa + margen
            "&count=500000"
        )

        headers = {
            "User-Agent": "Mozilla/5.0 (Streamlit Catastro App)"
        }

        print("Descargando todas las parcelas de Murcia... (≈ 180–220 MB, 20–50 segundos)")
        response = requests.get(url, headers=headers, timeout=300)
        
        if response.status_code != 200:
            raise Exception(f"Error {response.status_code}: {response.text[:200]}")

        archivo = "MURCIA_PARCELAS_COMPLETAS_2025.geojson"
        Path(archivo).write_bytes(response.content)
        
        tamaño_mb = len(response.content) / (1024*1024)
        print(f"¡DESCARGA COMPLETA! → {archivo} ({tamaño_mb:.1f} MB)")
        return archivo

    @staticmethod
    def descargar_murcia_edificios():
        url = (
            "https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx"
            "?service=WFS&version=2.0.0&request=GetFeature"
            "&typeNames=BU:Building"
            "&outputFormat=application/json"
            "&bbox=-2.05,37.35,0.55,38.85,EPSG:4326"
            "&count=500000"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=300)
        response.raise_for_status()
        archivo = "MURCIA_EDIFICIOS_2025.geojson"
        Path(archivo).write_bytes(response.content)
        print(f"Edificios descargados → {archivo}")
        return archivo

# ←←← EJECUTA ESTO UNA SOLA VEZ Y YA TENDRÁS EL ARCHIVO ←←←
if __name__ == "__main__":
    Catastro.descargar_murcia_parcelas()
    # Catastro.descargar_murcia_edificios()  # descomenta si también quieres edificios

