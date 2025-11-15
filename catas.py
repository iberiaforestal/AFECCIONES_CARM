# catas.py
import streamlit as st
import folium
from streamlit.components.v1 import html
from fpdf import FPDF
from pyproj import Transformer
import requests
import geopandas as gpd
import tempfile
import os
from shapely.geometry import Point, shape
import uuid
from datetime import datetime
from branca.element import Template, MacroElement
from io import BytesIO
from staticmap import StaticMap, CircleMarker
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image

# === CONFIGURACIÓN DE SESIÓN HTTP CON REINTENTOS ===
session = requests.Session()
retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504, 429])
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

# === WFS CATASTRO: BÚSQUEDA POR REFERENCIA ===
def buscar_parcela_wfs(municipio, poligono, parcela):
    municipio = municipio.strip().upper()
    poligono = poligono.zfill(3)
    parcela = parcela.zfill(5)
    
    url = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfLibres/OVCFiltros.svc/ObtenerGeometria"
    payload = {
        "Provincia": "MURCIA",
        "Municipio": municipio,
        "Poligono": poligono,
        "Parcela": parcela,
        "SRS": "EPSG:25830"
    }
    try:
        r = session.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("Geometria"):
                geom = shape(data["Geometria"])
                centroide = geom.centroid
                return {
                    'x': centroide.x,
                    'y': centroide.y,
                    'geom': geom,
                    'municipio': municipio,
                    'poligono': poligono,
                    'parcela': parcela
                }
    except Exception as e:
        st.error(f"Error WFS (ref): {e}")
    return None

# === WFS CATASTRO: BÚSQUEDA POR COORDENADAS ===
def buscar_parcela_por_coordenadas(x, y):
    url = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfLibres/OVCFiltros.svc/ObtenerParcelaPorCoordenadas"
    payload = {
        "Provincia": "MURCIA",
        "SRS": "EPSG:25830",
        "Coordenada_X": str(x),
        "Coordenada_Y": str(y)
    }
    try:
        r = session.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("ListaParcelas"):
                p = data["ListaParcelas"][0]
                ref = p["RefCatastral"]
                municipio = p["NombreMunicipio"]
                poligono = ref[7:10]
                parcela = ref[10:15]
                return buscar_parcela_wfs(municipio, poligono, parcela)
    except Exception as e:
        st.error(f"Error WFS (coord): {e}")
    return None

# === TRANSFORMAR COORDENADAS ETRS89 → WGS84 ===
def transformar_coordenadas(x, y):
    try:
        x, y = float(x), float(y)
        if not (500000 <= x <= 800000 and 4000000 <= y <= 4800000):
            st.error("Coordenadas fuera del rango ETRS89 UTM Zona 30")
            return None, None
        transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)
        return lon, lat
    except Exception as e:
        st.error("Coordenadas inválidas.")
        return None, None

# === DESCARGA CACHÉ DE WFS ===
@st.cache_data(show_spinner=False, ttl=604800)  # 7 días
def _descargar_geojson(url):
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return BytesIO(response.content)
    except Exception as e:
        key = url.split('/')[-1]
        if key not in getattr(st, "_wfs_warnings", set()):
            st.warning(f"Servicio no disponible: {key}")
            if not hasattr(st, "_wfs_warnings"):
                st._wfs_warnings = set()
            st._wfs_warnings.add(key)
        return None

# === CONSULTA WFS SEGURA ===
def consultar_wfs_seguro(geom, url, nombre_afeccion, campo_nombre=None, campos_mup=None):
    data = _descargar_geojson(url)
    if data is None:
        return f"Indeterminado: {nombre_afeccion} (servicio no disponible)"

    try:
        gdf = gpd.read_file(data)
        seleccion = gdf[gdf.intersects(geom)]
        if seleccion.empty:
            return f"No afecta a {nombre_afeccion}"

        if campos_mup:
            info = []
            for _, row in seleccion.iterrows():
                valores = [str(row.get(c.split(':')[0], "Desconocido")) for c in campos_mup]
                etiquetas = [c.split(':')[1] if ':' in c else c.split(':')[0] for c in campos_mup]
                info.append("\n".join(f"{etiquetas[i]}: {valores[i]}" for i in range(len(campos_mup))))
            return f"Dentro de {nombre_afeccion}:\n" + "\n\n".join(info)
        else:
            nombres = ', '.join(seleccion[campo_nombre].dropna().unique())
            return f"Dentro de {nombre_afeccion}: {nombres}"
    except Exception as e:
        return f"Indeterminado: {nombre_afeccion} (error de datos)"

# === CREAR MAPA INTERACTIVO ===
def crear_mapa(lon, lat, afecciones=[], parcela_gdf=None):
    if lon is None or lat is None:
        return None, afecciones

    m = folium.Map(location=[lat, lon], zoom_start=16)
    folium.Marker([lat, lon], popup="Punto de consulta").add_to(m)

    if parcela_gdf is not None and not parcela_gdf.empty:
        try:
            parcela_4326 = parcela_gdf.to_crs("EPSG:4326")
            folium.GeoJson(
                parcela_4326.to_json(),
                name="Parcela",
                style_function=lambda x: {'fillColor': 'transparent', 'color': 'blue', 'weight': 2, 'dashArray': '5, 5'}
            ).add_to(m)
        except Exception as e:
            st.error(f"Error al añadir parcela al mapa: {e}")

    wms_layers = [
        ("Red Natura 2000", "SIG_LUP_SITES_CARM:RN2000"),
        ("Montes", "PFO_ZOR_DMVP_CARM:MONTES"),
        ("Vías Pecuarias", "PFO_ZOR_DMVP_CARM:VP_CARM")
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
            st.error(f"Error WMS {name}: {e}")

    folium.LayerControl().add_to(m)

    legend_html = """
    {% macro html(this, kwargs) %}
    <div style="position: fixed; bottom: 20px; left: 20px; background: white; border: 1px solid grey; z-index: 9999; font-size: 10px; padding: 5px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2); line-height: 1.1em; width: auto; transform: scale(0.75); transform-origin: top left;">
        <b>Leyenda</b><br>
        <img src="https://mapas-gis-inter.carm.es/geoserver/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=20&height=20&layer=SIG_LUP_SITES_CARM%3ARN2000"><br>
        <img src="https://mapas-gis-inter.carm.es/geoserver/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=20&height=20&layer=PFO_ZOR_DMVP_CARM%3AMONTES"><br>
        <img src="https://mapas-gis-inter.carm.es/geoserver/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=20&height=20&layer=PFO_ZOR_DMVP_CARM%3AVP_CARM">
    </div>
    {% endmacro %}
    """
    legend = MacroElement()
    legend._template = Template(legend_html)
    m.get_root().add_child(legend)

    uid = uuid.uuid4().hex[:8]
    mapa_html = f"mapa_{uid}.html"
    m.save(mapa_html)
    return mapa_html, afecciones

# === CLASE PDF PERSONALIZADA ===
class CustomPDF(FPDF):
    def __init__(self, logo_path):
        super().__init__()
        self.logo_path = logo_path

    def header(self):
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                available_width = self.w - self.l_margin - self.r_margin
                max_logo_height = 25
                img = Image.open(self.logo_path)
                ratio = img.width / img.height
                target_width = available_width
                target_height = target_width / ratio
                if target_height > max_logo_height:
                    target_height = max_logo_height
                    target_width = target_height * ratio
                x = self.l_margin + (available_width - target_width) / 2
                y = 5
                self.image(self.logo_path, x=x, y=y, w=target_width, h=target_height)
                self.set_y(y + target_height + 3)
            except Exception as e:
                st.warning(f"Error logo: {e}")
                self.set_y(30)
        else:
            self.set_y(30)

    def footer(self):
        if self.page_no() > 0:
            self.set_y(-15)
            self.set_draw_color(0, 0, 255)
            self.set_line_width(0.5)
            page_width = self.w - 2 * self.l_margin
            self.line(self.l_margin, self.get_y(), self.l_margin + page_width, self.get_y())
            self.set_y(-15)
            self.set_font("Arial", "", 9)
            self.set_text_color(0, 0, 0)
            self.cell(0, 10, f"Página {self.page_no()}", align="R")

# === GENERAR PDF ===
def generar_pdf(datos, x, y, filename):
    logo_path = "logos.jpg"
    if not os.path.exists(logo_path):
        st.error("FALTA 'logos.jpg' en la raíz del proyecto.")
        st.markdown("[Descargar logos.jpg](https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg)")
        logo_path = None
    else:
        st.success("Logo cargado")

    query_geom = st.session_state.get('query_geom', Point(x, y))
    urls = st.session_state.get('wfs_urls', {})

    pdf = CustomPDF(logo_path)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    line_h = 5

    # Título
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "INFORME BÁSICO DE AFECCIONES AL MEDIO", ln=1, align="C")
    pdf.ln(5)

    # Datos solicitante
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, line_h, "DATOS DEL SOLICITANTE", ln=1)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, line_h, f"Nombre: {datos['nombre']} {datos['apellidos']}\nDNI: {datos['dni']}\nDirección: {datos['dirección']}\nTeléfono: {datos['teléfono']}\nEmail: {datos['email']}\nObjeto: {datos['objeto de la solicitud']}")

    # Coordenadas
    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, line_h, "LOCALIZACIÓN", ln=1)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, line_h, f"Coordenadas ETRS89 (UTM 30N): X = {x:.2f}, Y = {y:.2f}\nReferencia Catastral: {datos.get('municipio', 'N/A')} Pol. {datos.get('polígono', 'N/A')} Parc. {datos.get('parcela', 'N/A')}")

    # Afecciones
    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, line_h, "AFECCIONES DETECTADAS", ln=1)
    pdf.set_font("Arial", "", 9)
    for key, value in datos.items():
        if key.startswith("afección") and "No afecta" not in value and "Indeterminado" not in value:
            pdf.multi_cell(0, line_h, f"{key.upper()}: {value}")

    # Pie
    pdf.ln(10)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, line_h, "Normativa actualizada a 01/01/2026. Revisión trimestral.\ninfo@iberiaforestal.es")

    pdf.output(filename)
    return filename

# === INTERFAZ STREAMLIT ===
st.image("https://raw.githubusercontent.com/iberiaforestal/AFECCIONES_CARM/main/logos.jpg", width=250)
st.title("Informe Básico de Afecciones al Medio")

st.markdown("## Búsqueda de Parcela")

modo = st.radio("Modo de búsqueda", ["Por referencia catastral (rústica)", "Por coordenadas (X, Y)"], horizontal=True)

resultado = None

if modo == "Por referencia catastral (rústica)":
    col1, col2, col3, col4 = st.columns([3, 3, 1, 1])
    with col1:
        st.markdown("**Provincia**"); st.text_input("prov", "MURCIA", disabled=True, label_visibility="collapsed")
    with col2:
        st.markdown("**Municipio**"); mun = st.text_input("mun", placeholder="LORCA, CARTAGENA...", label_visibility="collapsed")
    with col3:
        st.markdown("**Polígono**"); pol = st.text_input("pol", max_chars=3, placeholder="000", label_visibility="collapsed")
    with col4:
        st.markdown("**Parcela**"); parc = st.text_input("parc", max_chars=5, placeholder="00000", label_visibility="collapsed")
    
    if st.button("Buscar parcela", type="primary"):
        if mun and len(pol) == 3 and pol.isdigit():
            with st.spinner("Consultando Catastro..."):
                resultado = buscar_parcela_wfs(mun, pol, parc)
        else:
            st.warning("Complete municipio y polígono (3 dígitos).")
else:
    col1, col2 = st.columns(2)
    with col1:
        x_input = st.number_input("Coordenada X (ETRS89)", format="%.2f", value=0.0)
    with col2:
        y_input = st.number_input("Coordenada Y (ETRS89)", format="%.2f", value=0.0)
    
    if st.button("Buscar por coordenadas", type="primary"):
        if x_input > 0 and y_input > 0:
            with st.spinner("Buscando parcela..."):
                resultado = buscar_parcela_por_coordenadas(x_input, y_input)
        else:
            st.warning("Introduce coordenadas válidas.")

# === GUARDAR RESULTADO ===
if resultado:
    st.success("¡Parcela encontrada!")
    st.info(f"**Referencia:** {resultado['municipio']} - Pol. {resultado['poligono']} - Parc. {resultado['parcela']}\n**Centroide:** X = {resultado['x']:.2f} | Y = {resultado['y']:.2f}")
    st.session_state.update({
        'x': resultado['x'], 'y': resultado['y'],
        'geom': resultado['geom'],
        'ref_cat': f"{resultado['municipio']} {resultado['poligono']} {resultado['parcela']}"
    })
else:
    for k in ['x', 'y', 'geom', 'ref_cat']:
        st.session_state.pop(k, None)

# === FORMULARIO ===
with st.form("formulario", clear_on_submit=False):
    if 'x' in st.session_state:
        x, y = st.session_state['x'], st.session_state['y']
        ref = st.session_state.get('ref_cat', 'N/A')
        st.info(f"**Parcela localizada:** {ref}\n**Centroide:** X = {x:.2f}, Y = {y:.2f}")
    else:
        st.info("Use el buscador superior para localizar la parcela.")

    col1, col2 = st.columns(2)
    with col1:
        nombre = st.text_input("Nombre *")
        dni = st.text_input("DNI *")
        telefono = st.text_input("Teléfono")
        direccion = st.text_input("Dirección")
    with col2:
        apellidos = st.text_input("Apellidos *")
        email = st.text_input("Correo electrónico")
        objeto = st.text_area("Objeto de la solicitud *", max_chars=255)

    submitted = st.form_submit_button("Generar informe", type="primary", use_container_width=True)

# === INICIALIZAR SESSION STATE ===
for key in ['mapa_html', 'pdf_file', 'afecciones']:
    if key not in st.session_state:
        st.session_state[key] = None

# === GENERAR INFORME ===
if submitted:
    if not all([nombre, apellidos, dni, objeto]):
        st.error("Complete todos los campos obligatorios (*).")
    elif 'x' not in st.session_state:
        st.error("Localice una parcela primero.")
    else:
        x, y = st.session_state['x'], st.session_state['y']
        geom = st.session_state['geom']

        # Limpiar archivos previos
        for key in ['mapa_html', 'pdf_file']:
            if st.session_state[key] and os.path.exists(st.session_state[key]):
                try: os.remove(st.session_state[key])
                except: pass
            st.session_state[key] = None

        # Transformar
        lon, lat = transformar_coordenadas(x, y)
        if not lon:
            st.error("Coordenadas inválidas.")
        else:
            # Guardar geometría
            st.session_state['query_geom'] = geom

            # URLs WFS
            urls = {
                'flora': "https://mapas-gis-inter.carm.es/geoserver/SIG_ZOR_PLANIGEST_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_ZOR_PLANIGEST_CARM:planes_recuperacion_flora2014&outputFormat=application/json",
                'garbancillo': "https://mapas-gis-inter.carm.es/geoserver/SIG_ZOR_PLANIGEST_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_ZOR_PLANIGEST_CARM:plan_recuperacion_garbancillo&outputFormat=application/json",
                'malvasia': "https://mapas-gis-inter.carm.es/geoserver/SIG_ZOR_PLANIGEST_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_ZOR_PLANIGEST_CARM:plan_recuperacion_malvasia&outputFormat=application/json",
                'fartet': "https://mapas-gis-inter.carm.es/geoserver/SIG_ZOR_PLANIGEST_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_ZOR_PLANIGEST_CARM:plan_recuperacion_fartet&outputFormat=application/json",
                'nutria': "https://mapas-gis-inter.carm.es/geoserver/SIG_ZOR_PLANIGEST_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_ZOR_PLANIGEST_CARM:plan_recuperacion_nutria&outputFormat=application/json",
                'perdicera': "https://mapas-gis-inter.carm.es/geoserver/SIG_ZOR_PLANIGEST_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_ZOR_PLANIGEST_CARM:plan_recuperacion_perdicera&outputFormat=application/json",
                'tortuga': "https://mapas-gis-inter.carm.es/geoserver/SIG_DES_BIOTA_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_DES_BIOTA_CARM:tortuga_distribucion_2001&outputFormat=application/json",
                'uso_suelo': "https://mapas-gis-inter.carm.es/geoserver/SIT_USU_PLA_URB_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIT_USU_PLA_URB_CARM:plu_ze_37_mun_uso_suelo&outputFormat=application/json",
                'esteparias': "https://mapas-gis-inter.carm.es/geoserver/SIG_DES_BIOTA_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_DES_BIOTA_CARM:esteparias_ceea_2019_10x10&outputFormat=application/json",
                'enp': "https://mapas-gis-inter.carm.es/geoserver/SIG_LUP_SITES_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_LUP_SITES_CARM:ENP&outputFormat=application/json",
                'zepa': "https://mapas-gis-inter.carm.es/geoserver/SIG_LUP_SITES_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_LUP_SITES_CARM:ZEPA&outputFormat=application/json",
                'lic': "https://mapas-gis-inter.carm.es/geoserver/SIG_LUP_SITES_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=SIG_LUP_SITES_CARM:LIC-ZEC&outputFormat=application/json",
                'vp': "https://mapas-gis-inter.carm.es/geoserver/PFO_ZOR_DMVP_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=PFO_ZOR_DMVP_CARM:VP_CARM&outputFormat=application/json",
                'tm': "https://mapas-gis-inter.carm.es/geoserver/MAP_UAD_DIVISION-ADMINISTRATIVA_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=MAP_UAD_DIVISION-ADMINISTRATIVA_CARM:recintos_municipales_inspire_carm_etrs89&outputFormat=application/json",
                'mup': "https://mapas-gis-inter.carm.es/geoserver/PFO_ZOR_DMVP_CARM/wfs?service=WFS&version=1.1.0&request=GetFeature&typeName=PFO_ZOR_DMVP_CARM:MONTES&outputFormat=application/json"
            }
            st.session_state['wfs_urls'] = urls

            # Consultar afecciones
            afeccion_flora = consultar_wfs_seguro(geom, urls['flora'], "FLORA", campo_nombre="tipo")
            afeccion_garbancillo = consultar_wfs_seguro(geom, urls['garbancillo'], "GARBANCILLO", campo_nombre="tipo")
            afeccion_malvasia = consultar_wfs_seguro(geom, urls['malvasia'], "MALVASIA", campo_nombre="clasificac")
            afeccion_fartet = consultar_wfs_seguro(geom, urls['fartet'], "FARTET", campo_nombre="clasificac")
            afeccion_nutria = consultar_wfs_seguro(geom, urls['nutria'], "NUTRIA", campo_nombre="tipo_de_ar")
            afeccion_perdicera = consultar_wfs_seguro(geom, urls['perdicera'], "ÁGUILA PERDICERA", campo_nombre="zona")
            afeccion_tortuga = consultar_wfs_seguro(geom, urls['tortuga'], "TORTUGA MORA", campo_nombre="cat_desc")
            afeccion_uso_suelo = consultar_wfs_seguro(geom, urls['uso_suelo'], "PLANEAMIENTO", campo_nombre="Clasificacion")
            afeccion_esteparias = consultar_wfs_seguro(geom, urls['esteparias'], "ESTEPARIAS", campo_nombre="nombre")
            afeccion_enp = consultar_wfs_seguro(geom, urls['enp'], "ENP", campo_nombre="nombre")
            afeccion_zepa = consultar_wfs_seguro(geom, urls['zepa'], "ZEPA", campo_nombre="site_name")
            afeccion_lic = consultar_wfs_seguro(geom, urls['lic'], "LIC", campo_nombre="site_name")
            afeccion_vp = consultar_wfs_seguro(geom, urls['vp'], "VP", campo_nombre="vp_nb")
            afeccion_tm = consultar_wfs_seguro(geom, urls['tm'], "TM", campo_nombre="nameunit")
            afeccion_mup = consultar_wfs_seguro(geom, urls['mup'], "MUP", campos_mup=["id_monte:ID", "nombremont:Nombre", "municipio:Municipio", "propiedad:Propiedad"])
            afecciones = [afeccion_flora, afeccion_garbancillo, afeccion_malvasia, afeccion_fartet, afeccion_nutria, afeccion_perdicera, afeccion_tortuga, afeccion_uso_suelo, afeccion_esteparias, afeccion_enp, afeccion_zepa, afeccion_lic, afeccion_vp, afeccion_tm, afeccion_mup]

            # Datos PDF
            ref_parts = st.session_state['ref_cat'].split()
            datos = {
                "fecha_informe": datetime.today().strftime('%d/%m/%Y'),
                "nombre": nombre, "apellidos": apellidos, "dni": dni,
                "dirección": direccion, "teléfono": telefono, "email": email,
                "objeto de la solicitud": objeto,
                "afección MUP": afeccion_mup, "afección VP": afeccion_vp,
                "afección ENP": afeccion_enp, "afección ZEPA": afeccion_zepa,
                "afección LIC": afeccion_lic, "Afección TM": afeccion_tm,
                "afección esteparias": afeccion_esteparias,
                "afección uso_suelo": afeccion_uso_suelo,
                "afección tortuga": afeccion_tortuga,
                "afección perdicera": afeccion_perdicera,
                "afección nutria": afeccion_nutria,
                "afección fartet": afeccion_fartet,
                "afección malvasia": afeccion_malvasia,
                "afección garbancillo": afeccion_garbancillo,
                "afección flora": afeccion_flora,
                "coordenadas_x": x, "coordenadas_y": y,
                "municipio": ref_parts[0], "polígono": ref_parts[2], "parcela": ref_parts[4]
            }

            # Generar mapa
            mapa_html, _ = crear_mapa(lon, lat, afecciones, gpd.GeoDataFrame([geom], crs="EPSG:25830"))
            if mapa_html:
                st.session_state['mapa_html'] = mapa_html
                st.session_state['afecciones'] = afecciones
                st.subheader("Afecciones detectadas")
                for a in afecciones:
                    st.write(f"• {a}")
                with open(mapa_html, 'r') as f:
                    html(f.read(), height=500)

            # Generar PDF
            pdf_file = f"informe_{uuid.uuid4().hex[:8]}.pdf"
            try:
                generar_pdf(datos, x, y, pdf_file)
                st.session_state['pdf_file'] = pdf_file
            except Exception as e:
                st.error(f"Error PDF: {e}")

            # Limpiar
            st.session_state.pop('query_geom', None)
            st.session_state.pop('wfs_urls', None)

# === DESCARGAS ===
if st.session_state['pdf_file']:
    with open(st.session_state['pdf_file'], "rb") as f:
        st.download_button("Descargar informe PDF", f, "informe_afecciones.pdf", "application/pdf")
if st.session_state['mapa_html']:
    with open(st.session_state['mapa_html'], "r") as f:
        st.download_button("Descargar mapa HTML", f.read(), "mapa_busqueda.html", "text/html")
