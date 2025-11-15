import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

# ===================== CONFIGURACIÓN =====================
st.set_page_config(
    page_title="Estadísticas Afecciones CARM",
    page_icon="📊",
    layout="wide"
)

# Contraseña (cámbiala por la que quieras)
PASSWORD = "carm2025stats"   # ← ¡CÁMBIALA!

# ===================== AUTENTICACIÓN =====================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 Estadísticas Internas - Afecciones CARM")
    pwd = st.text_input("Contraseña de acceso", type="password")
    if st.button("Entrar"):
        if pwd == PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    st.stop()

# ===================== CARGA DE DATOS =====================
if not os.path.exists("usage_stats.db"):
    st.error("⚠️ No se encontró usage_stats.db")
    st.info("Sube el archivo descargado desde la app principal")
    st.stop()

conn = sqlite3.connect("usage_stats.db")
df = pd.read_sql_query("SELECT * FROM usage ORDER BY fecha DESC", conn)
conn.close()

df["fecha"] = pd.to_datetime(df["fecha"])
df["fecha_date"] = df["fecha"].dt.date

# ===================== INTERFAZ =====================
st.image("https://www.carm.es/wp-content/uploads/2023/06/logo-carm-blanco.png", width=200)
st.title(" fdb Estadísticas de uso - Informes de Afecciones")
st.markdown(f"**Última actualización:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")

col1, col2, col3, col4 = st.columns(4)
total = len(df)
usuarios = df["ip_hash"].nunique()
municipios = df["municipio"].nunique()
primer = df["fecha"].min().strftime("%d/%m/%Y") if not df.empty else "-"

with col1: st.metric("Total informes", f"{total:,}")
with col2: st.metric("Usuarios únicos", f"{usuarios:,}")
with col3: st.metric("Municipios distintos", municipios)
with col4: st.metric("Desde", primer)

st.markdown("---")

c1, c2 = st.columns([2,1])

with c1:
    st.subheader("Top 15 municipios")
    top_mun = df["municipio"].value_counts().head(15)
    fig1 = px.bar(y=top_mun.index, x=top_mun.values, orientation='h',
                  text=top_mun.values, color=top_mun.values,
                  color_continuous_scale="emrld")
    fig1.update_layout(height=600, yaxis={'categoryorder':'total ascending'})
    st.plotly_chart(fig1, use_container_width=True)

with c2:
    st.subheader("Evolución diaria")
    daily = df.groupby(df["fecha"].dt.date).size().reset_index(name="informes")
    daily.columns = ["fecha", "informes"]
    fig2 = px.area(daily, x="fecha", y="informes", markers=True, color_discrete_sequence=["#006666"])
    fig2.update_layout(height=600)
    st.plotly_chart(fig2, use_container_width=True)

st.markdown("---")
st.subheader("Últimos 30 informes generados")
ultimos = df.head(30)[["fecha", "municipio", "poligono", "parcela", "objeto"]].copy()
ultimos["fecha"] = ultimos["fecha"].dt.strftime("%d/%m %H:%M")
st.dataframe(ultimos, use_container_width=True)

# Descarga CSV
csv = df.to_csv(index=False).encode()
st.download_button("📥 Descargar todos los datos (CSV)", csv,
                   f"afecciones_stats_{datetime.now().strftime('%Y%m%d')}.csv",
                   "text/csv")

# Botón de cerrar sesión
if st.button("Cerrar sesión"):
    st.session_state.authenticated = False
    st.rerun()