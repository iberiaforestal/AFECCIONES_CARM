# pages/CATASTRO.py
# CATASTRO NACIONAL - FUNCIONA SÍ O SÍ
# SIN ERRORES DE SINTAXIS

import streamlit as st
from fpdf import FPDF
import tempfile
from utils.catastro import get_catastro_info
from pyproj import Transformer

st.set_page_config(page_title="Catastro Nacional", layout="centered")
st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/36/Escudo_de_Espa%C3%B1a.svg/200px-Escudo_de_Espa%C3%B1a_svg.png", width=100)
st.title("Catastro Nacional - Informe Escalonado")

# Transformer
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# --- INPUT ---
col1, col2 = st.columns(2)
with col1:
    x = st.number_input("X (ETRS89)", value=670000, step=1)
with col2:
    y = st.number_input("Y (ETRS89)", value=4610000, step=1)

if st.button("GENERAR INFORME", type="primary"):
    with st.spinner("Consultando Catastro... (puede tardar 5-10 seg)"):
        info = get_catastro_info(x=x, y=y)

    if info:
        # Transformar coordenadas
        lon, lat = transformer.transform(x, y)

        # --- MOSTRAR RESULTADO ---
        st.success("¡PARCELA ENCONTRADA!")
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

        # --- GENERAR PDF ---
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

        datos = [
            ("Comunidad Autónoma", info.get('ca', 'España')),
            ("Provincia", info.get('provincia', 'N/A')),
            ("Municipio", info.get('municipio', 'N/A')),
            ("Polígono", info.get('poligono', 'N/A')),
            ("Parcela", info.get('parcela', 'N/A')),
            ("Referencia Catastral", info.get('ref_catastral', 'N/A')),
            ("Coordenadas ETRS89", f"X={x:.0f}, Y={y:.0f}"),
            ("Coordenadas WGS84", f"Lat={lat:.6f}, Lon={lon:.6f}"),
            ("Fuente", "Catastro INSPIRE - Ministerio de Hacienda"),
            ("Fecha", "15/11/2025")
        ]

        for label, value in datos:
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(60, 8, f"{label}:", ln=False)
            pdf.set_font("Arial", size=11)
            pdf.cell(0, 8, str(value), ln=True)

        # --- DESCARGAR PDF ---
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf.output(tmp.name)
            st.download_button(
                label="DESCARGAR PDF",
                data=open(tmp.name, "rb").read(),
                file_name=f"catastro_{info.get('ref_catastral', 'desconocida')}.pdf",
                mime="application/pdf"
            )
    else:
        st.error("No se encontró parcela. Prueba con coordenadas más precisas o dentro de un municipio.")
