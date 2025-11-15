# CATASTRO.py
# CATASTRO NACIONAL - 2 OPCIONES: COORDENADAS O DATOS
# UN SOLO ARCHIVO → FUNCIONA EN STREAMLIT CLOUD

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
st.title("Catastro Nacional - 2 Opciones")

# ------------------- TRANSFORMER -------------------
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# ------------------- WFS CATASTRO -------------------
session = requests.Session()
session.headers.update({'User-Agent': 'CatastroApp/1.0'})

@st.cache_data(ttl=3600)
def _wfs_request(typename, bbox=None, cql_filter=None):
    url = "https://ovc.catastro.hacienda.gob.es/INSPIRE/wfs"
    params = {
        'service': 'WFS', 'version': '1.1.0', 'request': 'GetFeature',
        'typeName': typename, 'outputFormat': 'application/json'
    }
    if bbox: params['bbox'] = bbox
    if cql_filter: params['CQL_FILTER'] = cql_filter

    for _ in range(3):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return gpd.read_file(BytesIO(r.content))
        except: time.sleep(1)
    return gpd.GeoDataFrame()

# ------------------- FUNCIÓN POR COORDENADAS -------------------
def get_by_coordenadas(x, y):
    lon, lat = transformer.transform(x, y)
    punto = Point(lon, lat)
    buffer = 0.00005
    bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"

    # Provincia + CA
    gdf = _wfs_request("AU:AdministrativeUnit", bbox)
    provincia = ca = "N/A"
    if not gdf.empty and gdf.intersects(punto).any():
        row = gdf[gdf.intersects(punto)].iloc[0]
        provincia = row.get('nationalProvinceName', 'N/A')
        ca = row.get('nationalCountryName', 'N/A')

    # Municipio
    gdf = _wfs_request("AU:AdministrativeBoundary", bbox)
    municipio = "N/A"
    if not gdf.empty and gdf.intersects(punto).any():
        municipio = gdf[gdf.intersects(punto)].iloc[0].get('nationalMunicipalName', 'N/A')

    # Parcela
    gdf = _wfs_request("CP:CadastralParcel", bbox)
    if not gdf.empty and gdf.intersects(punto).any():
        row = gdf[gdf.intersects(punto)].iloc[0]
        ref = row.get('nationalCadastralReference', 'N/A')
        poligono = ref[7:12] if len(ref) >= 14 else "N/A"
        parcela = ref[12:14] if len(ref) >= 14 else "N/A"
        return {
            "ca": ca, "provincia": provincia, "municipio": municipio,
            "poligono": poligono, "parcela": parcela, "ref_catastral": ref,
            "x": x, "y": y, "lat": lat, "lon": lon
        }
    return None

# ------------------- FUNCIÓN POR DATOS -------------------
def get_by_datos(provincia, poligono, parcela):
    # Construir filtro CQL (aproximado)
    pol = poligono.zfill(5)
    par = parcela.zfill(2)
    prov_code = provincia[:2].upper()
    cql = f"nationalCadastralReference LIKE '{prov_code}____{pol}{par}'"
    gdf = _wfs_request("CP:CadastralParcel", cql_filter=cql)
    if gdf.empty:
        return None
    row = gdf.iloc[0]
    ref = row.get('nationalCadastralReference', 'N/A')
    return {
        "ca": "España",
        "provincia": provincia,
        "municipio": ref[0:5] if len(ref) >= 5 else "N/A",
        "poligono": pol,
        "parcela": par,
        "ref_catastral": ref,
        "x": "N/A", "y": "N/A", "lat": "N/A", "lon": "N/A"
    }

# ------------------- INPUT -------------------
tab1, tab2 = st.tabs(["Por Coordenadas", "Por Datos"])

info = None
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        x = st.number_input("X (ETRS89)", value=670000, step=1)
    with col2:
        y = st.number_input("Y (ETRS89)", value=4610000, step=1)
    if st.button("BUSCAR POR COORDENADAS", type="primary"):
        with st.spinner("Consultando Catastro..."):
            info = get_by_coordenadas(x, y)

with tab2:
    col1, col2 = st.columns(2)
    with col1:
        provincia = st.text_input("Provincia", "Zaragoza")
        poligono = st.text_input("Polígono", "00123")
    with col2:
        parcela = st.text_input("Parcela", "45")
    if st.button("BUSCAR POR DATOS", type="primary"):
        with st.spinner("Buscando parcela..."):
            info = get_by_datos(provincia, poligono, parcela)

# ------------------- RESULTADO + PDF -------------------
if info:
    st.success("PARCELA ENCONTRADA")
    st.markdown(f"""
    **Comunidad Autónoma:** {info.get('ca', 'España')}  
    **Provincia:** {info.get('provincia', 'N/A')}  
    **Municipio:** {info.get('municipio', 'N/A')}  
    **Polígono:** {info.get('poligono', 'N/A')}  
    **Parcela:** {info.get('parcela', '
