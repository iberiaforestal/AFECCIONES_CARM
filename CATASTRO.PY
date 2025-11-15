# pages/catastro.py
# CATASTRO ESPAÑA - ESCALONADO - PDF
# ENTRADA: Coordenadas (X,Y) o Datos (CA, Provincia, Pol, Parc)
# SALIDA: PDF con CA, Provincia, Municipio, Polígono, Parcela, Ref, Coords

import streamlit as st
from fpdf import FPDF
import tempfile
from utils.catastro import get_catastro_info  # <-- TU CÓDIGO DE CATASTRO
from pyproj import Transformer

st.set_page_config(page_title="Catastro Nacional", layout="centered")
st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/36/Escudo_de_Espa%C3%B1a.svg/200px-Escudo_de_Espa%C3%B1a_svg.png", width=100)
st.title("Catastro Nacional - Informe Escalonado")

# Transformer
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# ------------------- INPUT -------------------
tab1, tab2 = st.tabs(["Por Coordenadas", "Por Datos Catastrales"])

info = None
x, y, lon, lat = None, None, None, None

# === POR COORDENADAS ===
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        x_input = st.number_input("X (ETRS89)", value=670000, key="x_coord")
    with col2:
        y_input = st.number_input("Y (ETRS89)", value=4610000, key="y_coord")
    if st.button("GENERAR INFORME POR COORDENADAS", type="primary"):
        info = get_catastro_info(x=x_input, y=y_input, ca="España")
        if info:
            x, y = x_input, y_input
            lon, lat = transformer.transform(x, y)

# === POR DATOS ===
with tab2:
    col1, col2 = st.columns(2)
    with col1:
        provincia = st.text_input("Provincia", "Zaragoza")
        poligono = st.text_input("Polígono", "00123")
    with col2:
        parcela = st.text_input("Parcela", "45")
    if st.button("GENERAR INFORME POR DATOS", type="primary"):
        info = get_catastro_info(ca="España", provincia=provincia, poligono=poligono, parcela=parcela)
        if info and 'geometry' in info:
            centro = info['geometry'].centroid
            x, y = centro.x, centro.y
            lon, lat = transformer.transform(x, y)

# ------------------- RESULTADO + PDF -------------------
if info and x is not None:
    st.success("PARCELA ENCONTRADA")
    st.markdown(f"""
    **Comunidad Autónoma:** {info.get('ca', 'España')}  
    **Provincia:** {info.get('provincia', 'N/A')}  
    **Municipio:** {info.get('municipio', 'N/A')}  
    **Polígono:** {info.get('poligono', 'N/A')}  
    **Parcela:** {info.get('parcela', 'N/A')}  
    **Referencia Catastral:** {info.get('ref_catastral', 'N/A')}  
    **Coordenadas (ETRS89):** X={x:.0f}, Y={y:.0f}  
    **Coordenadas (WGS84):** Lat={lat:.6f}, Lon={lon:.6f}
    """)

    # === PDF ===
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 14)
            self.cell(0, 10, 'INFORME CATASTRAL NACIONAL', ln=True, align='C')
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Página {self.page_no()}', align='C')

    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)

    pdf.cell(0, 8, "DATOS CATASTRALES ESCALONADOS", ln=True, align='C')
    pdf.ln(5)

    datos = [
        ("Comunidad Autónoma", info.get('ca', 'España')),
        ("Provincia", info.get('provincia', 'N/A')),
        ("Municipio", info.get('municipio', 'N/A')),
        ("Polígono", info.get('poligono', 'N/A')),
        ("Parcela", info.get('parcela', 'N/A')),
        ("Referencia Catastral", info.get('ref_catastral', 'N/A')),
        ("Coordenadas (ETRS89)", f"X={x:.0f}, Y={y:.0f}"),
        ("Coordenadas (WGS84)", f"Lat={lat:.6f}, Lon={lon:.6f}"),
        ("Fuente", "Catastro INSPIRE - Ministerio de Hacienda"),
        ("Fecha", "15/11/2025")
    ]

    for label, value in datos:
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(60, 8, label + ":", ln=False)
        pdf.set_font("Arial", size=11)
        pdf.cell(0, 8, str(value), ln=True)

    # Guardar y descargar
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf.output(tmp.name)
        st.download_button(
            label="DESCARGAR PDF",
            data=open(tmp.name, "rb"),
            file_name=f"catastro_{info.get('ref_catastral', 'desconocida')}.pdf",
            mime="application/pdf"
        )

else:
    if st.session_state.get("button_pressed"):
        st.error("No se encontró la parcela. Verifica los datos.")