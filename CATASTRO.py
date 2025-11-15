# CATASTRO.py
# CATASTRO NACIONAL - DESPLEGABLES CASCADA + COORDENADAS
# UN ARCHIVO → FUNCIONA EN STREAMLIT CLOUD

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
st.title("Catastro Nacional - Cascada + Coordenadas")

# ------------------- TRANSFORMER -------------------
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# ------------------- WFS CATASTRO -------------------
session = requests.Session()
session.headers.update({'User-Agent': 'CatastroApp/1.0'})

@st.cache_data(ttl=86400)
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

# ------------------- CARGAR DESPLEGABLES -------------------
@st.cache_data(ttl=86400)
def get_comunidades():
    gdf = _wfs_request("AU:AdministrativeUnit")
    if gdf.empty: return []
    return sorted(gdf['nationalCountryName'].dropna().unique())

@st.cache_data(ttl=86400)
def get_provincias(ca):
    gdf = _wfs_request("AU:AdministrativeUnit", cql_filter=f"nationalCountryName='{ca}'")
    if gdf.empty: return []
    return sorted(gdf['nationalProvinceName'].dropna().unique())

@st.cache_data(ttl=86400)
def get_municipios(ca, provincia):
    gdf = _wfs_request("AU:AdministrativeBoundary", cql_filter=f"nationalProvinceName='{provincia}'")
    if gdf.empty: return []
    return sorted(gdf['nationalMunicipalName'].dropna().unique())

# ------------------- POR COORDENADAS -------------------
def get_by_coordenadas(x, y):
    lon, lat = transformer.transform(x, y)
    punto = Point(lon, lat)
    buffer = 0.00005
    bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"

    gdf = _wfs_request("AU:AdministrativeUnit", bbox)
    ca = provincia = "N/A"
    if not gdf.empty and gdf.intersects(punto).any():
        row = gdf[gdf.intersects(punto)].iloc[0]
        ca = row.get('nationalCountryName', 'N/A')
        provincia = row.get('nationalProvinceName', 'N/A')

    gdf = _wfs_request("AU:AdministrativeBoundary", bbox)
    municipio = "N/A"
    if not gdf.empty and gdf.intersects(punto).any():
        municipio = gdf[gdf.intersects(punto)].iloc[0].get('nationalMunicipalName', 'N/A')

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

# ------------------- POR CASCADA -------------------
def get_by_cascada(ca, provincia, municipio, poligono, parcela):
    pol = poligono.zfill(5)
    par = parcela.zfill(2)
    cql = f"nationalCadastralReference LIKE '%{pol}{par}'"
    gdf = _wfs_request("CP:CadastralParcel", cql_filter=cql)
    if gdf.empty: return None
    gdf = gdf[gdf['nationalCadastralReference'].str.startswith(municipio[:5])]
    if gdf.empty: return None
    row = gdf.iloc[0]
    ref = row.get('nationalCadastralReference', 'N/A')
    return {
        "ca": ca, "provincia": provincia, "municipio": municipio,
        "poligono": pol, "parcela": par, "ref_catastral": ref,
        "x": "N/A", "y": "N/A", "lat": "N/A", "lon": "N/A"
    }

# ------------------- INPUT -------------------
tab1, tab2 = st.tabs(["Por Coordenadas", "Por Cascada"])

info = None

# === POR COORDENADAS ===
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        x = st.number_input("X (ETRS89)", value=670000, step=1)
    with col2:
        y = st.number_input("Y (ETRS89)", value=4610000, step=1)
    if st.button("BUSCAR POR COORDENADAS", type="primary"):
        with st.spinner("Consultando..."):
            info = get_by_coordenadas(x, y)

# === POR CASCADA ===
with tab2:
    comunidades = get_comunidades()
    ca = st.selectbox("Comunidad Autónoma", [""] + comunidades)
    provincias = get_provincias(ca) if ca else []
    provincia = st.selectbox("Provincia", [""] + provincias)
    municipios = get_municipios(ca, provincia) if provincia else []
    municipio = st.selectbox("Municipio", [""] + municipios)

    col1, col2 = st.columns(2)
    with col1:
        poligono = st.text_input("Polígono", "00123")
    with col2:
        parcela = st.text_input("Parcela", "45")

    if st.button("BUSCAR POR CASCADA", type="primary"):
        if ca and provincia and municipio:
            with st.spinner("Buscando parcela..."):
                info = get_by_cascada(ca, provincia, municipio, poligono, parcela)
        else:
            st.error("Selecciona CA, Provincia y Municipio")

# ------------------- RESULTADO + PDF -------------------
if info:
    st.success("PARCELA ENCONTRADA")
    st.markdown(f"""
    **Comunidad Autónoma:** {info.get('ca', 'España')}  
    **Provincia:** {info.get('provincia', 'N/A')}  
    **Municipio:** {info.get('municipio', 'N/A')}  
    **Polígono:** {info.get('poligono', 'N/A')}  
    **Parcela:** {info.get('parcela', 'N/A')}  
    **Referencia Catastral:** {info.get('ref_catastral', 'N/A')}  
    **ETRS89:** X={info.get('x', 'N/A')}, Y={info.get('y', 'N/A')}  
    **WGS84:** Lat={info.get('lat', 'N/A')}, Lon={info.get('lon', 'N/A')}
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
        ("ETRS89", f"X={info.get('x', 'N/A')}, Y={info.get('y', 'N/A')}"),
        ("WGS84", f"Lat={info.get('lat', 'N/A')}, Lon={info.get('lon', 'N/A')}"),
        ("Fuente", "Catastro INSPIRE"),
        ("Fecha", "15/11/2025")
    ]

    for label, value in datos:
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(50, 8, f"{label}:", ln=False)
        pdf.set_font("Arial", size=11)
        pdf.cell(0, 8, str(value), ln=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf.output(tmp.name)
        st.download_button(
            "DESCARGAR PDF",
            data=open(tmp.name, "rb"),
            file_name=f"catastro_{info.get('ref_catastral', 'xxx')}.pdf",
            mime="application/pdf"
        )
