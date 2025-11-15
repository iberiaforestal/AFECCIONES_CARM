# CATASTRO.py
# CATASTRO NACIONAL - CASCADA + COORDENADAS
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

# ------------------- LISTAS ESTÁTICAS -------------------
COMUNIDADES = [
    "Andalucía", "Aragón", "Principado de Asturias", "Illes Balears", "Canarias",
    "Cantabria", "Castilla-La Mancha", "Castilla y León", "Cataluña",
    "Ceuta", "Comunidad Valenciana", "Extremadura", "Galicia", "Comunidad de Madrid",
    "Región de Murcia", "Comunidad Foral de Navarra", "País Vasco", "La Rioja", "Melilla"
]

PROVINCIAS_POR_CA = {
    "Andalucía": ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"],
    "Aragón": ["Huesca", "Teruel", "Zaragoza"],
    "Principado de Asturias": ["Asturias"],
    "Illes Balears": ["Illes Balears"],
    "Canarias": ["Las Palmas", "Santa Cruz de Tenerife"],
    "Cantabria": ["Cantabria"],
    "Castilla-La Mancha": ["Albacete", "Ciudad Real", "Cuenca", "Guadalajara", "Toledo"],
    "Castilla y León": ["Ávila", "Burgos", "León", "Palencia", "Salamanca", "Segovia", "Soria", "Valladolid", "Zamora"],
    "Cataluña": ["Barcelona", "Girona", "Lleida", "Tarragona"],
    "Ceuta": ["Ceuta"],
    "Comunidad Valenciana": ["Alicante", "Castellón", "Valencia"],
    "Extremadura": ["Badajoz", "Cáceres"],
    "Galicia": ["A Coruña", "Lugo", "Ourense", "Pontevedra"],
    "Comunidad de Madrid": ["Madrid"],
    "Región de Murcia": ["Murcia"],
    "Comunidad Foral de Navarra": ["Navarra"],
    "País Vasco": ["Álava", "Bizkaia", "Gipuzkoa"],
    "La Rioja": ["La Rioja"],
    "Melilla": ["Melilla"]
}

# ------------------- FUNCIÓN POR COORDENADAS -------------------
def get_by_coordenadas(x, y):
    lon, lat = transformer.transform(x, y)
    punto = Point(lon, lat)
    buffer = 0.0001  # ~10m
    bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"

    gdf = _wfs_request("CP:CadastralParcel", bbox)
    if gdf.empty or not gdf.intersects(punto).any():
        return None

    row = gdf[gdf.intersects(punto)].iloc[0]
    ref = row.get('nationalCadastralReference', 'N/A')
    if len(ref) < 14:
        return None

    # Extraer CA, Provincia, Municipio desde ref
    cod_ca = ref[0:2]
    cod_prov = ref[0:2]
    cod_mun = ref[0:5]

    CA_NOMBRE = {
        "01": "Andalucía", "02": "Aragón", "03": "Principado de Asturias", "04": "Illes Balears",
        "05": "Canarias", "06": "Cantabria", "07": "Castilla-La Mancha", "08": "Castilla y León",
        "09": "Cataluña", "51": "Ceuta", "10": "Comunidad Valenciana", "11": "Extremadura",
        "12": "Galicia", "13": "Comunidad de Madrid", "14": "Región de Murcia",
        "15": "Comunidad Foral de Navarra", "16": "País Vasco", "17": "La Rioja", "52": "Melilla"
    }

    PROV_NOMBRE = {
        "04": "Albacete", "13": "Ciudad Real", "16": "Cuenca", "19": "Guadalajara", "45": "Toledo",
        "22": "Huesca", "44": "Teruel", "50": "Zaragoza", "28": "Madrid", "30": "Murcia"
    }

    return {
        "ca": CA_NOMBRE.get(cod_ca, "N/A"),
        "provincia": PROV_NOMBRE.get(cod_prov, "N/A"),
        "municipio": cod_mun,
        "poligono": ref[7:12],
        "parcela": ref[12:14],
        "ref_catastral": ref,
        "x": x, "y": y, "lat": round(lat, 6), "lon": round(lon, 6)
    }

# ------------------- FUNCIÓN POR CASCADA -------------------
def get_by_cascada(ca, provincia, municipio_code, poligono, parcela):
    pol = poligono.zfill(5)
    par = parcela.zfill(2)
    ref_pattern = f"{municipio_code}{pol}{par}"
    cql = f"nationalCadastralReference LIKE '%{ref_pattern}'"
    gdf = _wfs_request("CP:CadastralParcel", cql_filter=cql)
    if gdf.empty:
        return None
    row = gdf.iloc[0]
    ref = row.get('nationalCadastralReference', 'N/A')
    return {
        "ca": ca,
        "provincia": provincia,
        "municipio": municipio_code,
        "poligono": pol,
        "parcela": par,
        "ref_catastral": ref,
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
        with st.spinner("Buscando parcela..."):
            info = get_by_coordenadas(x, y)

# === POR CASCADA ===
with tab2:
    ca = st.selectbox("Comunidad Autónoma", [""] + COMUNIDADES)
    provincias = PROVINCIAS_POR_CA.get(ca, []) if ca else []
    provincia = st.selectbox("Provincia", [""] + provincias)

    # Código INE por provincia (ejemplo)
    CODIGO_INE = {
        "Zaragoza": "50250", "Huesca": "22125", "Teruel": "44150", "Madrid": "28079"
    }
    codigo_mun = CODIGO_INE.get(provincia, "00000")

    col1, col2 = st.columns(2)
    with col1:
        poligono = st.text_input("Polígono", "00123")
    with col2:
        parcela = st.text_input("Parcela", "45")

    if st.button("BUSCAR POR CASCADA", type="primary"):
        if ca and provincia and codigo_mun != "00000":
            with st.spinner("Buscando..."):
                info = get_by_cascada(ca, provincia, codigo_mun, poligono, parcela)
        else:
            st.error("Selecciona CA y provincia válida")

# ------------------- RESULTADO + PDF -------------------
if info:
    st.success("PARCELA ENCONTRADA")
    st.markdown(f"""
    **Comunidad Autónoma:** {info.get('ca', 'N/A')}  
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
        ("CA", info.get('ca', 'N/A')),
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
else:
    if st.session_state.get("button_pressed"):
        st.error("No se encontró parcela. Verifica los datos.")
