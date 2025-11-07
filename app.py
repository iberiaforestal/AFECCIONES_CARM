import streamlit as st
import folium
from streamlit.components.v1 import html
from fpdf import FPDF
from pyproj import Transformer
import requests
from io import BytesIO
import geopandas as gpd
import tempfile
import os
from shapely.geometry import Point
import uuid
from datetime import datetime
from branca.element import Template, MacroElement
from staticmap import StaticMap, CircleMarker
import textwrap

# === CONFIGURACIÓN INICIAL ===
st.set_page_config(page_title="Afecciones Forestales CARM", layout="wide")
st.image("https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg", use_container_width=True)
st.title("Informe preliminar de Afecciones Forestales")

# === MUNICIPIOS (para selectbox) ===
municipios = [
    "ABANILLA", "ABARAN", "AGUILAS", "ALBUDEITE", "ALCANTARILLA", "ALEDO", "ALGUAZAS",
    "ALHAMA_DE_MURCIA", "ARCHENA", "BENIEL", "BLANCA", "BULLAS", "CALASPARRA",
    "CAMPOS_DEL_RIO", "CARAVACA_DE_LA_CRUZ", "CARTAGENA", "CEHEGIN", "CEUTI", "CIEZA",
    "FORTUNA", "FUENTE_ALAMO_DE_MURCIA", "JUMILLA", "LAS_TORRES_DE_COTILLAS",
    "LA_UNION", "LIBRILLA", "LORCA", "LORQUI", "LOS_ALCAZARES", "MAZARRON",
    "MOLINA_DE_SEGURA", "MORATALLA", "MULA", "MURCIA", "OJOS", "PLIEGO",
    "PUERTO_LUMBRERAS", "RICOTE", "SANTOMERA", "SAN_JAVIER", "SAN_PEDRO_DEL_PINATAR",
    "TORRE_PACHECO", "TOTANA", "ULEA", "VILLANUEVA_DEL_RIO_SEGURA", "YECLA"
]

# === FUNCIÓN: WFS CATASTRO POR COORDENADAS ===
@st.cache_data
def catastro_wfs_por_coordenadas(x, y):
    try:
        x, y = float(x), float(y)
        punto = Point(x, y)
        buffer = 100
        bbox = (x - buffer, y - buffer, x + buffer, y + buffer)
        bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},urn:ogc:def:crs:EPSG::25830"

        url = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": "CP.CadastralParcel", "outputFormat": "application/json",
            "bbox": bbox_str
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        gdf = gpd.read_file(BytesIO(response.content))

        if gdf.empty:
            return "N/A", "N/A", "N/A", None

        contiene = gdf[gdf.contains(punto)]
        if contiene.empty:
            return "N/A", "N/A", "N/A", None

        p = contiene.iloc[0]
        ref = p["nationalCadastralReference"]
        parts = ref.split()
        if len(parts) < 3:
            return "N/A", "N/A", "N/A", None
        municipio, masa, parcela = parts[0], parts[1], parts[2]
        return municipio, masa, parcela, gdf[gdf["nationalCadastralReference"] == ref]

    except Exception as e:
        st.error(f"Error Catastro (coords): {e}")
        return "N/A", "N/A", "N/A", None

# === FUNCIÓN: WFS CATASTRO POR PARCELA ===
@st.cache_data
def catastro_wfs_por_parcela(municipio, masa, parcela):
    try:
        ref = f"{municipio} {masa} {parcela}"
        cql = f"nationalCadastralReference = '{ref}'"
        url = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": "CP.CadastralParcel", "outputFormat": "application/json",
            "CQL_FILTER": cql
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        gdf = gpd.read_file(BytesIO(response.content))
        if gdf.empty:
            return "N/A", "N/A", "N/A", None
        return municipio, masa, parcela, gdf
    except Exception as e:
        st.error(f"Error Catastro (parcela): {e}")
        return "N/A", "N/A", "N/A", None

# === FUNCIÓN: OBTENER POLÍGONOS Y PARCELAS DINÁMICOS ===
@st.cache_data(ttl=3600)
def obtener_poligonos_parcelas(municipio, masa=None):
    try:
        url = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": "CP.CadastralParcel", "outputFormat": "application/json",
            "propertyName": "nationalCadastralReference"
        }
        if masa:
            cql = f"nationalCadastralReference LIKE '{municipio} {masa} %'"
        else:
            cql = f"nationalCadastralReference LIKE '{municipio} %'"
        params["CQL_FILTER"] = cql
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        gdf = gpd.read_file(BytesIO(response.content))
        refs = gdf["nationalCadastralReference"].str.split(" ")
        if masa:
            return sorted(refs.str[2].unique().tolist(), key=lambda x: int(x))
        else:
            return sorted(refs.str[1].unique().tolist())
    except:
        return ["01"] if not masa else ["0001"]

# === TRANSFORMAR COORDENADAS ===
def transformar_coordenadas(x, y):
    try:
        x, y = float(x), float(y)
        if not (500000 <= x <= 800000 and 4000000 <= y <= 4800000):
            return None, None
        transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
        return transformer.transform(x, y)
    except:
        return None, None

# === WFS AFECCIONES (CARM) ===
@st.cache_data
def consultar_wfs_afeccion(geom, typename, nombre, campo):
    try:
        if geom.crs != "EPSG:4326":
            geom = geom.to_crs("EPSG:4326")
        bounds = geom.bounds
        bbox = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
        url = "https://mapas-gis-inter.carm.es/geoserver/ows"
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeName": typename, "outputFormat": "application/json", "bbox": bbox
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        gdf = gpd.read_file(BytesIO(response.content))
        if gdf.empty:
            return f"No se encuentra en ninguna {nombre}"
        seleccion = gdf[gdf.intersects(geom)]
        if seleccion.empty:
            return f"No se encuentra en ninguna {nombre}"
        nombres = ', '.join(seleccion[campo].dropna().unique())
        return f"Dentro de {nombre}: {nombres}"
    except Exception as e:
        return f"Error al consultar {nombre}"

@st.cache_data
def consultar_mup_wfs(geom):
    try:
        if geom.crs != "EPSG:4326":
            geom = geom.to_crs("EPSG:4326")
        bounds = geom.bounds
        bbox = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
        url = "https://mapas-gis-inter.carm.es/geoserver/ows"
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeName": "PFO_ZOR_DMVP_CARM:MONTES", "outputFormat": "application/json", "bbox": bbox
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        gdf = gpd.read_file(BytesIO(response.content))
        if gdf.empty or not gdf.intersects(geom).any():
            return "No se encuentra en ningún MUP"
        info = []
        for _, r in gdf[gdf.intersects(geom)].iterrows():
            info.append(f"ID: {r.get('ID_MONTE','N/A')}\nNombre: {r.get('NOMBREMONT','N/A')}\nMunicipio: {r.get('MUNICIPIO','N/A')}\nPropiedad: {r.get('PROPIEDAD','N/A')}")
        return "Dentro de MUP:\n" + "\n\n".join(info)
    except:
        return "Error al consultar MUP"

# === MAPA ===
def crear_mapa(lon, lat, afecciones, parcela_gdf):
    m = folium.Map(location=[lat, lon], zoom_start=16)
    folium.Marker([lat, lon], popup="Punto consultado").add_to(m)
    if parcela_gdf is not None:
        try:
            p4326 = parcela_gdf.to_crs("EPSG:4326")
            folium.GeoJson(p4326.to_json(), style_function=lambda x: {'color': 'blue', 'weight': 2, 'fillOpacity': 0}).add_to(m)
        except: pass

    wms_layers = [
        ("Red Natura 2000", "SIG_LUP_SITES_CARM:RN2000"),
        ("Montes", "PFO_ZOR_DMVP_CARM:MONTES"),
        ("Vías Pecuarias", "PFO_ZOR_DMVP_CARM:VP_CARM")
    ]
    for name, layer in wms_layers:
        folium.raster_layers.WmsTileLayer(
            url="https://mapas-gis-inter.carm.es/geoserver/ows",
            layers=layer, name=name, fmt="image/png", transparent=True, opacity=0.3
        ).add_to(m)
    folium.LayerControl().add_to(m)

    uid = uuid.uuid4().hex[:8]
    html_file = f"mapa_{uid}.html"
    m.save(html_file)
    return html_file

# === PDF ===
class CustomPDF(FPDF):
    def __init__(self, logo_path):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.logo_path = logo_path
    def header(self):
        if self.logo_path and os.path.exists(self.logo_path):
            self.image(self.logo_path, 10, 8, 50)
            self.set_y(30)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf(datos, x, y, filename, query_geom):
    logo_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg"
    logo_path = None
    try:
        r = requests.get(logo_url, timeout=10)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
            f.write(r.content)
            logo_path = f.name
    except: pass

    pdf = CustomPDF(logo_path)
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Informe preliminar de Afecciones Forestales", ln=True, align="C")
    pdf.ln(5)

    # Datos
    campos = [
        ("Fecha solicitud", datos.get("fecha_solicitud", "")),
        ("Nombre", datos.get("nombre", "")),
        ("DNI", datos.get("dni", "")),
        ("Municipio", datos.get("municipio", "")),
        ("Polígono", datos.get("polígono", "")),
        ("Parcela", datos.get("parcela", "")),
        ("Coordenadas ETRS89", f"X: {x}, Y: {y}")
    ]
    pdf.set_font("Arial", "", 12)
    for k, v in campos:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(50, 8, f"{k}:")
        pdf.set_font("Arial", "", 12)
        pdf.multi_cell(0, 8, str(v) if v else "N/A")
        pdf.ln(2)

    # Afecciones
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Afecciones detectadas:", ln=True)
    for k in ["ENP", "ZEPA", "LIC", "TM", "VP", "MUP"]:
        valor = datos.get(f"afección {k}", "")
        if valor and "No se encuentra" not in valor and "Error" not in valor:
            pdf.multi_cell(0, 8, f"{k}: {valor}")
    if not any("Dentro de" in v for v in datos.values()):
        pdf.multi_cell(0, 8, "No se detectan afecciones relevantes.")

    # Aviso legal
    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(255, 0, 0)
    pdf.multi_cell(0, 8, "Este informe es preliminar y no tiene validez legal.", border=1, fill=True)

    pdf.output(filename)
    return filename

# === INTERFAZ ===
modo = st.radio("Modo de búsqueda", ["Por coordenadas", "Por parcela"])

x, y = 0.0, 0.0
municipio_sel = masa_sel = parcela_sel = ""
parcela_gdf = None
query_geom = None

if modo == "Por coordenadas":
    col1, col2 = st.columns(2)
    with col1:
        x = st.number_input("X (ETRS89)", format="%.2f", value=0.0)
    with col2:
        y = st.number_input("Y (ETRS89)", format="%.2f", value=0.0)
    if x > 0 and y > 0:
        municipio_sel, masa_sel, parcela_sel, parcela_gdf = catastro_wfs_por_coordenadas(x, y)
        if municipio_sel != "N/A":
            st.success(f"Parcela: {municipio_sel} - {masa_sel} - {parcela_sel}")
            query_geom = Point(x, y)
        else:
            st.warning("No se encontró parcela.")

else:  # Por parcela
    municipio_sel = st.selectbox("Municipio", municipios)
    with st.spinner("Cargando polígonos..."):
        masas = obtener_poligonos_parcelas(municipio_sel)
    masa_sel = st.selectbox("Polígono", masas)
    with st.spinner("Cargando parcelas..."):
        parcelas = obtener_poligonos_parcelas(municipio_sel, masa_sel)
    parcela_sel = st.selectbox("Parcela", parcelas)

    if st.button("Cargar parcela"):
        municipio_sel, masa_sel, parcela_sel, parcela_gdf = catastro_wfs_por_parcela(municipio_sel, masa_sel, parcela_sel)
        if parcela_gdf is not None:
            centroide = parcela_gdf.to_crs("EPSG:25830").geometry.centroid.iloc[0]
            x, y = centroide.x, centroide.y
            query_geom = parcela_gdf.to_crs("EPSG:25830").geometry.iloc[0]
            st.success(f"Parcela cargada: X={x:.2f}, Y={y:.2f}")

# === FORMULARIO ===
with st.form("formulario"):
    fecha_solicitud = st.date_input("Fecha solicitud")
    nombre = st.text_input("Nombre")
    apellidos = st.text_input("Apellidos")
    dni = st.text_input("DNI")
    direccion = st.text_input("Dirección")
    telefono = st.text_input("Teléfono")
    email = st.text_input("Email")
    objeto = st.text_area("Objeto de la solicitud")
    submitted = st.form_submit_button("Generar informe")

# === GENERAR INFORME ===
if submitted:
    if not all([nombre, apellidos, dni, x, y, query_geom]):
        st.error("Completa todos los campos y localiza la parcela.")
    else:
        lon, lat = transformar_coordenadas(x, y)
        if not lon:
            st.error("Coordenadas inválidas.")
        else:
            # Afecciones
            afeccion_enp = consultar_wfs_afeccion(query_geom, "SIG_LUP_SITES_CARM:ENP", "ENP", "nombre")
            afeccion_zepa = consultar_wfs_afeccion(query_geom, "SIG_LUP_SITES_CARM:ZEPA", "ZEPA", "SITE_NAME")
            afeccion_lic = consultar_wfs_afeccion(query_geom, "SIG_LUP_SITES_CARM:LIC-ZEC", "LIC", "SITE_NAME")
            afeccion_vp = consultar_wfs_afeccion(query_geom, "PFO_ZOR_DMVP_CARM:VP_CARM", "VP", "VP_NB")
            afeccion_tm = consultar_wfs_afeccion(query_geom, "PFO_ZOR_DMVP_CARM:MONTES", "TM", "NOMBREMONT")
            afeccion_mup = consultar_mup_wfs(query_geom)

            datos = {
                "fecha_solicitud": fecha_solicitud.strftime("%d/%m/%Y"),
                "nombre": f"{nombre} {apellidos}", "dni": dni,
                "municipio": municipio_sel, "polígono": masa_sel, "parcela": parcela_sel,
                "afección ENP": afeccion_enp, "afección ZEPA": afeccion_zepa,
                "afección LIC": afeccion_lic, "afección VP": afeccion_vp,
                "afección TM": afeccion_tm, "afección MUP": afeccion_mup
            }

            # Mapa
            mapa_file = crear_mapa(lon, lat, [], parcela_gdf)
            with open(mapa_file, "r") as f:
                html(f.read(), height=500)

            # PDF
            pdf_file = f"informe_{uuid.uuid4().hex[:8]}.pdf"
            generar_pdf(datos, x, y, pdf_file, query_geom)

            # Descargas
            with open(pdf_file, "rb") as f:
                st.download_button("Descargar PDF", f, file_name="informe_afecciones.pdf")
            with open(mapa_file, "r") as f:
                st.download_button("Descargar mapa", f, file_name="mapa.html")
