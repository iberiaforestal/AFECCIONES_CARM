# archivo: catastro_app.py

import streamlit as st
import geopandas as gpd
import requests
import contextily as ctx
import matplotlib.pyplot as plt

st.title("🔍 Buscador Catastro España - WFS 2025")
st.markdown("Introduce la referencia catastral de 20 dígitos (rústica o urbana)")

ref = st.text_input("Referencia catastral", "13045A00100001000000")

if st.button("Buscar parcela"):
    if len(ref) != 20:
        st.error("La referencia debe tener exactamente 20 caracteres")
    else:
        with st.spinner("Consultando Catastro..."):
            url = "https://services.catastro.hacienda.gob.es/INSPIRE/CP/wfs"
            params = {
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": "CP.CadastralParcel",
                "CQL_FILTER": f"reference='{ref}'",
                "outputFormat": "application/json"
            }
            r = requests.get(url, params=params, timeout=30)
            
            if r.status_code != 200 or r.json()["features"] == []:
                st.error("Parcela no encontrada")
            else:
                gdf = gpd.read_file(r.content)
                parcela = gdf.iloc[0]
                
                st.success(f"¡Encontrada! Superficie: {int(parcela.areaValue):,} m²")
                
                fig, ax = plt.subplots(figsize=(10,8))
                gdf.to_crs(epsg=3857).plot(ax=ax, facecolor="none", edgecolor="red", linewidth=4)
                ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik)
                ax.set_title(f"Ref. {ref}")
                ax.axis('off')
                st.pyplot(fig)
                
                st.download_button("Descargar GeoJSON", gdf.to_json(), f"{ref}.geojson")
