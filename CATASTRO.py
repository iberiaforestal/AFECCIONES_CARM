# CATASTRO.py
# CATASTRO NACIONAL - TODO EN UN ARCHIVO
# SIN utils/, SIN catastro.py → FUNCIONA EN STREAMLIT CLOUD

import streamlit as st
import geopandas as gpd
from fpdf import FPDF
import tempfile
from pyproj import Transformer
from shapely.geometry import Point
import requests
from io import BytesIO
import time

# ------------------- CONFIG -------------------
st.set_page_config(page_title="Catastro Nacional", layout="centered")
st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/36/Escudo_de_Espa%C3%B1a.svg/200px-Escudo_de_Espa%C3%B1a_svg.png", width=100)
st.title("Catastro Nacional - Informe Escalonado")

# ------------------- TRANSFORMER -------------------
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# ------------------- WFS CATASTRO -------------------
session = requests.Session()
session.headers.update({
    'User-Agent': 'CatastroApp/1.0 (+https://github.com/tuusuario)',
    'Accept': 'application/json'
})

@st.cache_data(ttl=3600)
def _wfs_request(typename, bbox=None):
    url = "https://ovc.catastro.hacienda.gob.es/INSPIRE/wfs"
    params = {
        'service': 'WFS',
        'version': '1.1.0',
        'request': 'GetFeature',
        'typeName': typename,
        'outputFormat': 'application/json'
    }
    if bbox:
        params['bbox'] = bbox

    for _ in range(3):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return gpd.read_file(BytesIO(r.content))
        except:
            time.sleep(1)
    return gpd.GeoDataFrame()

# ------------------- FUNCIÓN CATASTRO -------------------
def get_catastro_info(x, y):
    lon, lat = transformer.transform(x, y)
    punto = Point(lon, lat)
    buffer = 0.00005  # ~5 metros
    bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"

    # 1. PROVINCIA + CA
    gdf = _wfs_request("AU:AdministrativeUnit", bbox)
    provincia = ca = "N/A"
    if not gdf.empty and gdf.intersects(punto).any():
        row = gdf[gdf.intersects(punto)].iloc[0]
        provincia = row.get('nationalProvinceName', 'N/A')
        ca = row.get('nationalCountryName', 'N/A')

    # 2. MUNICIPIO
    gdf = _wfs_request("AU:AdministrativeBoundary", bbox)
    municipio = "N/A"
    if not gdf.empty and gdf.intersects(punto).any():
        municipio = gdf[gdf.intersects(punto)].iloc[0].get('nationalMunicipalName', 'N/A')

    # 3. PARCELA
    gdf = _wfs_request("CP:CadastralParcel", bbox)
    if not gdf.empty and gdf.intersects(punto).any():
        row = gdf[gdf.intersects(punto)].iloc[0]
        ref = row.get('nationalCadastralReference', 'N/A')
        poligono = ref[7:12] if len(ref) >= 14 else "N/A"
        parcela = ref[12:14] if len(ref) >= 14 else "N/A"
        return {
            "ca": ca,
            "provincia": provincia,
            "municipio": municipio,
            "poligono": poligono,
            "parcela": parcela,
            "ref_catastral": ref,
            "geometry": row.geometry
        }
    return None

# ------------------- INPUT -------------------
col1, col2 = st.columns(2)
with col1:
    x = st.number_input("X (ETRS89)", value=670000, step=1)
with col2:
    y = st.number_input("Y (ETRS89)", value=4610000, step=1)

if st.button("GENERAR INFORME", type="primary"):
    with st.spinner("Consultando Catastro... (5-15 seg)"):
        info = get_catastro_info(x, y)

    if info:
        lon, lat = transformer.transform(x, y)

        # --- RESULTADO ---
        st.success("PARCELA ENCONTRADA")
        st.markdown(f"""
        **Comunidad Autónoma:** {info.get('ca', 'España')}  
        **Provincia:** {info.get('provincia', 'N/A')}  
        **Municipio:** {info.get('municipio', 'N/A')}  
        **Polígono:** {info.get('poligono', 'N/A')}  
        **Parcela:** {info.get('parcela', 'N/A')}  
        **Referencia Catastral:** {info.get('ref_catastral', 'N/A')}  
        **Coordenadas ETRS89:** X={x:.0f}, Y={y:.0f}  
        **Coordenadas WGS84:** Lat={lat:.6f}, Lon={lon:.6f}
        """)

        # --- PDF ---
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, "INFORME CATASTRAL NACIONAL", ln=True, align='C')
        pdf.ln(5)
        pdf.set_font("Arial", size=11)

        datos = [
            ("CA", info.get('ca', 'España')),
            ("Provincia", info.get('provincia', 'N/A')),
            ("Municipio", info.get('municipio', 'N/A')),
            ("Polígono", info.get('poligono', 'N/A')),
            ("Parcela", info.get('parcela', 'N/A')),
            ("Ref. Catastral", info.get('ref_catastral', 'N/A')),
            ("ETRS89", f"X={x:.0f}, Y={y:.0f}"),
            ("WGS84", f"Lat={lat:.6f}, Lon={lon:.6f}"),
            ("Fuente", "Catastro INSPIRE - Hacienda"),
            ("Fecha", "15/11/2025")
        ]

        for label, value in datos:
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(50, 8, f"{label}:", ln=False)
            pdf.set_font("Arial", size=11)
            pdf.cell(0, 8, str(value), ln=True)

        # --- DESCARGAR PDF ---
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf.output(tmp.name)
            st.download_button(
                "DESCARGAR PDF",
                data=open(tmp.name, "rb"),
                file_name=f"catastro_{info.get('ref_catastral', 'xxx')}.pdf",
                mime="application/pdf"
            )
    else:
        st.error("No se encontró parcela. Prueba dentro de una parcela urbana o rústica.")
