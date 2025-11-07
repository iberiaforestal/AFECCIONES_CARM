import streamlit as st
import folium
from streamlit.components.v1 import html
from fpdf import FPDF
from pyproj import Transformer
import requests
import geopandas as gpd
import tempfile
import os
from shapely.geometry import Point
import uuid
from datetime import datetime
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

# === FUNCIÓN PARA CARGAR PARCELA POR REFCAT (storedquery_id CORREGIDO) ===
@st.cache_data
def cargar_parcela_por_refcat(refcat):
    try:
        wfs = WebFeatureService(url=WFS_CP_URL, version='2.0.0')
        response = wfs.getfeature(
            storedquery_id='GetParcel',  # CORREGIDO: minúsculas
            refcat=[refcat],
            outputFormat='application/gml+xml; version=3.2'
        )
        gdf = gpd.read_file(BytesIO(response.read()))
        if not gdf.empty:
            return gdf.to_crs("EPSG:25830")
        return None
    except Exception as e:
        st.error(f"Error al cargar parcela: {str(e)}")
        return None

# === FUNCIÓN PARA BUSCAR POR COORDENADAS ===
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

# === TRANSFORMAR COORDENADAS ===
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

# === CONSULTAR GEOJSON ===
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

# === CONSULTAR MUP ===
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

# === CREAR MAPA ===
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

# === IMAGEN ESTÁTICA ===
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

# === PDF PERSONALIZADO ===
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
        self.set_draw_color(0, 0, 255)
        self.set_line_width(0.5)
        page_width = self.w - 2 * self.l_margin
        self.line(self.l_margin, self.get_y(), self.l_margin + page_width, self.get_y())
        self.set_y(-15)
        self.set_font("Arial", "", 10)
        self.set_text_color(0, 0, 0)
        page_number = f"Página {self.page_no()}"
        self.cell(0, 10, page_number, 0, 0, 'R')

# === GENERAR PDF ===
def generar_pdf(datos, x, y, filename):
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
        x_centered = pdf.l_margin + (epw - image_width) / 2
        pdf.image(imagen_mapa_path, x=x_centered, w=image_width)
    else:
        pdf.set_font("Arial", "", 12)
        pdf.cell(0, 7, "No se pudo generar el mapa de localización.", ln=True)

    pdf.add_page()
    seccion_titulo("3. Afecciones detectadas")
    afecciones_keys = ["afección ENP", "afección ZEPA", "afección LIC", "afección TM"]
    vp_key = "afección VP"
    mup_key = "afección MUP"
    
    vp_valor = datos.get(vp_key, "").strip()
    vp_detectado = []
    if vp_valor and not vp_valor.startswith("No se encuentra") and not vp_valor.startswith("Error"):
        try:
            gdf = gpd.read_file(vp_url)
            seleccion = gdf[gdf.intersects(query_geom)]
            if not seleccion.empty:
                for _, props in seleccion.iterrows():
                    codigo_vp = props.get("VP_COD", "N/A")
                    nombre = props.get("VP_NB", "N/A")
                    municipio = props.get("VP_MUN", "N/A")
                    situacion_legal = props.get("VP_SIT_LEG", "N/A")
                    ancho_legal = props.get("VP_ANCH_LG", "N/A")
                    vp_detectado.append((codigo_vp, nombre, municipio, situacion_legal, ancho_legal))
            vp_valor = ""
        except Exception as e:
            st.error(f"Error al procesar VP desde {vp_url}: {e}")
            vp_valor = "Error al consultar VP"
    else:
        vp_valor = "No se encuentra en ninguna VP" if not vp_detectado else ""

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

    otras_afecciones = []
    for key in afecciones_keys:
        valor = datos.get(key, "").strip()
        if valor and not valor.startswith("Error"):
            otras_afecciones.append((key.capitalize(), valor))
        else:
            otras_afecciones.append((key.capitalize(), valor if valor else "No se encuentra"))
    if not vp_detectado:
        otras_afecciones.append(("Afección VP", vp_valor if vp_valor else "No se encuentra"))
    if not mup_detectado:
        otras_afecciones.append(("Afección MUP", mup_valor if mup_valor else "No se encuentra"))

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

    if vp_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Afecciones de Vías Pecuarias (VP):", ln=True)
        pdf.ln(2)
        col_widths = [30, 50, 40, 40, 30]
        row_height = 8
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        pdf.cell(col_widths[0], row_height, "Código", border=1, fill=True)
        pdf.cell(col_widths[1], row_height, "Nombre", border=1, fill=True)
        pdf.cell(col_widths[2], row_height, "Municipio", border=1, fill=True)
        pdf.cell(col_widths[3], row_height, "Situación Legal", border=1, fill=True)
        pdf.cell(col_widths[4], row_height, "Ancho Legal", border=1, fill=True)
        pdf.ln()
        pdf.set_font("Arial", "", 10)
        for codigo_vp, nombre, municipio, situacion_legal, ancho_legal in vp_detectado:
            pdf.cell(col_widths[0], row_height, str(codigo_vp), border=1)
            pdf.cell(col_widths[1], row_height, str(nombre), border=1)
            pdf.cell(col_widths[2], row_height, str(municipio), border=1)
            pdf.cell(col_widths[3], row_height, str(situacion_legal), border=1)
            pdf.cell(col_widths[4], row_height, str(ancho_legal), border=1)
            pdf.ln()
        pdf.ln(10)

    if mup_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Afecciones de Montes (MUP):", ln=True)
        pdf.ln(2)
        col_widths = [30, 80, 40, 40]
        row_height = 8
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        pdf.cell(col_widths[0], row_height, "ID", border=1, fill=True)
        pdf.cell(col_widths[1], row_height, "Nombre", border=1, fill=True)
        pdf.cell(col_widths[2], row_height, "Municipio", border=1, fill=True)
        pdf.cell(col_widths[3], row_height, "Propiedad", border=1, fill=True)
        pdf.ln()
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

    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(255, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.5)
    pdf.set_fill_color(200, 200, 200)
    texto_rojo = "Este borrador preliminar de afecciones no tiene el valor de una certificación oficial y por tanto carece de validez legal y solo sirve como información general con carácter orientativo."
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_rojo, border=1, align="J", fill=True)
    pdf.ln(2)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "B", 8)
    texto_resto = "En caso de ser detectadas afecciones a Dominio público forestal o pecuario, así como a Espacios Naturales Protegidos o RN2000, debe solicitar informe oficial a la D. G. de Patrimonio Natural y Acción Climática, a través de los procedimientos establecidos en sede electrónica:\n"
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_resto, border=0, align="J")
    pdf.ln(2)
    pdf.set_font("Arial", "", 8)
    procedimientos = (
        "- 1609 Solicitudes, escritos y comunicaciones que no disponen de un procedimiento específico en la Guía de Procedimientos y Servicios.\n"
        "- 1802 Emisión de certificación sobre delimitación vías pecuarias con respecto a fincas particulares para inscripción registral.\n"
        "- 3482 Emisión de Informe en el ejercicio de los derechos de adquisición preferente (tanteo y retracto) en transmisiones onerosas de fincas forestales.\n"
        "- 3483 Autorización de proyectos o actuaciones materiales en dominio público forestal que no conlleven concesión administrativa.\n"
        "- 3485 Deslinde y amojonamiento de montes a instancia de parte.\n"
        "- 3487 Clasificación, deslinde, desafectación y amojonamiento de vías pecuarias.\n"
        "- 3488 Emisión de certificaciones de colindancia de fincas particulares respecto
