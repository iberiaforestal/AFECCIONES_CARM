import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

st.set_page_config(page_title="Stats Afecciones CARM", layout="wide")

# === CONTRASEÑA (cambia la que quieras) ===
PASSWORD = "carm2025stats"   # ← tu contraseña

if st.secrets.get("password", "") != PASSWORD:
    pwd = st.text_input("Contraseña", type="password")
    if pwd != PASSWORD:
        st.error("Acceso denegado")
        st.stop()

# === LECTURA DIRECTA DEL ARCHIVO QUE USA LA APP PRINCIPAL ===
DB_PATH = "../usage_stats.db"   # ← ¡¡MAGIA!! apunta a la raíz

if not os.path.exists(DB_PATH):
    st.error("La app principal aún no ha generado informes")
    st.info("Genera al menos un informe en la app principal")
    st.stop()

conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query("SELECT * FROM usage ORDER BY fecha DESC", conn)
conn.close()

df["fecha"] = pd.to_datetime(df["fecha"])

# === INTERFAZ IGUAL QUE ANTES, pero 100% en tiempo real ===
st.image("https://www.carm.es/wp-content/uploads/2023/06/logo-carm-blanco.png", width=180)
st.title("Estadísticas en tiempo real - Informes de Afecciones")

col1, col2, col3 = st.columns(3)
with col1: st.metric("Informes generados", len(df))
with col2: st.metric("Usuarios únicos", df["ip_hash"].nunique())
with col3: st.metric("Municipios distintos", df["municipio"].nunique())

# Gráfico rápido
daily = df.groupby(df["fecha"].dt.date).size().reset_index(name="n")
fig = px.area(daily, x="fecha", y="n", title="Evolución diaria")
st.plotly_chart(fig, use_container_width=True)

st.dataframe(df[["fecha","municipio","poligono","parcela"]].head(50))
