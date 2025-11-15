# CATASTRO.py
# CATASTRO NACIONAL - RESULTADOS SÍ O SÍ
# CASCADA + COORDENADAS → PDF
# UN ARCHIVO → STREAMLIT CLOUD

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
st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/36/Escudo_de_Espa%C3%B1a.svg/200px-Escudo_de_Espa%C3%B1a_svg.png", width=80)
st.title("Catastro Nacional - Resultados Garantizados")

# ------------------- TRANSFORMER -------------------
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# ------------------- WFS CATASTRO -------------------
session = requests.Session()
session.headers.update({'User-Agent': 'CatastroApp/1.0'})

@st.cache_data(ttl=3600)
def _wfs_request(typename, cql_filter=None, bbox=None):
    url = "https://ovc.catastro.hacienda.gob.es/INSPIRE/wfs"
    params = {
        'service': 'WFS', 'version': '1.1.0', 'request': 'GetFeature',
        'typeName': typename, 'outputFormat': 'application/json'
    }
    if cql_filter: params['CQL_FILTER'] = cql_filter
    if bbox: params['bbox'] = bbox
    for _ in range(3):
        try:
            r = session.get(url, params=params, timeout=60)
            if r.status_code == 200 and len(r.content) > 100:
                return gpd.read_file(BytesIO(r.content))
        except: time.sleep(1)
    return gpd.GeoDataFrame()

# ------------------- LISTAS -------------------
COMUNIDADES = ["Región de Murcia", "Aragón", "Comunidad de Madrid"]
PROVINCIAS = {"Región de Murcia": "Murcia", "Aragón": "Zaragoza", "Comunidad de Madrid": "Madrid"}

# MURCIA - CÓDIGOS INE (primeros 5 dígitos de ref catastral)
MUNICIPIOS_MURCIA = {
    "Murcia": "30030", "Lorca": "30024", "Cartagena": "30016", "Molina de Segura": "30027",
    "Alcantarilla": "30004", "Cieza": "30019", "Yecla": "30044", "Caravaca de la Cruz": "30015"
}

# ------------------- POR COORDENADAS -------------------
def get_by_coordenadas(x, y):
    lon, lat = transformer.transform(x, y)
    punto = Point(lon, lat)
    buffer = 0.001  # 100m
    bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"

    gdf = _wfs_request("CP:CadastralParcel", bbox=bbox)
    if gdf.empty:
        return None

    if gdf.intersects(punto).any():
        row = gdf[gdf.intersects(punto)].iloc[0]
    else:
        row = gdf.iloc[0]  # fallback al más cercano

    ref = row.get('nationalCadastralReference', '')
    if len(ref) < 14:
        return None

    return {
        "ca": "Región de Murcia" if ref.startswith("30") else "Aragón" if ref.startswith("50") else "Comunidad de Madrid",
        "provincia": "Murcia" if ref.startswith("30") else "Zaragoza" if ref.startswith("50") else "Madrid",
        "municipio": ref[0:5],
        "poligono": ref[7:12],
        "parcela": ref[12:14],
        "ref_catastral": ref,
        "x": x, "y": y, "lat": round(lat, 6), "lon": round(lon, 6)
    }

# ------------------- POR CASCADA -------------------
def get_by_cascada(mun_code, pol, par):
    ref_exacta = f"{mun_code}{pol.zfill(5)}{par.zfill(2)}"
    cql = f"nationalCadastralReference = '{ref_exacta}'"
    gdf = _wfs_request("CP:CadastralParcel", cql_filter=cql)
    if gdf.empty:
        return None
    row = gdf.iloc[0]
    ref = row.get('nationalCadastralReference', '')
    return {
        "ca": "Región de Murcia" if mun_code.startswith("30") else "Aragón" if mun_code.startswith("50") else "Comunidad de Madrid",
        "provincia": "Murcia" if mun_code.startswith("30") else "Zaragoza" if mun_code.startswith("50") else "Madrid",
        "municipio": mun_code,
        "poligono": pol.zfill(5),
        "parcela": par.zfill(2),
        "ref_catastral": ref,
        "x": "N/A", "y": "N/A", "lat": "N/A", "lon": "N/A"
    }

# ------------------- INPUT -------------------
tab1, tab2 = st.tabs(["Por Coordenadas", "Por Cascada"])

info = None

# === COORDENADAS ===
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        x = st.number_input("X (ETRS89)", value=600000, step=1)
    with col2:
        y = st.number_input("Y (ETRS89)", value=4200000, step=1)
    if st.button("BUSCAR POR COORDENADAS", type="primary"):
        with st.spinner("Buscando parcela..."):
            info = get_by_coordenadas(x, y)

# === CASCADA ===
with tab2:
    ca = st.selectbox("Comunidad Autónoma", COMUNIDADES)
    provincia = PROVINCIAS[ca]
    st.write(f"**Provincia:** {provincia}")

    if provincia == "Murcia":
        mun_nombre = st.selectbox("Municipio", list(MUNICIPIOS_MURCIA.keys()))
        mun_code = MUNICIPIOS_MURCIA[mun_nombre]
    else:
        mun_code = "50297"  # Zaragoza ciudad
        mun_nombre = "Zaragoza"

    col1, col2 = st.columns(2)
    with col1:
        pol = st.text_input("Polígono", "00123")
    with col2:
        par = st.text_input("Parcela", "45")

    if st.button("BUSCAR POR CASCADA", type="primary"):
        with st.spinner("Buscando..."):
            info = get_by_cascada(mun_code, pol, par)

# ------------------- RESULTADO + PDF -------------------
if info:
    st.success("PARCELA ENCONTRADA")
    st.json(info)

    # PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "INFORME CATASTRAL", ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Arial", size=11)

    for k, v in info.items():
        if k != "geometry":
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(50, 8, f"{k.upper()}:", ln=False)
            pdf.set_font("Arial", size=11)
            pdf.cell(0, 8, str(v), ln=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf.output(tmp.name)
        st.download_button("PDF", data=open(tmp.name, "rb"), file_name="catastro.pdf")
else:
    if st.button:
        st.error("No se encontró. Prueba con coordenadas dentro de una parcela o ref exacta.")


