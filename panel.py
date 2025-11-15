# dashboard/app.py → VERSIÓN FINAL OFICIAL (15-nov-2025)
import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

st.set_page_config(page_title="Estadísticas Afecciones CARM", layout="wide", initial_sidebar_state="collapsed")

# ────── LOGIN ──────
PASSWORD = "carm2025"   # ← cambia por la tuya

if st.session_state.get("auth") != True:
    st.image("https://www.carm.es/wp-content/uploads/2023/06/logo-carm-blanco.png", width=200)
    st.title("Estadísticas Internas - Afecciones CARM")
    pwd = st.text_input("Contraseña de acceso", type="password")
    col1, col2, col3 = st.columns([1,1,1])
    if col2.button("Entrar", use_container_width=True):
        if pwd == PASSWORD:
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    st.stop()

# ────── CARGA DE DATOS EN TIEMPO REAL ──────
@st.cache_data(ttl=60)  # se actualiza cada 60 segundos automáticamente
def load_data():
    conn = sqlite3.connect("../usage_stats.db")
    df = pd.read_sql_query("SELECT * FROM usage ORDER BY fecha DESC", conn)
    conn.close()
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df

df = load_data()

# ────── HEADER ──────
st.image("https://www.carm.es/wp-content/uploads/2023/06/logo-carm-blanco.png", width=180)
st.title("📊 Estadísticas en tiempo real — Informes de Afecciones")
st.markdown(f"**Última actualización:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

# ────── MÉTRICAS ──────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total informes", f"{len(df):,}")
c2.metric("Usuarios únicos", f"{df['ip_hash'].nunique():,}")
c3.metric("Municipios distintos", df["municipio"].nunique())
c4.metric("Media diaria (últimos 30 días)", f"{len(df[df['fecha'] > datetime.now()-pd.Timedelta(days=30)]) / 30:.1f}")

# ────── GRÁFICOS ──────
col1, col2 = st.columns([1.5, 1])

with col1:
    st.subheader("Top 20 municipios")
    top20 = df["municipio"].value_counts().head(20)
    fig = px.bar(y=top20.index, x=top20.values, orientation='h', height=600,
                 color=top20.values, color_continuous_scale="emrld")
    fig.update_layout(yaxis={'categoryorder':'total ascending'})
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Evolución diaria")
    daily = df.groupby(df["fecha"].dt.date).size().reset_index(name="informes")
    daily["fecha"] = pd.to_datetime(daily["fecha"])
    fig2 = px.area(daily, x="fecha", y="informes", height=600, color_discrete_sequence=["#006666"])
    st.plotly_chart(fig2, use_container_width=True)

# ────── TABLA ÚLTIMOS ──────
st.subheader("Últimos 25 informes generados")
ultimos = df.head(25)[["fecha", "municipio", "poligono", "parcela", "objeto"]].copy()
ultimos["fecha"] = ultimos["fecha"].dt.strftime("%d/%m %H:%M")
st.dataframe(ultimos, use_container_width=True, hide_index=True)

# ────── DESCARGA + CIERRE ──────
colx, coly = st.columns([1, 4])
with colx:
    csv = df.to_csv(index=False).encode()
    st.download_button("📥 CSV completo", csv, f"afecciones_stats_{datetime.now():%Y%m%d}.csv", "text/csv")
with coly:
    if st.button("Cerrar sesión"):
        st.session_state.auth = False
        st.rerun()

# Auto-refresh cada 60 segundos
st.rerun() if st.checkbox("Auto-refresh cada minuto", value=True) else None

