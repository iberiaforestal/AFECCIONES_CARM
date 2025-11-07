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

# WFS URLs
WFS_CP_URL = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
WFS_AD_URL = "https://ovc.catastro.meh.es/INSPIRE/wfsAD.aspx"

# Diccionario con nombres de municipios de Murcia y sus códigos INE
municipio_codes = {
    "ABANILLA": "30001",
    "ABARAN": "30002",
    "AGUILAS": "30003",
    "ALBUDEITE": "30004",
    "ALCANTARILLA": "30005",
    "ALEDO": "30006",
    "ALGUAZAS": "30007",
    "ALHAMA_DE_MURCIA": "30008",
    "ARCHENA": "30009",
    "BENIEL": "30010",
    "BLANCA": "30011",
    "BULLAS": "30012",
    "CALASPARRA": "30013",
    "CAMPOS_DEL_RIO": "30014",
    "CARAVACA_DE_LA_CRUZ": "30015",
    "CARTAGENA": "30016",
    "CEHEGIN": "30017",
    "CEUTI": "30018",
    "CIEZA": "30019",
    "FORTUNA": "30020",
    "FUENTE_ALAMO_DE_MURCIA": "30021",
    "JUMILLA": "30022",
    "LIBRILLA": "30023",
    "LORCA": "30024",
    "LORQUI": "30025",
    "LOS_ALCAZARES": "30026",
    "MAZARRON": "30027",
    "MOLINA_DE_SEGURA": "30028",
    "MORATALLA": "30029",
    "MULA": "30030",
    "MURCIA": "30031",
    "OJOS": "30032",
    "PLIEGO": "30033",
    "PUERTO_LUMBRERAS": "30034",
    "RICOTE": "30035",
    "SANTOMERA": "30036",
    "SAN_JAVIER": "30037",
    "SAN_PEDRO_DEL_PINATAR": "30038",
    "TORRE_PACHECO": "30039",
    "TOTANA": "30040",
    "ULEA": "30041",
    "VILLANUEVA_DEL_RIO_SEGURA": "30042",
    "YECLA": "30043",
}

# Función para consultar municipio desde WFS AD (opcional para precisión)
@st.cache_data
def consultar_municipio_ad(geom_or_point, radio=0.0005):
    try:
        wfs = WebFeatureService(url=WFS_AD_URL, version='2.0.0')
        layer = 'AD:Address'
        if isinstance(geom_or_point, Point):
            lon, lat = geom_or_point.x, geom_or_point.y
            bbox = (lon - radio, lat - radio, lon + radio, lat + radio)
        else:
            bounds = geom_or_point.bounds
            bbox = (bounds[0], bounds[1], bounds[2], bounds[3])
        response = wfs.getfeature(
            typename=layer,
            bbox=bbox,
            srsname='EPSG:4326',
            outputFormat='application/gml+xml; version=3.2',
            maxfeatures=5
        )
        gdf = gpd.read_file(BytesIO(response.read()))
        if gdf.empty:
            return "N/A"
        municipio = gdf['designator'].iloc[0] if 'designator' in gdf.columns else "N/A"
        return municipio
    except:
        return "N/A"

# Función para obtener polígonos (MASA) para un municipio
@st.cache_data
def obtener_masas_por_municipio(code):
    try:
        wfs = WebFeatureService(url=WFS_CP_URL, version='2.0.0')
        # El localId tiene 14 caracteres: 5(INE) + 3(MASA) + 5(PARCELA) + 1(LETRA)
        cql = f"localId LIKE '{code.zfill(5)}%'"
        response = wfs.getfeature(
            typename='CP:CadastralParcel',
            cql_filter=cql,
            propertyname='localId',
            maxfeatures=1000,
            outputFormat='application/json'
        )
        gdf = gpd.read_file(BytesIO(response.read()))
        if gdf.empty:
            return []
        # Extraer MASA: caracteres 5-8
        gdf['masa'] = gdf['localId'].str[5:8]
        return sorted(gdf['masa'].unique())
    except Exception as e:
        st.error(f"Error al cargar polígonos: {str(e)}")
        return []

# Función para obtener parcelas
@st.cache_data
def obtener_parcelas_por_masa(code, masa):
    try:
        wfs = WebFeatureService(url=WFS_CP_URL, version='2.0.0')
        prefix = f"{code.zfill(5)}{masa.zfill(3)}"
        cql = f"localId LIKE '{prefix}%'"
        response = wfs.getfeature(
            typename='CP:CadastralParcel',
            cql_filter=cql,
            propertyname='localId',
            maxfeatures=1000,
            outputFormat='application/json'
        )
        gdf = gpd.read_file(BytesIO(response.read()))
        if gdf.empty:
            return []
        # Extraer PARCELA: caracteres 8-13
        gdf['parcela'] = gdf['localId'].str[8:13]
        return sorted(gdf['parcela'].unique())
    except Exception as e:
        st.error(f"Error al cargar parcelas: {str(e)}")
        return []

# Función para obtener geometría
@st.cache_data
def obtener_parcela_gdf(code, masa, parcela):
    try:
        wfs = WebFeatureService(url=WFS_CP_URL, version='2.0.0')
        # Construir base: 5+3+5 = 13 caracteres
        base = f"{code.zfill(5)}{masa.zfill(3)}{parcela.zfill(5)}"
        cql = f"localId LIKE '{base}%'"
        response = wfs.getfeature(
            typename='CP:CadastralParcel',
            cql_filter=cql,
            outputFormat='application/gml+xml; version=3.2',
            maxfeatures=1
        )
        gdf = gpd.read_file(BytesIO(response.read()))
        if not gdf.empty:
            return gdf.to_crs("EPSG:25830")
        return None
    except Exception as e:
        st.error(f"Error al cargar geometría: {str(e)}")
        return None

# Función para encontrar por coordenadas
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
        code = refcat[0:5]
        masa = refcat[5:8]
        parcela = refcat[8:13]
        municipio = next((k for k, v in municipio_codes.items() if v == code), "N/A")
        return municipio, masa, parcela, seleccion.to_crs("EPSG:25830")
    except Exception as e:
        st.error(f"Error al buscar parcela: {str(e)}")
        return "N/A", "N/A", "N/A", None

# Función para transformar coordenadas de ETRS89 a WGS84
def transformar_coordenadas(x, y):
    try:
        x, y = float(x), float(y)
        if not (500000 <= x <= 800000 and 4000000 <= y <= 4800000):
            st.error("Coordenadas fuera del rango esperado para ETRS89 UTM Zona 30")
            return None, None
        transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)
        return lon, lat
    except ValueError:
        st.error("Coordenadas inválidas. Asegúrate de ingresar valores numéricos.")
        return None, None

# Función para consultar si la geometría intersecta con algún polígono del GeoJSON
def consultar_geojson(geom, geojson_url, nombre_afeccion="Afección", campo_nombre="nombre"):
    try:
        gdf = gpd.read_file(geojson_url)
        seleccion = gdf[gdf.intersects(geom)]
        if not seleccion.empty:
            nombres = ', '.join(seleccion[campo_nombre].dropna().unique())
            return f"Dentro de {nombre_afeccion}: {nombres}"
        else:
            return f"No se encuentra en ninguna {nombre_afeccion}"
    except Exception as e:
        st.error(f"Error al leer GeoJSON de {nombre_afeccion}: {e}")
        return f"Error al consultar {nombre_afeccion}"

# Función para consultar si la geometría intersecta con algún MUP del GeoJSON
def consultar_mup(geom, geojson_url):
    try:
        gdf = gpd.read_file(geojson_url)
        seleccion = gdf[gdf.intersects(geom)]
        if not seleccion.empty:
            info = []
            for _, props in seleccion.iterrows():
                id_monte = props.get("ID_MONTE", "Desconocido")
                nombre_monte = props.get("NOMBREMONT", "Desconocido")
                municipio = props.get("MUNICIPIO", "Desconocido")
                propiedad = props.get("PROPIEDAD", "Desconocido")
                info.append(f"ID: {id_monte}\nNombre: {nombre_monte}\nMunicipio: {municipio}\nPropiedad: {propiedad}")
            return "Dentro de MUP:\n" + "\n\n".join(info)
        else:
            return "No se encuentra en ningún MUP"
    except Exception as e:
        st.error(f"Error al consultar MUP: {e}")
        return "Error al consultar MUP"

# Función para crear el mapa con afecciones específicas
def crear_mapa(lon, lat, afecciones=[], parcela_gdf=None):
    if lon is None or lat is None:
        st.error("Coordenadas inválidas para generar el mapa.")
        return None, afecciones
    
    m = folium.Map(location=[lat, lon], zoom_start=16)
    folium.Marker([lat, lon], popup=f"Coordenadas transformadas: {lon}, {lat}").add_to(m)
    if parcela_gdf is not None and not parcela_gdf.empty:
        try:
            parcela_4326 = parcela_gdf.to_crs("EPSG:4326")
            folium.GeoJson(
                parcela_4326.to_json(),
                name="Parcela",
                style_function=lambda x: {'fillColor': 'transparent', 'color': 'blue', 'weight': 2, 'dashArray': '5, 5'}
            ).add_to(m)
        except Exception as e:
            st.error(f"Error al añadir la parcela al mapa: {str(e)}")
    wms_layers = [
        ("Red Natura 2000", "SIG_LUP_SITES_CARM:RN2000"),
        ("Montes", "PFO_ZOR_DMVP_CARM:MONTES"),
        ("Vias Pecuarias", "PFO_ZOR_DMVP_CARM:VP_CARM")
    ]
    for name, layer in wms_layers:
        try:
            folium.raster_layers.WmsTileLayer(
                url="https://mapas-gis-inter.carm.es/geoserver/ows?SERVICE=WMS&?",
                name=name,
                fmt="image/png",
                layers=layer,
                transparent=True,
                opacity=0.25,
                control=True
            ).add_to(m)
        except Exception as e:
            st.error(f"Error al cargar la capa WMS {name}: {str(e)}")
    folium.LayerControl().add_to(m)
    legend_html = """
    {% macro html(this, kwargs) %}
<div style="
    position: fixed;
    bottom: 20px;
    left: 20px;
    background-color: white;
    border: 1px solid grey;
    z-index: 9999;
    font-size: 10px;
    padding: 5px;
    box-shadow: 2px 2px 6px rgba(0,0,0,0.2);
    line-height: 1.1em;
    width: auto;
    transform: scale(0.75);
    transform-origin: top left;
">
    <b>Leyenda</b><br>
    <div>
        <img src="https://mapas-gis-inter.carm.es/geoserver/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=20&height=20&layer=SIG_LUP_SITES_CARM%3ARN2000" alt="Red Natura"><br>
        <img src="https://mapas-gis-inter.carm.es/geoserver/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=20&height=20&layer=PFO_ZOR_DMVP_CARM%3AMONTES" alt="Montes"><br>
        <img src="https://mapas-gis-inter.carm.es/geoserver/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=20&height=20&layer=PFO_ZOR_DMVP_CARM%3AVP_CARM" alt="Vias Pecuarias"><br>
    </div>
</div>
{% endmacro %}
"""
    legend = MacroElement()
    legend._template = Template(legend_html)
    m.get_root().add_child(legend)
    for afeccion in afecciones:
        folium.Marker([lat, lon], popup=afeccion).add_to(m)
    uid = uuid.uuid4().hex[:8]
    mapa_html = f"mapa_{uid}.html"
    m.save(mapa_html)
    return mapa_html, afecciones

# Función para generar la imagen estática del mapa usando staticmap
def generar_imagen_estatica_mapa(x, y, zoom=16, size=(800, 600)):
    lon, lat = transformar_coordenadas(x, y)
    if lon is None or lat is None:
        return None
    
    try:
        m = StaticMap(size[0], size[1], url_template='http://a.tile.openstreetmap.org/{z}/{x}/{y}.png')
        marker = CircleMarker((lon, lat), 'red', 12)
        m.add_marker(marker)
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "mapa.png")
        image = m.render(zoom=zoom)
        image.save(output_path)
        return output_path
    except Exception as e:
        st.error(f"Error al generar la imagen estática del mapa: {str(e)}")
        return None

# Clase personalizada para el PDF con encabezado y pie de página
class CustomPDF(FPDF):
    def __init__(self, logo_path):
        super().__init__()
        self.logo_path = logo_path

    def header(self):
        if self.logo_path and os.path.exists(self.logo_path):
            page_width = self.w - 2 * self.l_margin
            logo_width = page_width * 0.5
            self.image(self.logo_path, x=self.l_margin, y=10, w=logo_width)
            logo_height = logo_width * 0.2
            self.set_y(10 + logo_height + 2)
        else:
            self.set_y(10)

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(0, 0, 255) # Línea azul
        self.set_line_width(0.5)
        page_width = self.w - 2 * self.l_margin
        self.line(self.l_margin, self.get_y(), self.l_margin + page_width, self.get_y())
        self.set_y(-15)
        self.set_font("Arial", "", 10)
        self.set_text_color(0, 0, 0)
        page_number = f"Página {self.page_no()}"
        self.cell(0, 10, page_number, 0, 0, 'R')

# Función para generar el PDF con los datos de la solicitud
def generar_pdf(datos, x, y, filename):
    # Descargar y guardar el logo en un archivo temporal
    logo_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg"
    logo_path = None
    try:
        response = requests.get(logo_url, timeout=10)
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
            tmp_img.write(response.content)
            logo_path = tmp_img.name
    except Exception as e:
        st.error(f"Error al descargar el logo: {str(e)}")

    # Crear instancia de la clase personalizada
    pdf = CustomPDF(logo_path)
    pdf.set_margins(left=10, top=10, right=10)
    pdf.add_page()

    pdf.set_font("Arial", "B", size=16)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, "Informe preliminar de Afecciones Forestales", ln=True, align="C")
    pdf.ln(5)

    azul_rgb = (141, 179, 226)

    campos_orden = [
        ("Fecha solicitud", datos.get("fecha_solicitud", "").strip()),
        ("Fecha informe", datos.get("fecha_informe", "").strip()),
        ("Nombre", datos.get("nombre", "").strip()),
        ("Apellidos", datos.get("apellidos", "").strip()),
        ("DNI", datos.get("dni", "").strip()),
        ("Dirección", datos.get("dirección", "").strip()),
        ("Teléfono", datos.get("teléfono", "").strip()),
        ("Email", datos.get("email", "").strip()),
    ]

    def seccion_titulo(texto):
        pdf.set_fill_color(*azul_rgb)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "B", 13)
        pdf.cell(0, 10, texto, ln=True, fill=True)
        pdf.ln(2)

    def campo_orden(pdf, titulo, valor):
        pdf.set_font("Arial", "B", 12)
        pdf.cell(50, 7, f"{titulo}:", ln=0)
        pdf.set_font("Arial", "", 12)
        
        valor = valor.strip() if valor else "No especificado"
        wrapped_text = textwrap.wrap(valor, width=60)
        if not wrapped_text:
            wrapped_text = ["No especificado"]
        
        for line in wrapped_text:
            pdf.cell(0, 7, line, ln=1)

    seccion_titulo("1. Datos del solicitante")
    for titulo, valor in campos_orden:
        campo_orden(pdf, titulo, valor)

    objeto = datos.get("objeto de la solicitud", "").strip()
    pdf.ln(2)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 7, "Objeto de la solicitud:", ln=True)
    pdf.set_font("Arial", "", 12)
    wrapped_objeto = textwrap.wrap(objeto if objeto else "No especificado", width=60)
    for line in wrapped_objeto:
        pdf.cell(0, 7, line, ln=1)
        
    seccion_titulo("2. Localización")
    for campo in ["municipio", "polígono", "parcela"]:
        valor = datos.get(campo, "").strip()
        campo_orden(pdf, campo.capitalize(), valor if valor else "No disponible")

    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"Coordenadas ETRS89: X = {x}, Y = {y}", ln=True)

    imagen_mapa_path = generar_imagen_estatica_mapa(x, y)
    if imagen_mapa_path and os.path.exists(imagen_mapa_path):
        epw = pdf.w - 2 * pdf.l_margin
        pdf.ln(5)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 7, "Mapa de localización:", ln=True, align="C")
        image_width = epw * 0.5
        x_centered = pdf.l_margin + (epw - image_width) / 2  # Calcular posición x para centrar
        pdf.image(imagen_mapa_path, x=x_centered, w=image_width)
    else:
        pdf.set_font("Arial", "", 12)
        pdf.cell(0, 7, "No se pudo generar el mapa de localización.", ln=True)

    pdf.add_page()
    seccion_titulo("3. Afecciones detectadas")

    afecciones_keys = ["afección ENP", "afección ZEPA", "afección LIC", "afección TM"]
    vp_key = "afección VP"
    mup_key = "afección MUP"
    
    # Procesar afecciones VP
    vp_valor = datos.get(vp_key, "").strip()
    vp_detectado = []
    if vp_valor and not vp_valor.startswith("No se encuentra") and not vp_valor.startswith("Error"):
        try:
            gdf = gpd.read_file(vp_url) # Cargar el GeoJSON de Vías Pecuarias (VP.json)
            seleccion = gdf[gdf.intersects(query_geom)] # Filtrar geometrías que intersectan
            if not seleccion.empty:
                for _, props in seleccion.iterrows():
                    codigo_vp = props.get("VP_COD", "N/A") # Código de la vía
                    nombre = props.get("VP_NB", "N/A") # Nombre de la vía
                    municipio = props.get("VP_MUN", "N/A") # Término municipal
                    situacion_legal = props.get("VP_SIT_LEG", "N/A") # Situación legal
                    ancho_legal = props.get("VP_ANCH_LG", "N/A") # Ancho legal
                    vp_detectado.append((codigo_vp, nombre, municipio, situacion_legal, ancho_legal))
            vp_valor = "" # Evitamos poner "No se encuentra" si hay tabla
        except Exception as e:
            st.error(f"Error al procesar VP desde {vp_url}: {e}")
            vp_valor = "Error al consultar VP"
    else:
        vp_valor = "No se encuentra en ninguna VP" if not vp_detectado else ""

    # Procesar afecciones MUP
    mup_valor = datos.get(mup_key, "").strip()
    mup_detectado = []
    if mup_valor and not mup_valor.startswith("No se encuentra") and not mup_valor.startswith("Error"):
        entries = mup_valor.replace("Dentro de MUP:\n", "").split("\n\n")
        for entry in entries:
            lines = entry.split("\n")
            if lines:
                id_monte = lines[0].replace("ID: ", "").strip() if len(lines) > 0 else "N/A"
                nombre = lines[1].replace("Nombre: ", "").strip() if len(lines) > 1 else "N/A"
                municipio = lines[2].replace("Municipio: ", "").strip() if len(lines) > 2 else "N/A"
                propiedad = lines[3].replace("Propiedad: ", "").strip() if len(lines) > 3 else "N/A"
                mup_detectado.append((id_monte, nombre, municipio, propiedad))
        mup_valor = ""
    # Procesar otras afecciones como texto
    otras_afecciones = []
    for key in afecciones_keys:
        valor = datos.get(key, "").strip()
        if valor and not valor.startswith("Error"):
            otras_afecciones.append((key.capitalize(), valor))
        else:
            otras_afecciones.append((key.capitalize(), valor if valor else "No se encuentra"))
    # Solo incluir MUP o VP en "otras afecciones" si NO tienen detecciones
    if not vp_detectado:
        otras_afecciones.append(("Afección VP", vp_valor if vp_valor else "No se encuentra"))
    if not mup_detectado:
        otras_afecciones.append(("Afección MUP", mup_valor if mup_valor else "No se encuentra"))
    # Mostrar otras afecciones con títulos en negrita
    if otras_afecciones:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Otras afecciones:", ln=True)
        pdf.ln(2)
        for titulo, valor in otras_afecciones:
            if valor:
                pdf.set_font("Arial", "B", 12)
                pdf.cell(60, 8, f"{titulo}:", ln=0)
                pdf.set_font("Arial", "", 12)
                wrapped_valor = textwrap.wrap(valor, width=60)
                for line in wrapped_valor:
                    pdf.cell(0, 8, line, ln=1)
        pdf.ln(2)
    # Procesar VP para tabla si hay detecciones
    if vp_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Afecciones de Vías Pecuarias (VP):", ln=True)
        pdf.ln(2)
        # Configurar la tabla para VP
        col_widths = [30, 50, 40, 40, 30] # Anchos: Código, Nombre, Municipio, Situación Legal, Ancho Legal
        row_height = 8
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        pdf.cell(col_widths[0], row_height, "Código", border=1, fill=True)
        pdf.cell(col_widths[1], row_height, "Nombre", border=1, fill=True)
        pdf.cell(col_widths[2], row_height, "Municipio", border=1, fill=True)
        pdf.cell(col_widths[3], row_height, "Situación Legal", border=1, fill=True)
        pdf.cell(col_widths[4], row_height, "Ancho Legal", border=1, fill=True)
        pdf.ln()
        # Agregar filas a la tabla
        pdf.set_font("Arial", "", 10)
        for codigo_vp, nombre, municipio, situacion_legal, ancho_legal in vp_detectado:
            pdf.cell(col_widths[0], row_height, str(codigo_vp), border=1)
            pdf.cell(col_widths[1], row_height, str(nombre), border=1)
            pdf.cell(col_widths[2], row_height, str(municipio), border=1)
            pdf.cell(col_widths[3], row_height, str(situacion_legal), border=1)
            pdf.cell(col_widths[4], row_height, str(ancho_legal), border=1)
            pdf.ln()
        pdf.ln(10)
    # Procesar MUP para tabla si hay detecciones
    if mup_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Afecciones de Montes (MUP):", ln=True)
        pdf.ln(2)
        # Configurar la tabla para MUP
        col_widths = [30, 80, 40, 40]
        row_height = 8
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        pdf.cell(col_widths[0], row_height, "ID", border=1, fill=True)
        pdf.cell(col_widths[1], row_height, "Nombre", border=1, fill=True)
        pdf.cell(col_widths[2], row_height, "Municipio", border=1, fill=True)
        pdf.cell(col_widths[3], row_height, "Propiedad", border=1, fill=True)
        pdf.ln()
        # Agregar filas a la tabla
        pdf.set_font("Arial", "", 10)
        for id_monte, nombre, municipio, propiedad in mup_detectado:
            pdf.cell(col_widths[0], row_height, id_monte, border=1)
            pdf.cell(col_widths[1], row_height, nombre, border=1)
            pdf.cell(col_widths[2], row_height, municipio, border=1)
            pdf.cell(col_widths[3], row_height, propiedad, border=1)
            pdf.ln()
        pdf.ln(10)
    elif not any(valor != "No se encuentra" and valor != "No se encuentra en ninguna VP" and valor != "No se encuentra en ningún MUP" for _, valor in otras_afecciones):
        pdf.set_font("Arial", "", 12)
        pdf.cell(0, 8, "No se encuentra en ENP, ZEPA, LIC, VP, MUP", ln=True)
        pdf.ln(10)
    # Nueva sección para el texto en cuadro
    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(255, 0, 0)
    pdf.set_draw_color(0, 0, 0) # Borde negro
    pdf.set_line_width(0.5)
    pdf.set_fill_color(200, 200, 200) # Fondo gris
    
    # Parte 1: Texto en rojo y negrita dentro de un cuadro con fondo gris
    pdf.set_text_color(255, 0, 0) # Color rojo
    texto_rojo = (
        "Este borrador preliminar de afecciones no tiene el valor de una certificación oficial y por tanto carece de validez legal y solo sirve como información general con carácter orientativo."
    )
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_rojo, border=1, align="J", fill=True) # Con borde, fondo gris y texto justificado
    pdf.ln(2)
    # Parte 2: Texto en negrita (sin rojo) para el resto del documento
    pdf.set_text_color(0, 0, 0) # Color negro
    pdf.set_font("Arial", "B", 8) # Fuente en negrita para el texto general
    texto_resto = (
    "En caso de ser detectadas afecciones a Dominio público forestal o pecuario, así como a Espacios Naturales Protegidos o RN2000, debe solicitar informe oficial a la D. G. de Patrimonio Natural y Acción Climática, a través de los procedimientos establecidos en sede electrónica:\n"
    )
    # Añadir el texto inicial en negrita
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_resto, border=0, align="J")
    pdf.ln(2)
    # Procedimientos sin negrita
    pdf.set_font("Arial", "", 8) # Fuente normal para los procedimientos
    procedimientos = (
        "- 1609 Solicitudes, escritos y comunicaciones que no disponen de un procedimiento específico en la Guía de Procedimientos y Servicios.\n"
        "- 1802 Emisión de certificación sobre delimitación vías pecuarias con respecto a fincas particulares para inscripción registral.\n"
        "- 3482 Emisión de Informe en el ejercicio de los derechos de adquisición preferente (tanteo y retracto) en transmisiones onerosas de fincas forestales.\n"
        "- 3483 Autorización de proyectos o actuaciones materiales en dominio público forestal que no conlleven concesión administrativa.\n"
        "- 3485 Deslinde y amojonamiento de montes a instancia de parte.\n"
        "- 3487 Clasificación, deslinde, desafectación y amojonamiento de vías pecuarias.\n"
        "- 3488 Emisión de certificaciones de colindancia de fincas particulares respecto a montes incluidos en el Catálogo de Utilidad Pública.\n"
        "- 3489 Autorizaciones en dominio público pecuario sin uso privativo.\n"
        "- 3490 Emisión de certificación o informe de colindancia de finca particular respecto de vía pecuaria.\n"
        "- 5883 (INM) Emisión de certificación o informe para inmatriculación o inscripción registral de fincas colindantes con monte incluido en el Catálogo de Montes de Utilidad Pública.\n"
        "- 7002 Expedición de certificados de no afección a la Red Natura 2000.\n"
        "- 7186 Ocupación renovable de carácter temporal de vias pecuarias con concesión demanial.\n"
        "- 7202 Modificación de trazados en vias pecuarias.\n"
        "- 7222 Concesión para la utilización privativa y aprovechamiento especial del dominio público.\n"
        "- 7242 Autorización de permutas en montes públicos.\n"
    )
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, procedimientos, border=0, align="J")
    pdf.ln(2)
    # Volver a negrita para el resto del texto
    pdf.set_font("Arial", "B", 10) # Restaurar negrita
    texto_final = (
        "\nDe acuerdo con lo establecido en el artículo 22 de la ley 43/2003 de 21 de noviembre de Montes, toda inmatriculación o inscripción de exceso de cabida en el Registro de la Propiedad de un monte o de una finca colindante con monte demanial o ubicado en un término municipal en el que existan montes demaniales requerirá el previo informe favorable de los titulares de dichos montes y, para los montes catalogados, el del órgano forestal de la comunidad autónoma.\n\n"
        "En cuanto a vias pecuarias, salvaguardando lo que pudiera resultar de los futuros deslindes, en las parcelas objeto este informe-borrador, cualquier construcción, plantación, vallado, obras, instalaciones, etc., no deberían realizarse dentro del área delimitada como dominio público pecuario provisional para evitar invadir éste.\n\n"
        "En todo caso, no podrá interrumpirse el tránsito por las Vías Pecuarias, dejando siempre el paso adecuado para el tránsito ganadero y otros usos legalmente establecidos en la Ley 3/1995, de 23 de marzo, de Vías Pecuarias."
    )
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_final, border=0, align="J")
    pdf.ln(2)
  
    # Cerrar el cuadro con borde
    pdf.set_text_color(0, 0, 0) # Restaurar color negro para el resto del documento
    pdf.output(filename)
    return filename

# Interfaz de Streamlit
st.image("https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg", use_container_width=True)
st.title("Informe preliminar de Afecciones Forestales")

modo = st.radio("Seleccione el modo de búsqueda. Recuerde que la busqueda por parcela analiza afecciones al total de la superficie de la parcela, por el contrario la busqueda por coordenadas analiza las afecciones del punto", ["Por coordenadas", "Por parcela"])

x = 0.0
y = 0.0
municipio_sel = ""
masa_sel = ""
parcela_sel = ""
parcela = None

if modo == "Por parcela":
    municipio_sel = st.selectbox("Municipio", sorted(municipio_codes.keys()))
    code = municipio_codes[municipio_sel]

    masas = obtener_masas_por_municipio(code)
    masa_sel = st.selectbox("Polígono", masas)

    if masa_sel:
        parcels = obtener_parcelas_por_masa(code, masa_sel)
        parcela_sel = st.selectbox("Parcela", parcels)

        if parcela_sel:
            parcela = obtener_parcela_gdf(code, masa_sel, parcela_sel)
            if parcela is not None:
                centroide = parcela.geometry.centroid.iloc[0]
                x = centroide.x
                y = centroide.y
                st.success("Parcela cargada correctamente.")
                st.write(f"Municipio: {municipio_sel}")
                st.write(f"Polígono: {masa_sel}")
                st.write(f"Parcela: {parcela_sel}")
            else:
                st.error("No se pudo cargar la geometría de la parcela.")
else:
    x = st.number_input("Coordenada X (ETRS89)", format="%.2f", help="Introduce coordenadas en metros, sistema ETRS89 / UTM zona 30")
    y = st.number_input("Coordenada Y (ETRS89", format="%.2f")
    if x != 0.0 and y != 0.0:
        municipio_sel, masa_sel, parcela_sel, parcela = encontrar_municipio_poligono_parcela(x, y)
        if municipio_sel != "N/A":
            st.success(f"Parcela encontrada: Municipio: {municipio_sel}, Polígono: {masa_sel}, Parcela: {parcela_sel}")
        else:
            st.warning("No se encontró una parcela para las coordenadas proporcionadas.")

with st.form("formulario"):
    if modo == "Por parcela":
        st.info(f"Coordenadas obtenidas del centroide de la parcela: X = {x}, Y = {y}")
        
    fecha_solicitud = st.date_input("Fecha de la solicitud")
    nombre = st.text_input("Nombre")
    apellidos = st.text_input("Apellidos")
    dni = st.text_input("DNI")
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
