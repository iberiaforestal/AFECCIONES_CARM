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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import shutil

# Sesión segura con reintentos
session = requests.Session()
retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504, 429])
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

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
    base_url ="https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/CATASTRO/"
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

# Función para consultar si la geometría intersecta con algún polígono del GeoJSON
# === FUNCIÓN DESCARGA CON CACHÉ ===
@st.cache_data(show_spinner=False, ttl=604800)  # 7 días
def _descargar_geojson(url):
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return BytesIO(response.content)
    except Exception as e:
        if not hasattr(st, "_wfs_warnings"):
            st._wfs_warnings = set()
        warning_key = url.split('/')[-1]
        if warning_key not in st._wfs_warnings:
            st.warning(f"Servicio no disponible: {warning_key}")
            st._wfs_warnings.add(warning_key)
        return None

# === FUNCIÓN PRINCIPAL (SIN CACHÉ EN GEOMETRÍA) ===
def consultar_wfs_seguro(geom, url, nombre_afeccion, campo_nombre=None, campos_mup=None):
    """
    Consulta WFS con:
    - Descarga cacheada (rápida después de la 1ª vez)
    - Geometría NO cacheada (evita UnhashableParamError)
    """
    data = _descargar_geojson(url)
    if data is None:
        return f"Indeterminado: {nombre_afeccion} (servicio no disponible)"

    try:
        gdf = gpd.read_file(data)
        seleccion = gdf[gdf.intersects(geom)]
        
        if seleccion.empty:
            return f"No afecta en ninguna {nombre_afeccion}"

        # --- MODO MUP: campos personalizados ---
        if campos_mup:
            info = []
            for _, row in seleccion.iterrows():
                valores = [str(row.get(c.split(':')[0], "Desconocido")) for c in campos_mup]
                etiquetas = [c.split(':')[1] if ':' in c else c.split(':')[0] for c in campos_mup]
                info.append("\n".join(f"{etiquetas[i]}: {valores[i]}" for i in range(len(campos_mup))))
            return f"Dentro de {nombre_afeccion}:\n" + "\n\n".join(info)

        # --- MODO NORMAL: solo nombres ---
        else:
            nombres = ', '.join(seleccion[campo_nombre].dropna().unique())
            return f"Dentro de {nombre_afeccion}: {nombres}"

    except Exception as e:
        return f"Indeterminado: {nombre_afeccion} (error de datos)"

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

# Función para generar la imagen estática del mapa usando py-staticmaps
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
        self.set_draw_color(0, 0, 255)  # Línea azul
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

    # === RECUPERAR query_geom ===
    query_geom = st.session_state.get('query_geom')
    if query_geom is None:
        query_geom = Point(x, y)

    # === OBTENER URLs DESDE SESSION_STATE ===
    urls = st.session_state.get('wfs_urls', {})
    vp_url = urls.get('vp')
    zepa_url = urls.get('zepa')
    lic_url = urls.get('lic')
    enp_url = urls.get('enp')

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

    afecciones_keys = ["afección TM"]
    vp_key = "afección VP"
    mup_key = "afección MUP"
    zepa_key = "afección ZEPA"
    lic_key = "afección LIC"
    enp_key = "afección ENP"
    
# === PROCESAR TODAS LAS CAPAS (VP, ZEPA, LIC, ENP) ===
    def procesar_capa(url, key, valor_inicial, campos, detectado_list):
        valor = datos.get(key, "").strip()
        if valor and not valor.startswith("No afecta") and not valor.startswith("Error"):
            try:
                data = _descargar_geojson(url)
                if data is None:
                    return "Error al consultar"
                gdf = gpd.read_file(data)
                seleccion = gdf[gdf.intersects(query_geom)]
                if not seleccion.empty:
                    for _, props in seleccion.iterrows():
                        fila = tuple(props.get(campo, "N/A") for campo in campos)
                        detectado_list.append(fila)
                    return ""
                return valor_inicial
            except Exception as e:
                st.error(f"Error al procesar {key}: {e}")
                return "Error al consultar"
        return valor_inicial if not detectado_list else ""

    # === VP ===
    vp_detectado = []
    vp_valor = procesar_capa(
        vp_url, "afección VP", "No afecta a ninguna VP",
        ["vp_cod", "vp_nb", "vp_mun", "vp_sit_leg", "vp_anch_lg"],
        vp_detectado
    )

    # === ZEPA ===
    zepa_detectado = []
    zepa_valor = procesar_capa(
        zepa_url, "afección ZEPA", "No afecta a ninguna ZEPA",
        ["site_code", "site_name"],
        zepa_detectado
    )

    # === LIC ===
    lic_detectado = []
    lic_valor = procesar_capa(
        lic_url, "afección LIC", "No afecta a ningún LIC",
        ["site_code", "site_name"],
        lic_detectado
    )

    # === ENP ===
    enp_detectado = []
    enp_valor = procesar_capa(
        enp_url, "afección ENP", "No afecta a ningún ENP",
        ["nombre", "figura"],
        enp_detectado
    )

    # === MUP (ya funciona bien, lo dejamos igual) ===
    mup_valor = datos.get("afección MUP", "").strip()
    mup_detectado = []
    if mup_valor and not mup_valor.startswith("No afecta") and not mup_valor.startswith("Error"):
        entries = mup_valor.replace("Dentro de MUP:\n", "").split("\n\n")
        for entry in entries:
            lines = entry.split("\n")
            if lines:
                mup_detectado.append((
                    lines[0].replace("ID: ", "").strip() if len(lines) > 0 else "N/A",
                    lines[1].replace("Nombre: ", "").strip() if len(lines) > 1 else "N/A",
                    lines[2].replace("Municipio: ", "").strip() if len(lines) > 2 else "N/A",
                    lines[3].replace("Propiedad: ", "").strip() if len(lines) > 3 else "N/A"
                ))
        mup_valor = ""

    # Procesar otras afecciones como texto
    otras_afecciones = []
    for key in afecciones_keys:
        valor = datos.get(key, "").strip()
        if valor and not valor.startswith("Error"):
            otras_afecciones.append((key.capitalize(), valor))
        else:
            otras_afecciones.append((key.capitalize(), valor if valor else "No afecta"))

    # Solo incluir MUP, VP, ZEPA, LIC, ENP en "otras afecciones" si NO tienen detecciones
    if not enp_detectado:
        otras_afecciones.append(("Afección ENP", enp_valor if enp_valor else "No se encuentra en ningún ENP"))
    if not lic_detectado:
        otras_afecciones.append(("Afección LIC", lic_valor if lic_valor else "No afecta a ningún LIC"))
    if not zepa_detectado:
        otras_afecciones.append(("Afección ZEPA", zepa_valor if zepa_valor else "No afecta a ninguna ZEPA"))
    if not vp_detectado:
        otras_afecciones.append(("Afección VP", vp_valor if vp_valor else "No afecta a ninguna VP"))
    if not mup_detectado:
        otras_afecciones.append(("Afección MUP", mup_valor if mup_valor else "No afecta a ningún MUP"))

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
        col_widths = [30, 50, 40, 40, 30]  # Anchos: Código, Nombre, Municipio, Situación Legal, Ancho Legal
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

            line_height = 5  # altura base de una línea

            # Obtener altura necesaria para columnas multilínea
            nombre_lines = pdf.multi_cell(col_widths[1], line_height, str(nombre), split_only=True)
            if not nombre_lines:
                nombre_lines = [""]  # evitar None
            nombre_height = len(nombre_lines) * line_height

            # Situación legal
            sit_leg_lines = pdf.multi_cell(col_widths[3], line_height, str(situacion_legal), split_only=True)
            if not sit_leg_lines:
                sit_leg_lines = [""]  # evitar None
            sit_leg_height = len(sit_leg_lines) * line_height

            # Altura real de la fila
            row_h = max(row_height, nombre_height, sit_leg_height)    

            # Guardar posición actual
            x = pdf.get_x()
            y = pdf.get_y()

            # --- 1) DIBUJAR LA FILA (EL MARCO COMPLETO) ---
            pdf.rect(x, y, col_widths[0], row_h)
            pdf.rect(x + col_widths[0], y, col_widths[1], row_h)
            pdf.rect(x + col_widths[0] + col_widths[1], y, col_widths[2], row_h)
            pdf.rect(x + col_widths[0] + col_widths[1] + col_widths[2], y, col_widths[3], row_h)
            pdf.rect(x + col_widths[0] + col_widths[1] + col_widths[2] + col_widths[3], y, col_widths[4], row_h)

            # --- 2) ESCRIBIR EL TEXTO DENTRO DE LAS CELDAS ---
            # Código
            pdf.set_xy(x, y)
            pdf.multi_cell(col_widths[0], line_height, str(codigo_vp), align="L")

            # Nombre (multilínea)
            pdf.set_xy(x + col_widths[0], y)
            pdf.multi_cell(col_widths[1], line_height, str(nombre), align="L")

            # Municipio
            pdf.set_xy(x + col_widths[0] + col_widths[1], y)
            pdf.multi_cell(col_widths[2], line_height, str(municipio), align="L")

            # Situación legal (multilínea)
            pdf.set_xy(x + col_widths[0] + col_widths[1] + col_widths[2], y)
            pdf.multi_cell(col_widths[3], line_height, str(situacion_legal), align="L")

            # Ancho legal
            pdf.set_xy(x + col_widths[0] + col_widths[1] + col_widths[2] + col_widths[3], y)
            pdf.multi_cell(col_widths[4], line_height, str(ancho_legal), align="L")

            # Mover a la siguiente fila
            pdf.set_xy(x, y + row_h)

        pdf.ln(5)  # Espacio adicional después de la tabla

    # Procesar MUP para tabla si hay detecciones
    if mup_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Afecciones de Montes (MUP):", ln=True)
        pdf.ln(2)

        # Configurar la tabla para MUP
        line_height = 5
        col_widths = [30, 80, 40, 40]
        row_height = 8
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        
        # Cabecera
        pdf.cell(col_widths[0], 8, "ID", border=1, fill=True)
        pdf.cell(col_widths[1], 8, "Nombre", border=1, fill=True)
        pdf.cell(col_widths[2], 8, "Municipio", border=1, fill=True)
        pdf.cell(col_widths[3], 8, "Propiedad", border=1, fill=True)
        pdf.ln()

        # Filas
        pdf.set_font("Arial", "", 10)
        for id_monte, nombre, municipio, propiedad in mup_detectado:
            # Calcular líneas necesarias por columna
            id_lines = pdf.multi_cell(col_widths[0], line_height, str(id_monte), split_only=True) or [""]
            nombre_lines = pdf.multi_cell(col_widths[1], line_height, str(nombre), split_only=True) or [""]
            mun_lines = pdf.multi_cell(col_widths[2], line_height, str(municipio), split_only=True) or [""]
            prop_lines = pdf.multi_cell(col_widths[3], line_height, str(propiedad), split_only=True) or [""]

            # Altura de fila = máximo de líneas * line_height
            row_h = max(
                8,
                len(id_lines) * line_height,
                len(nombre_lines) * line_height,
                len(mun_lines) * line_height,
                len(prop_lines) * line_height
            )

            # Guardar posición
            x = pdf.get_x()
            y = pdf.get_y()

            # Dibujar bordes de celdas
            pdf.rect(x, y, col_widths[0], row_h)
            pdf.rect(x + col_widths[0], y, col_widths[1], row_h)
            pdf.rect(x + col_widths[0] + col_widths[1], y, col_widths[2], row_h)
            pdf.rect(x + col_widths[0] + col_widths[1] + col_widths[2], y, col_widths[3], row_h)

            # Escribir contenido centrado verticalmente
            # ID
            id_h = len(id_lines) * line_height
            pdf.set_xy(x, y + (row_h - id_h) / 2)
            pdf.multi_cell(col_widths[0], line_height, str(id_monte), align="L")

            # Nombre
            nombre_h = len(nombre_lines) * line_height
            pdf.set_xy(x + col_widths[0], y + (row_h - nombre_h) / 2)
            pdf.multi_cell(col_widths[1], line_height, str(nombre), align="L")

            # Municipio
            mun_h = len(mun_lines) * line_height
            pdf.set_xy(x + col_widths[0] + col_widths[1], y + (row_h - mun_h) / 2)
            pdf.multi_cell(col_widths[2], line_height, str(municipio), align="L")

            # Propiedad
            prop_h = len(prop_lines) * line_height
            pdf.set_xy(x + col_widths[0] + col_widths[1] + col_widths[2], y + (row_h - prop_h) / 2)
            pdf.multi_cell(col_widths[3], line_height, str(propiedad), align="L")

            # Mover a siguiente fila
            pdf.set_y(y + row_h)

        pdf.ln(5)  # Espacio después de la tabla

    # Procesar tabla para ZEPA
    if zepa_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Afección Zonas de Especial Protección para las Aves (ZEPA):", ln=True)
        pdf.ln(2)
        col_w_code = 30
        col_w_name = pdf.w - 2 * pdf.l_margin - col_w_code
        row_height = 8
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        pdf.cell(col_w_code, row_height, "Código", border=1, fill=True)
        pdf.cell(col_w_name, row_height, "Nombre", border=1, fill=True)
        pdf.ln()
        pdf.set_font("Arial", "", 10)
        for site_code, site_name in zepa_detectado:
            code_lines = pdf.multi_cell(col_w_code, 5, str(site_code), split_only=True)
            name_lines = pdf.multi_cell(col_w_name, 5, str(site_name), split_only=True)
            row_h = max(row_height, len(code_lines) * 5, len(name_lines) * 5)
            x = pdf.get_x()
            y = pdf.get_y()
            pdf.rect(x, y, col_w_code, row_h)
            pdf.rect(x + col_w_code, y, col_w_name, row_h)
            code_h = len(code_lines) * 5
            y_code = y + (row_h - code_h) / 2
            pdf.set_xy(x, y_code)
            pdf.multi_cell(col_w_code, 5, str(site_code), align="L")
            name_h = len(name_lines) * 5
            y_name = y + (row_h - name_h) / 2
            pdf.set_xy(x + col_w_code, y_name)
            pdf.multi_cell(col_w_name, 5, str(site_name), align="L")
            pdf.set_y(y + row_h)
        pdf.ln(5)

    # Procesar tabla para LIC
    if lic_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Afección Lugar de Importancia Comunitaria (LIC):", ln=True)
        pdf.ln(2)
        col_w_code = 30
        col_w_name = pdf.w - 2 * pdf.l_margin - col_w_code
        row_height = 8
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        pdf.cell(col_w_code, row_height, "Código", border=1, fill=True)
        pdf.cell(col_w_name, row_height, "Nombre", border=1, fill=True)
        pdf.ln()
        pdf.set_font("Arial", "", 10)
        for site_code, site_name in lic_detectado:
            code_lines = pdf.multi_cell(col_w_code, 5, str(site_code), split_only=True)
            name_lines = pdf.multi_cell(col_w_name, 5, str(site_name), split_only=True)
            row_h = max(row_height, len(code_lines) * 5, len(name_lines) * 5)
            x = pdf.get_x()
            y = pdf.get_y()
            pdf.rect(x, y, col_w_code, row_h)
            pdf.rect(x + col_w_code, y, col_w_name, row_h)
            code_h = len(code_lines) * 5
            y_code = y + (row_h - code_h) / 2
            pdf.set_xy(x, y_code)
            pdf.multi_cell(col_w_code, 5, str(site_code), align="L")
            name_h = len(name_lines) * 5
            y_name = y + (row_h - name_h) / 2
            pdf.set_xy(x + col_w_code, y_name)
            pdf.multi_cell(col_w_name, 5, str(site_name), align="L")
            pdf.set_y(y + row_h)
        pdf.ln(5)
        
    # Procesar tabla para ENP
    enp_detectado = list(set(tuple(row) for row in enp_detectado))  # ← ELIMINA DUPLICADOS
    if enp_detectado:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Espacio Natural Protegido (ENP):", ln=True)
        pdf.ln(2)

        # --- ANCHO TOTAL DISPONIBLE ---
        page_width = pdf.w - 2 * pdf.l_margin
        col_widths = [page_width * 0.6, page_width * 0.4]  # 60% | 40%
        line_height = 8

        # --- CABECERA ---
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(*azul_rgb)
        pdf.cell(col_widths[0], 10, "Nombre", border=1, fill=True)
        pdf.cell(col_widths[1], 10, "Figura", border=1, fill=True, ln=True)

        # --- FILAS ---
        pdf.set_font("Arial", "", 10)
        for nombre, figura in enp_detectado:
            nombre = str(nombre)
            figura = str(figura)

            # Calcular líneas necesarias
            nombre_lines = len(pdf.multi_cell(col_widths[0], line_height, nombre, split_only=True))
            figura_lines = len(pdf.multi_cell(col_widths[1], line_height, figura, split_only=True))
            row_height = max(10, nombre_lines * line_height, figura_lines * line_height)

            # Salto de página si no cabe
            if pdf.get_y() + row_height > pdf.h - pdf.b_margin:
                pdf.add_page()

            x = pdf.get_x()
            y = pdf.get_y()

            # Dibujar bordes
            pdf.rect(x, y, col_widths[0], row_height)
            pdf.rect(x + col_widths[0], y, col_widths[1], row_height)

            # Texto centrado verticalmente
            pdf.set_xy(x, y + (row_height - nombre_lines * line_height) / 2)
            pdf.multi_cell(col_widths[0], line_height, nombre)

            pdf.set_xy(x + col_widths[0], y + (row_height - figura_lines * line_height) / 2)
            pdf.multi_cell(col_widths[1], line_height, figura)

            pdf.set_y(y + row_height)

        pdf.ln(5)
    # Nueva sección para el texto en cuadro
    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(255, 0, 0)
    pdf.set_draw_color(0, 0, 0) # Borde negro  
    pdf.set_line_width(0.5)
    pdf.set_fill_color(200, 200, 200) # Fondo gris
    
    # Parte 1: Texto en rojo y negrita dentro de un cuadro con fondo gris
    pdf.set_text_color(255, 0, 0)  # Color rojo
    texto_rojo = (
        "Este borrador preliminar de afecciones no tiene el valor de una certificación oficial y por tanto carece de validez legal y solo sirve como información general con carácter orientativo."
    )
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_rojo, border=1, align="J", fill=True)  # Con borde, fondo gris y texto justificado
    pdf.ln(2)

    # Parte 2: Texto en negrita (sin rojo) para el resto del documento
    pdf.set_text_color(0, 0, 0)  # Color negro
    pdf.set_font("Arial", "B", 8)  # Fuente en negrita para el texto general
    texto_resto = (
    "En caso de ser detectadas afecciones a Dominio público forestal o pecuario, así como a Espacios Naturales Protegidos o RN2000, debe solicitar informe oficial a la D. G. de Patrimonio Natural y Acción Climática, a través de los procedimientos establecidos en sede electrónica:\n"
    )
    # Añadir el texto inicial en negrita
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_resto, border=0, align="J")
    pdf.ln(2)

    # Procedimientos sin negrita
    pdf.set_font("Arial", "", 8)  # Fuente normal para los procedimientos
    procedimientos_con_enlace = [
        ("1609", "Solicitudes, escritos y comunicaciones que no disponen de un procedimiento específico en la Guía de Procedimientos y Servicios.", "https://sede.carm.es/web/pagina?IDCONTENIDO=1609&IDTIPO=240&RASTRO=c$m40288"),
        ("1802", "Emisión de certificación sobre delimitación vías pecuarias con respecto a fincas particulares para inscripción registral.", "https://sede.carm.es/web/pagina?IDCONTENIDO=1802&IDTIPO=240&RASTRO=c$m40288"),
        ("3482", "Emisión de Informe en el ejercicio de los derechos de adquisición preferente (tanteo y retracto) en transmisiones onerosas de fincas forestales.", None),
        ("3483", "Autorización de proyectos o actuaciones materiales en dominio público forestal que no conlleven concesión administrativa.", "https://sede.carm.es/web/pagina?IDCONTENIDO=3483&IDTIPO=240&RASTRO=c$m40288"),
        ("3485", "Deslinde y amojonamiento de montes a instancia de parte.", "https://sede.carm.es/web/pagina?IDCONTENIDO=3485&IDTIPO=240&RASTRO=c$m40288"),
        ("3487", "Clasificación, deslinde, desafectación y amojonamiento de vías pecuarias.", "https://sede.carm.es/web/pagina?IDCONTENIDO=3487&IDTIPO=240&RASTRO=c$m40293"),
        ("3488", "Emisión de certificaciones de colindancia de fincas particulares respecto a montes incluidos en el Catálogo de Utilidad Pública.", "https://sede.carm.es/web/pagina?IDCONTENIDO=3488&IDTIPO=240&RASTRO=c$m40293"),
        ("3489", "Autorizaciones en dominio público pecuario sin uso privativo.", "https://sede.carm.es/web/pagina?IDCONTENIDO=3489&IDTIPO=240&RASTRO=c$m40288"),
        ("3490", "Emisión de certificación o informe de colindancia de finca particular respecto de vía pecuaria.", "https://sede.carm.es/web/pagina?IDCONTENIDO=3490&IDTIPO=240&RASTRO=c$m40288"),
        ("5883", "(INM) Emisión de certificación o informe para inmatriculación o inscripción registral de fincas colindantes con monte incluido en el Catálogo de Montes de Utilidad Pública.", "https://sede.carm.es/web/pagina?IDCONTENIDO=5883&IDTIPO=240&RASTRO=c$m40288"),
        ("482", "Autorizaciones e informes en Espacios Naturales Protegidos y Red Natura 2000 de la Región de Murcia.", "https://sede.carm.es/web/pagina?IDCONTENIDO=482&IDTIPO=240&RASTRO=c$m40288"),
        ("7186", "Ocupación renovable de carácter temporal de vías pecuarias con concesión demanial.", None),
        ("7202", "Modificación de trazados en vías pecuarias.", "https://sede.carm.es/web/pagina?IDCONTENIDO=7202&IDTIPO=240&RASTRO=c$m40288"),
        ("7222", "Concesión para la utilización privativa y aprovechamiento especial del dominio público.", None),
        ("7242", "Autorización de permutas en montes públicos.", "https://sede.carm.es/web/pagina?IDCONTENIDO=7242&IDTIPO=240&RASTRO=c$m40288"),
    ]
    line_height = 4  # Altura de línea: 4mm
    margin = pdf.l_margin

    # Guardar posición inicial
    start_y = pdf.get_y()

    for i, (codigo, texto, url) in enumerate(procedimientos_con_enlace):
        y = start_y + i * (line_height + 1)  # 4mm línea + 1mm espacio

        # --- CÓDIGO (EN AZUL SI TIENE ENLACE) ---
        pdf.set_y(y)
        if url:
            pdf.set_text_color(0, 0, 255)
            pdf.cell(22, line_height, f"- {codigo}", border=0)
            pdf.set_text_color(0, 0, 0)
        else:
            pdf.cell(22, line_height, f"- {codigo}", border=0)

        # --- TEXTO (EN LA MISMA LÍNEA, SIN SALTO) ---
        pdf.set_xy(margin + 22, y)
        pdf.multi_cell(pdf.w - 2 * margin - 22, line_height, f" {texto}", border=0, align="J")

        # --- HIPERVÍNCULO (SOLO EN CÓDIGO) ---
        if url:
            pdf.link(margin, y, 22, line_height, url)

    # Ajustar cursor final
    pdf.set_y(start_y + len(procedimientos_con_enlace) * (line_height + 1))

    # Volver a negrita para el resto del texto
    pdf.set_font("Arial", "B", 10)  # Restaurar negrita
    texto_final = (
        "\nDe acuerdo con lo establecido en el artículo 22 de la ley 43/2003 de 21 de noviembre de Montes, toda inmatriculación o inscripción de exceso de cabida en el Registro de la Propiedad de un monte o de una finca colindante con monte demanial o ubicado en un término municipal en el que existan montes demaniales requerirá el previo informe favorable de los titulares de dichos montes y, para los montes catalogados, el del órgano forestal de la comunidad autónoma.\n\n"
        "En cuanto a vías pecuarias, salvaguardando lo que pudiera resultar de los futuros deslindes, en las parcelas objeto este informe-borrador, cualquier construcción, plantación, vallado, obras, instalaciones, etc., no deberían realizarse dentro del área delimitada como dominio público pecuario provisional para evitar invadir éste.\n\n"
        "En todo caso, no podrá interrumpirse el tránsito por las Vías Pecuarias, dejando siempre el paso adecuado para el tránsito ganadero y otros usos legalmente establecidos en la Ley 3/1995, de 23 de marzo, de Vías Pecuarias."
    )
    pdf.multi_cell(pdf.w - 2 * pdf.l_margin, 8, texto_final, border=0, align="J")
    pdf.ln(2)
   
    # Cerrar el cuadro con borde
    pdf.set_text_color(0, 0, 0)  # Restaurar color negro para el resto del documento
    pdf.output(filename)
    return filename

# Interfaz de Streamlit
st.image("https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg", use_container_width=True)
st.title("Informe preliminar de Afecciones Forestales")

modo = st.radio("Seleccione el modo de búsqueda. Recuerde que la busqueda por parcela analiza afecciones al total de la superficie de la parcela, por el contrario la busqueda por coodenadas analiza las afecciones del punto", ["Por coordenadas", "Por parcela"])

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
        x = st.number_input("Coordenada X (ETRS89)", format="%.2f", help="Introduce coordenadas en metros, sistema ETRS89 / UTM zona 30")
        y = st.number_input("Coordenada Y (ETRS89)", format="%.2f")
        if x != 0.0 and y != 0.0:
            municipio_sel, masa_sel, parcela_sel, parcela = encontrar_municipio_poligono_parcela(x, y)
            if municipio_sel != "N/A":
                st.success(f"Parcela encontrada: Municipio: {municipio_sel}, Polígono: {masa_sel}, Parcela: {parcela_sel}")
            else:
                st.warning("No se encontró una parcela para las coordenadas proporcionadas.")
    else:
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
# === 1. LIMPIAR ARCHIVOS DE BÚSQUEDAS ANTERIORES ===
    for key in ['mapa_html', 'pdf_file']:
        if key in st.session_state and st.session_state[key]:
            try:
                if os.path.exists(st.session_state[key]):
                    os.remove(st.session_state[key])
            except:
                pass
    st.session_state.pop('mapa_html', None)
    st.session_state.pop('pdf_file', None)

    # === 2. VALIDAR CAMPOS OBLIGATORIOS ===
    if not nombre or not apellidos or not dni or x == 0 or y == 0:
        st.warning("Por favor, completa todos los campos obligatorios y asegúrate de que las coordenadas son válidas.")
    else:
        # === 3. TRANSFORMAR COORDENADAS ===
        lon, lat = transformar_coordenadas(x, y)
        if lon is None or lat is None:
            st.error("No se pudo generar el informe debido a coordenadas inválidas.")
        else:
            # === 4. DEFINIR query_geom (UNA VEZ) ===
            if modo == "Por parcela":
                query_geom = parcela.geometry.iloc[0]
            else:
                query_geom = Point(x, y)

            # === 5. GUARDAR query_geom Y URLs EN SESSION_STATE ===
            st.session_state['query_geom'] = query_geom
            enp_url = "https://mapas-gis-inter.carm.es/geoserver/SIG_LUP_SITES_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_LUP_SITES_CARM:ENP&outputFormat=application/json"
            zepa_url = "https://mapas-gis-inter.carm.es/geoserver/SIG_LUP_SITES_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_LUP_SITES_CARM:ZEPA&outputFormat=application/json"
            lic_url = "https://mapas-gis-inter.carm.es/geoserver/SIG_LUP_SITES_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_LUP_SITES_CARM:LIC-ZEC&outputFormat=application/json"
            vp_url = "https://mapas-gis-inter.carm.es/geoserver/PFO_ZOR_DMVP_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=PFO_ZOR_DMVP_CARM:VP_CARM&outputFormat=application/json"
            tm_url = "https://mapas-gis-inter.carm.es/geoserver/MAP_UAD_DIVISION-ADMINISTRATIVA_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=MAP_UAD_DIVISION-ADMINISTRATIVA_CARM:recintos_municipales_inspire_carm_etrs89&outputFormat=application/json"
            mup_url = "https://mapas-gis-inter.carm.es/geoserver/PFO_ZOR_DMVP_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=PFO_ZOR_DMVP_CARM:MONTES&outputFormat=application/json"
            st.session_state['wfs_urls'] = {
                'enp': enp_url, 'zepa': zepa_url, 'lic': lic_url,
                'vp': vp_url, 'tm': tm_url, 'mup': mup_url
            }

            # === 6. CONSULTAR AFECCIONES ===
            afeccion_enp = consultar_wfs_seguro(query_geom, enp_url, "ENP", campo_nombre="nombre")
            afeccion_zepa = consultar_wfs_seguro(query_geom, zepa_url, "ZEPA", campo_nombre="site_name")
            afeccion_lic = consultar_wfs_seguro(query_geom, lic_url, "LIC", campo_nombre="site_name")
            afeccion_vp = consultar_wfs_seguro(query_geom, vp_url, "VP", campo_nombre="vp_nb")
            afeccion_tm = consultar_wfs_seguro(query_geom, tm_url, "TM", campo_nombre="nameunit")
            afeccion_mup = consultar_wfs_seguro(
                query_geom, mup_url, "MUP",
                campos_mup=["id_monte:ID", "nombremont:Nombre", "municipio:Municipio", "propiedad:Propiedad"]
            )
            afecciones = [afeccion_enp, afeccion_zepa, afeccion_lic, afeccion_vp, afeccion_tm, afeccion_mup]

            # === 7. CREAR DICCIONARIO `datos` ===
            datos = {
                "fecha_solicitud": fecha_solicitud.strftime('%d/%m/%Y'),
                "fecha_informe": datetime.today().strftime('%d/%m/%Y'),
                "nombre": nombre, "apellidos": apellidos, "dni": dni,
                "dirección": direccion, "teléfono": telefono, "email": email,
                "objeto de la solicitud": objeto,
                "afección MUP": afeccion_mup, "afección VP": afeccion_vp,
                "afección ENP": afeccion_enp, "afección ZEPA": afeccion_zepa,
                "afección LIC": afeccion_lic, "afección TM": afeccion_tm,
                "coordenadas_x": x, "coordenadas_y": y,
                "municipio": municipio_sel, "polígono": masa_sel, "parcela": parcela_sel
            }

            # === 8. MOSTRAR RESULTADOS EN PANTALLA ===
            st.write(f"Municipio seleccionado: {municipio_sel}")
            st.write(f"Polígono seleccionado: {masa_sel}")
            st.write(f"Parcela seleccionada: {parcela_sel}")

            # === 9. GENERAR MAPA ===
            mapa_html, afecciones_lista = crear_mapa(lon, lat, afecciones, parcela_gdf=parcela)
            if mapa_html:
                st.session_state['mapa_html'] = mapa_html
                st.session_state['afecciones'] = afecciones_lista
                st.subheader("Resultado de las afecciones")
                for afeccion in afecciones_lista:
                    st.write(f"• {afeccion}")
                with open(mapa_html, 'r') as f:
                    html(f.read(), height=500)

            # === 10. GENERAR PDF (AL FINAL, CUANDO `datos` EXISTE) ===
            pdf_filename = f"informe_{uuid.uuid4().hex[:8]}.pdf"
            try:
                generar_pdf(datos, x, y, pdf_filename)
                st.session_state['pdf_file'] = pdf_filename
            except Exception as e:
                st.error(f"Error al generar el PDF: {str(e)}")

            # === 11. LIMPIAR DATOS TEMPORALES ===
            st.session_state.pop('query_geom', None)
            st.session_state.pop('wfs_urls', None)
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
