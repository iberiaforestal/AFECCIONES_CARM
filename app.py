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

# Diccionario con los nombres de municipios y sus nombres base de archivo
shp_urls = {
    "ABANILLA": "ABANILLA",
    "ABARAN": "ABARAN",
    "AGUILAS": "AGUILAS",
    "ALBUDEITE": "ALBUDEITE",
    "ALCANTARILLA": "ALCANTARILLA",
    "ALEDO": "ALEDO",
    "ALGUAZAS": "ALGUAZAS",
    "ALHAMA_DE_MURCIA": "ALHAMA_DE_MURCIA",
    "ARCHENA": "ARCHENA",
    "BENIEL": "BENIEL",
    "BLANCA": "BLANCA",
    "BULLAS": "BULLAS",
    "CALASPARRA": "CALASPARRA",
    "CAMPOS_DEL_RIO": "CAMPOS_DEL_RIO",
    "CARAVACA_DE_LA_CRUZ": "CARAVACA_DE_LA_CRUZ",
    "CARTAGENA": "CARTAGENA",
    "CEHEGIN": "CEHEGIN",
    "CEUTI": "CEUTI",
    "CIEZA": "CIEZA",
    "FORTUNA": "FORTUNA",
    "FUENTE_ALAMO_DE_MURCIA": "FUENTE_ALAMO_DE_MURCIA",
    "JUMILLA": "JUMILLA",
    "LAS_TORRES_DE_COTILLAS": "LAS_TORRES_DE_COTILLAS",
    "LA_UNION": "LA_UNION",
    "LIBRILLA": "LIBRILLA",
    "LORCA": "LORCA",
    "LORQUI": "LORQUI",
    "LOS_ALCAZARES": "LOS_ALCAZARES",
    "MAZARRON": "MAZARRON",
    "MOLINA_DE_SEGURA": "MOLINA_DE_SEGURA",
    "MORATALLA": "MORATALLA",
    "MULA": "MULA",
    "MURCIA": "MURCIA",
    "OJOS": "OJOS",
    "PLIEGO": "PLIEGO",
    "PUERTO_LUMBRERAS": "PUERTO_LUMBRERAS",
    "RICOTE": "RICOTE",
    "SANTOMERA": "SANTOMERA",
    "SAN_JAVIER": "SAN_JAVIER",
    "SAN_PEDRO_DEL_PINATAR": "SAN_PEDRO_DEL_PINATAR",
    "TORRE_PACHECO": "TORRE_PACHECO",
    "TOTANA": "TOTANA",
    "ULEA": "ULEA",
    "VILLANUEVA_DEL_RIO_SEGURA": "VILLANUEVA_DEL_RIO_SEGURA",
    "YECLA": "YECLA",
}

# Función para cargar shapefiles desde GitHub
@st.cache_data
def cargar_shapefile_desde_github(base_name):
    base_url = "https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/CATASTRO/"
    exts = [".shp", ".shx", ".dbf", ".prj", ".cpg"]
   
    with tempfile.TemporaryDirectory() as tmpdir:
        local_paths = {}
        for ext in exts:
            filename = base_name + ext
            url = base_url + filename
            try:
                response = requests.get(url, timeout=100)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                st.error(f"Error al descargar {url}: {str(e)}")
                return None
           
            local_path = os.path.join(tmpdir, filename)
            with open(local_path, "wb") as f:
                f.write(response.content)
            local_paths[ext] = local_path
       
        shp_path = local_paths[".shp"]
        try:
            gdf = gpd.read_file(shp_path)
            return gdf
        except Exception as e:
            st.error(f"Error al leer shapefile {shp_path}: {str(e)}")
            return None

# Función para encontrar municipio, polígono y parcela a partir de coordenadas
def encontrar_municipio_poligono_parcela(x, y):
    try:
        punto = Point(x, y)
        for municipio, archivo_base in shp_urls.items():
            gdf = cargar_shapefile_desde_github(archivo_base)
            if gdf is None:
                continue
            seleccion = gdf[gdf.contains(punto)]
            if not seleccion.empty:
                parcela_gdf = seleccion.iloc[[0]]
                masa = parcela_gdf["MASA"].iloc[0]
                parcela = parcela_gdf["PARCELA"].iloc[0]
                return municipio, masa, parcela, parcela_gdf
        return "N/A", "N/A", "N/A", None
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

# === NUEVA FUNCIÓN WFS PARA ENP, ZEPA, LIC, VP, TM ===
@st.cache_data
def consultar_wfs(geom, typename, nombre_afeccion="Afección", campo_nombre="nombre"):
    try:
        # Transformar a WGS84
        if geom.crs != "EPSG:4326":
            geom_wgs84 = geom.to_crs("EPSG:4326")
        else:
            geom_wgs84 = geom

        bounds = geom_wgs84.bounds
        bbox = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"

        wfs = WebFeatureService(url="https://mapas-gis-inter.carm.es/geoserver/ows", version="2.0.0")
        response = wfs.getfeature(
            typename=typename,
            bbox=bbox,
            outputFormat="application/json"
        )
        gdf = gpd.read_file(BytesIO(response.read()))

        if not gdf.empty:
            seleccion = gdf[gdf.intersects(geom_wgs84)]
            if not seleccion.empty:
                nombres = ', '.join(seleccion[campo_nombre].dropna().unique())
                return f"Dentro de {nombre_afeccion}: {nombres}"
        return f"No se encuentra en ninguna {nombre_afeccion}"
    except Exception as e:
        st.error(f"Error WFS {nombre_afeccion}: {e}")
        return f"Error al consultar {nombre_afeccion}"

# === NUEVA FUNCIÓN WFS PARA MUP ===
@st.cache_data
def consultar_mup_wfs(geom):
    try:
        if geom.crs != "EPSG:4326":
            geom = geom.to_crs("EPSG:4326")
        bounds = geom.bounds
        bbox = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"

        wfs = WebFeatureService(url="https://mapas-gis-inter.carm.es/geoserver/ows", version="2.0.0")
        response = wfs.getfeature(
            typename="PFO_ZOR_DMVP_CARM:MONTES",
            bbox=bbox,
            outputFormat="application/json"
        )
        gdf = gpd.read_file(BytesIO(response.read()))

        if not gdf.empty:
            seleccion = gdf[gdf.intersects(geom)]
            if not seleccion.empty:
                info = []
                for _, row in seleccion.iterrows():
                    info.append(
                        f"ID: {row.get('ID_MONTE', 'N/A')}\n"
                        f"Nombre: {row.get('NOMBREMONT', 'N/A')}\n"
                        f"Municipio: {row.get('MUNICIPIO', 'N/A')}\n"
                        f"Propiedad: {row.get('PROPIEDAD', 'N/A')}"
                    )
                return "Dentro de MUP:\n" + "\n\n".join(info)
        return "No se encuentra en ningún MUP"
    except Exception as e:
        st.error(f"Error WFS MUP: {e}")
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

# Función para generar la imagen estática del mapa
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

# Clase personalizada para el PDF
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

# === FUNCIÓN generar_pdf CORREGIDA CON WFS ===
def generar_pdf(datos, x, y, filename, query_geom):
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

    # === RECONSULTAR VP Y MUP CON WFS PARA TABLAS ===
    vp_detectado = []
    mup_detectado = []

    try:
        wfs = WebFeatureService("https://mapas-gis-inter.carm.es/geoserver/ows", version="2.0.0")
        response = wfs.getfeature(typename="PFO_ZOR_DMVP_CARM:VP_CARM", outputFormat="application/json")
        gdf_vp = gpd.read_file(BytesIO(response.read()))
        seleccion_vp = gdf_vp[gdf_vp.intersects(query_geom.to_crs(gdf_vp.crs))]
        for _, row in seleccion_vp.iterrows():
            vp_detectado.append((
                row.get("VP_COD", "N/A"),
                row.get("VP_NB", "N/A"),
                row.get("VP_MUN", "N/A"),
                row.get("VP_SIT_LEG", "N/A"),
                row.get("VP_ANCH_LG", "N/A")
            ))
    except: pass

    try:
        wfs = WebFeatureService("https://mapas-gis-inter.carm.es/geoserver/ows", version="2.0.0")
        response = wfs.getfeature(typename="PFO_ZOR_DMVP_CARM:MONTES", outputFormat="application/json")
        gdf_mup = gpd.read_file(BytesIO(response.read()))
        seleccion_mup = gdf_mup[gdf_mup.intersects(query_geom.to_crs(gdf_mup.crs))]
        for _, row in seleccion_mup.iterrows():
            mup_detectado.append((
                row.get("ID_MONTE", "N/A"),
                row.get("NOMBREMONT", "N/A"),
                row.get("MUNICIPIO", "N/A"),
                row.get("PROPIEDAD", "N/A")
            ))
    except: pass

    afecciones_keys = ["afección ENP", "afección ZEPA", "afección LIC", "afección TM"]
    vp_key = "afección VP"
    mup_key = "afección MUP"

    otras_afecciones = []
    for key in afecciones_keys:
        valor = datos.get(key, "").strip()
        if valor and not valor.startswith("Error"):
            otras_afecciones.append((key.replace("afección ", "").upper(), valor))
        else:
            otras_afecciones.append((key.replace("afección ", "").upper(), valor if valor else "No se encuentra"))

    if not vp_detectado:
        vp_valor = datos.get(vp_key, "").strip()
        otras_afecciones.append(("VP", vp_valor if vp_valor and not vp_valor.startswith("Error") else "No se encuentra en ninguna VP"))
    if not mup_detectado:
        mup_valor = datos.get(mup_key, "").strip()
        otras_afecciones.append(("MUP", mup_valor if mup_valor and not mup_valor.startswith("Error") else "No se encuentra en ningún MUP"))

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
    elif not any("Dentro de" in v for _, v in otras_afecciones):
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
    procedimientos = "- 1609 Solicitudes, escritos y comunicaciones que no disponen de un procedimiento específico en la Guía de Procedimientos y Servicios.\n- 1802 Emisión de certificación sobre delimitación vías pecuarias con respecto a fincas particulares para inscripción registral.\n- 3482 Emisión de Informe en el ejercicio de los derechos de adquisición preferente (tanteo y retracto) en transmisiones onerosas de fincas forestales.\n- 3483 Autorización de proyectos o actuaciones materiales en dominio público forestal que no conlleven concesión administrativa.\n- 3485 Deslinde y amojonamiento de montes a instancia de parte.\n- 3487 Clasificación, deslinde, desafectación y amojonamiento de vías pecuarias.\n- 3488 Emisión de certificaciones de colindancia de fincas particulares respecto a montes incluidos en el Catálogo de Utilidad Pública.\n- 3489 Autorizaciones en dominio público pecuario sin uso privativo.\n- 3490 Emisión de certificación o informe de colindancia de finca particular respecto de vía pecuaria.\n- 5883 (INM) Emisión de certificación o informe para inmatriculación o inscripción registral de fincas colindantes con monte incluido en el Catálogo de Montes de Utilidad Pública.\n- 7002 Expedición de certificados de no afección a la Red Natura 2000.\n- 7186 Ocupación renovable de carácter temporal de vías pecuarias con concesión demanial.\n- 7202 Modificación de trazados en vías pecuarias.\n- 7222 Concesión para la utilización privativa y aprovechamiento especial del dominio público.\n- 7242 Autorización de permutas en montes públicos.\n"
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, procedimientos, border=0, align="J")
    pdf.ln(2)
    pdf.set_font("Arial", "B", 10)
    texto_final = "\nDe acuerdo con lo establecido en el artículo 22 de la ley 43/2003 de 21 de noviembre de Montes, toda inmatriculación o inscripción de exceso de cabida en el Registro de la Propiedad de un monte o de una finca colindante con monte demanial o ubicado en un término municipal en el que existan montes demaniales requerirá el previo informe favorable de los titulares de dichos montes y, para los montes catalogados, el del órgano forestal de la comunidad autónoma.\n\nEn cuanto a vías pecuarias, salvaguardando lo que pudiera resultar de los futuros deslindes, en las parcelas objeto este informe-borrador, cualquier construcción, plantación, vallado, obras, instalaciones, etc., no deberían realizarse dentro del área delimitada como dominio público pecuario provisional para evitar invadir éste.\n\nEn todo caso, no podrá interrumpirse el tránsito por las Vías Pecuarias, dejando siempre el paso adecuado para el tránsito ganadero y otros usos legalmente establecidos en la Ley 3/1995, de 23 de marzo, de Vías Pecuarias."
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_final, border=0, align="J")
    pdf.ln(2)
    pdf.set_text_color(0, 0, 0)
    pdf.output(filename)
    return filename

# === INTERFAZ STREAMLIT ===
st.image("https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg", use_container_width=True)
st.title("Informe preliminar de Afecciones Forestales")

modo = st.radio("Seleccione el modo de búsqueda", ["Por coordenadas", "Por parcela"])

x = 0.0
y = 0.0
municipio_sel = ""
masa_sel = ""
parcela_sel = ""
parcela = None

if modo == "Por parcela":
    municipio_sel = st.selectbox("Municipio", sorted(shp_urls.keys()))
    archivo_base = shp_urls[municipio_sel]
    gdf = cargar_shapefile_desde_github(archivo_base)
    if gdf is not None:
        masa_sel = st.selectbox("Polígono", sorted(gdf["MASA"].unique()))
        parcela_sel = st.selectbox("Parcela", sorted(gdf[gdf["MASA"] == masa_sel]["PARCELA"].unique()))
        parcela = gdf[(gdf["MASA"] == masa_sel) & (gdf["PARCELA"] == parcela_sel)]
        if parcela.geometry.geom_type.isin(['Polygon', 'MultiPolygon']).all():
            centroide = parcela.geometry.centroid.iloc[0]
            x = centroide.x
            y = centroide.y
            st.success("Parcela cargada correctamente.")
            st.write(f"Municipio: {municipio_sel}")
            st.write(f"Polígono: {masa_sel}")
            st.write(f"Parcela: {parcela_sel}")
        else:
            st.error("La geometría seleccionada no es un polígono válido.")
    else:
        st.error(f"No se pudo cargar el shapefile para el municipio: {municipio_sel}")

with st.form("formulario"):
    if modo == "Por coordenadas":
        x = st.number_input("Coordenada X (ETRS89)", format="%.2f")
        y = st.number_input("Coordenada Y (ETRS89)", format="%.2f")
        if x != 0.0 and y != 0.0:
            municipio_sel, masa_sel, parcela_sel, parcela = encontrar_municipio_poligono_parcela(x, y)
            if municipio_sel != "N/A":
                st.success(f"Parcela encontrada: {municipio_sel}, Polígono: {masa_sel}, Parcela: {parcela_sel}")
            else:
                st.warning("No se encontró una parcela para las coordenadas proporcionadas.")
    else:
        st.info(f"Coordenadas obtenidas del centroide: X = {x}, Y = {y}")

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
                query_geom = parcela.to_crs("EPSG:25830").geometry.iloc[0]
            else:
                query_geom = Point(x, y)

            # === CONSULTAS WFS ===
            afeccion_enp = consultar_wfs(query_geom, "SIG_LUP_SITES_CARM:ENP", "ENP", "nombre")
            afeccion_zepa = consultar_wfs(query_geom, "SIG_LUP_SITES_CARM:ZEPA", "ZEPA", "SITE_NAME")
            afeccion_lic = consultar_wfs(query_geom, "SIG_LUP_SITES_CARM:LIC-ZEC", "LIC", "SITE_NAME")
            afeccion_vp = consultar_wfs(query_geom, "PFO_ZOR_DMVP_CARM:VP_CARM", "VP", "VP_NB")
            afeccion_tm = consultar_wfs(query_geom, "PFO_ZOR_DMVP_CARM:MONTES", "TM", "NOMBREMONT")
            afeccion_mup = consultar_mup_wfs(query_geom)

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
                    generar_pdf(datos, x, y, pdf_filename, query_geom)
                    st.session_state['pdf_file'] = pdf_filename
                except Exception as e:
                    st.error(f"Error al generar el PDF: {str(e)}")

if st.session_state['mapa_html'] and st.session_state['pdf_file']:
    try:
        with open(st.session_state['pdf_file'], "rb") as f:
            st.download_button("Descargar informe PDF", f, file_name="informe_afecciones.pdf")
    except Exception as e:
        st.error(f"Error al descargar el PDF: {str(e)}")
    try:
        with open(st.session_state['mapa_html'], "r") as f:
            st.download_button("Descargar mapa HTML", f, file_name="mapa_busqueda.html")
    except Exception as e:
        st.error(f"Error al descargar el mapa HTML: {str(e)}")
