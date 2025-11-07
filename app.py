import streamlit as st
import folium
from streamlit.components.v1 import html
from fpdf import FPDF
from pyproj import Transformer
import requests
import xml.etree.ElementTree as ET
import geopandas as gpd
import tempfile
import os
from shapely.geometry import Point
import uuid
from datetime import datetime
from docx import Document
from branca.element import Template, MacroElement
from io import BytesIO
from staticmap import StaticMap, CircleMarker
import textwrap
from owslib.wfs import WebFeatureService

# WFS Catastro
WFS_CP_URL = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"

# Códigos INE para municipios de Murcia (7 dígitos: 30 + código municipio + 000)
municipio_codes = {
    "ABANILLA": "30001000",
    "ABARAN": "30002000",
    "AGUILAS": "30003000",
    "ALBUDEITE": "30004000",
    "ALCANTARILLA": "30005000",
    "ALEDO": "30006000",
    "ALGUAZAS": "30007000",
    "ALHAMA_DE_MURCIA": "30008000",
    "ARCHENA": "30009000",
    "BENIEL": "30010000",
    "BLANCA": "30011000",
    "BULLAS": "30012000",
    "CALASPARRA": "30013000",
    "CAMPOS_DEL_RIO": "30014000",
    "CARAVACA_DE_LA_CRUZ": "30015000",
    "CARTAGENA": "30016000",
    "CEHEGIN": "30017000",
    "CEUTI": "30018000",
    "CIEZA": "30019000",
    "FORTUNA": "30020000",
    "FUENTE_ALAMO_DE_MURCIA": "30021000",
    "JUMILLA": "30022000",
    "LAS_TORRES_DE_COTILLAS": "30023000",
    "LA_UNION": "30024000",
    "LIBRILLA": "30025000",
    "LORCA": "30026000",
    "LORQUI": "30027000",
    "LOS_ALCAZARES": "30028000",
    "MAZARRON": "30029000",
    "MOLINA_DE_SEGURA": "30030000",
    "MORATALLA": "30031000",
    "MULA": "30032000",
    "MURCIA": "30033000",
    "OJOS": "30034000",
    "PLIEGO": "30035000",
    "PUERTO_LUMBRERAS": "30036000",
    "RICOTE": "30037000",
    "SANTOMERA": "30038000",
    "SAN_JAVIER": "30039000",
    "SAN_PEDRO_DEL_PINATAR": "30040000",
    "TORRE_PACHECO": "30041000",
    "TOTANA": "30042000",
    "ULEA": "30043000",
    "VILLANUEVA_DEL_RIO_SEGURA": "30044000",
    "YECLA": "30045000",
}

# Función para cargar parcela por REFCAT usando stored query
@st.cache_data
def cargar_parcela_por_refcat(refcat):
    try:
        wfs = WebFeatureService(url=WFS_CP_URL, version='2.0.0')
        response = wfs.getfeature(storedQuery_id='GetParcel', refcat=[refcat], outputFormat='application/gml+xml; version=3.2')
        gdf = gpd.read_file(BytesIO(response.read()))
        if not gdf.empty:
            return gdf.to_crs("EPSG:25830")
        return None
    except Exception as e:
        st.error(f"Error al cargar parcela: {str(e)}")
        return None

# Función para encontrar por coordenadas (bbox + contains)
def encontrar_municipio_poligono_parcela(x, y):
    try:
        transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)
        punto = Point(lon, lat)
        bbox = (lon - 0.001, lat - 0.001, lon + 0.001, lat + 0.001)
        wfs = WebFeatureService(url=WFS_CP_URL, version='2.0.0')
        response = wfs.getfeature(
            typename='CP:CadastralParcel',
            bbox=bbox,
            srsname='EPSG:4326',
            outputFormat='application/gml+xml; version=3.2',
            maxfeatures=10
        )
        gdf = gpd.read_file(BytesIO(response.read()))
        if gdf.empty:
            return "N/A", "N/A", "N/A", None
        gdf_4326 = gdf.to_crs("EPSG:4326")
        seleccion = gdf_4326[gdf_4326.contains(punto)]
        if seleccion.empty:
            return "N/A", "N/A", "N/A", None
        refcat = seleccion['localId'].iloc[0]
        code = refcat[0:7]
        masa = refcat[7:10]
        parcela = refcat[10:14]
        municipio = next((k for k, v in municipio_codes.items() if v == code), "N/A")
        return municipio, masa, parcela, seleccion.to_crs("EPSG:25830")
    except Exception as e:
        st.error(f"Error al buscar parcela: {str(e)}")
        return "N/A", "N/A", "N/A", None

# El resto de funciones (transformar_coordenadas, consultar_geojson, consultar_mup, crear_mapa, generar_imagen_estatica_mapa, CustomPDF, generar_pdf) permanecen IGUALES que tu código original

# Interfaz de Streamlit (similar a SEC: escalonada, provincia fija)
st.image("https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg", use_container_width=True)
st.title("Informe preliminar de Afecciones Forestales")

modo = st.radio("Seleccione el modo de búsqueda. Recuerde que la búsqueda por parcela analiza afecciones al total de la superficie de la parcela, por el contrario la búsqueda por coordenadas analiza las afecciones del punto", ["Por coordenadas", "Por parcela"])

x = 0.0
y = 0.0
municipio_sel = ""
masa_sel = ""
parcela_sel = ""
parcela = None

if modo == "Por parcela":
    # Provincia fija como en SEC (Murcia)
    provincia = st.selectbox("Provincia*", ["Murcia"])
    
    # Municipio dropdown
    municipio_sel = st.selectbox("Municipio*", sorted(municipio_codes.keys()))
    code = municipio_codes[municipio_sel]
    
    # Polígono input alfanumérico (mínimo 3 caracteres, como SEC)
    masa_sel = st.text_input("Polígono*", placeholder="Ej: V1K (alfanumérico, min 3 caracteres)")
    if len(masa_sel) < 3:
        st.warning("Introduzca al menos 3 caracteres para polígono.")
    else:
        # Parcela input numérico
        parcela_sel = st.text_input("Parcela*", placeholder="Ej: 4810 (numérico, 4 dígitos)")
        if len(parcela_sel) != 4 or not parcela_sel.isdigit():
            st.warning("Parcela debe ser 4 dígitos numéricos.")
        else:
            # Construir REFCAT y cargar
            refcat = f"{code}{masa_sel.upper()}{parcela_sel.zfill(4)}"
            with st.spinner("Cargando parcela desde Catastro..."):
                parcela = cargar_parcela_por_refcat(refcat)
            if parcela is not None:
                centroide = parcela.geometry.centroid.iloc[0]
                x = centroide.x
                y = centroide.y
                st.success("Parcela cargada correctamente desde Catastro.")
                st.write(f"REFCAT: {refcat}")
                st.write(f"Coordenadas centroide: X={x:.2f}, Y={y:.2f}")
            else:
                st.error(f"No se encontró la parcela con REFCAT: {refcat}. Verifique el formato.")
else:
    x = st.number_input("Coordenada X (ETRS89)*", format="%.2f", help="Sistema ETRS89 UTM zona 30N")
    y = st.number_input("Coordenada Y (ETRS89)*", format="%.2f")
    if x != 0.0 and y != 0.0:
        municipio_sel, masa_sel, parcela_sel, parcela = encontrar_municipio_poligono_parcela(x, y)
        if municipio_sel != "N/A":
            st.success(f"Parcela encontrada: Municipio: {municipio_sel}, Polígono: {masa_sel}, Parcela: {parcela_sel}")
        else:
            st.warning("No se encontró una parcela para las coordenadas proporcionadas.")

# Formulario y generación de informe (tu código original SIN CAMBIOS)
with st.form("formulario"):
    if modo == "Por parcela":
        st.info(f"Coordenadas obtenidas del centroide de la parcela: X = {x}, Y = {y}")
    fecha_solicitud = st.date_input("Fecha de la solicitud*")
    nombre = st.text_input("Nombre*")
    apellidos = st.text_input("Apellidos*")
    dni = st.text_input("DNI*")
    direccion = st.text_input("Dirección")
    telefono = st.text_input("Teléfono")
    email = st.text_input("Correo electrónico")
    objeto = st.text_area("Objeto de la solicitud", max_chars=255)
    submitted = st.form_submit_button("Generar informe")

if 'mapa_html' not in st.session_state:
    st.session_state['mapa_html'] = None
if 'pdf_file' not in st.session_state:
    st.session_state['pdf_file'] = None
if 'afecciones' not in st.session_state:
    st.session_state['afecciones'] = []

if submitted:
    if not nombre or not apellidos or not dni or x == 0 or y == 0:
        st.warning("Por favor, completa todos los campos obligatorios y asegúrate de que las coordenadas son válidas.")
    else:
        lon, lat = transformar_coordenadas(x, y)
        if lon is None or lat is None:
            st.error("No se pudo generar el informe debido a coordenadas inválidas.")
        else:
            if modo == "Por parcela":
                query_geom = parcela.geometry.iloc[0]
            else:
                query_geom = Point(x, y)
            st.write(f"Municipio seleccionado: {municipio_sel}")
            st.write(f"Polígono seleccionado: {masa_sel}")
            st.write(f"Parcela seleccionada: {parcela_sel}")
            enp_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/GeoJSON/ENP.json"
            zepa_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/GeoJSON/ZEPA.json"
            lic_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/GeoJSON/LIC.json"
            vp_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/GeoJSON/VP.json"
            tm_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/GeoJSON/TM.json"
            mup_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/GeoJSON/MUP.json"
            afeccion_enp = consultar_geojson(query_geom, enp_url, "ENP", campo_nombre="nombre")
            afeccion_zepa = consultar_geojson(query_geom, zepa_url, "ZEPA", campo_nombre="SITE_NAME")
            afeccion_lic = consultar_geojson(query_geom, lic_url, "LIC", campo_nombre="SITE_NAME")
            afeccion_vp = consultar_geojson(query_geom, vp_url, "VP", campo_nombre="VP_NB")
            afeccion_tm = consultar_geojson(query_geom, tm_url, "TM", campo_nombre="NAMEUNIT")
            afeccion_mup = consultar_mup(query_geom, mup_url)
            afecciones = [afeccion_enp, afeccion_zepa, afeccion_lic, afeccion_vp, afeccion_tm, afeccion_mup]
            
            datos = {
                "fecha_solicitud": fecha_solicitud.strftime('%d/%m/%Y'),
                "fecha_informe": datetime.today().strftime('%d/%m/%Y'),
                "nombre": nombre,
                "apellidos": apellidos,
                "dni": dni,
                "dirección": direccion,
                "teléfono": telefono,
                "email": email,
                "objeto de la solicitud": objeto,
                "afección MUP": afeccion_mup,
                "afección VP": afeccion_vp,
                "afección ENP": afeccion_enp,
                "afección ZEPA": afeccion_zepa,
                "afección LIC": afeccion_lic,
                "afección TM": afeccion_tm,
                "coordenadas_x": x,
                "coordenadas_y": y,
                "municipio": municipio_sel,
                "polígono": masa_sel,
                "parcela": parcela_sel
            }
            
            mapa_html, afecciones = crear_mapa(lon, lat, afecciones, parcela_gdf=parcela)
            if mapa_html:
                st.session_state['mapa_html'] = mapa_html
                st.session_state['afecciones'] = afecciones
                st.subheader("Resultado de las afecciones")
                for afeccion in afecciones:
                    st.write(f"• {afeccion}")
                with open(mapa_html, 'r') as f:
                    html(f.read(), height=500)
                pdf_filename = f"informe_{uuid.uuid4().hex[:8]}.pdf"
                try:
                    generar_pdf(datos, x, y, pdf_filename)
                    st.session_state['pdf_file'] = pdf_filename
                except Exception as e:
                    st.error(f"Error al generar el PDF: {str(e)}")

if st.session_state['mapa_html'] and st.session_state['pdf_file']:
    try:
        with open(st.session_state['pdf_file'], "rb") as f:
            st.download_button("📄 Descargar informe PDF", f, file_name="informe_afecciones.pdf")
    except Exception as e:
        st.error(f"Error al descargar el PDF: {str(e)}")
    try:
        with open(st.session_state['mapa_html'], "r") as f:
            st.download_button("🌍 Descargar mapa HTML", f, file_name="mapa_busqueda.html")
    except Exception as e:
        st.error(f"Error al descargar el mapa HTML: {str(e)}")
