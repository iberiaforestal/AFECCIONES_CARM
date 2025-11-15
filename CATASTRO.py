# utils/catastro.py
# CATASTRO NACIONAL - CARGA SÍ O SÍ - 15/11/2025

import streamlit as st
import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point
import requests
from io import BytesIO
import time

# Transformer
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# Sesión con headers
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json'
})

@st.cache_data(ttl=3600)
def _wfs_request(typename, bbox=None, cql_filter=None):
    url = "https://ovc.catastro.hacienda.gob.es/INSPIRE/wfs"
    params = {
        'service': 'WFS',
        'version': '1.1.0',
        'request': 'GetFeature',
        'typeName': typename,
        'outputFormat': 'application/json'
    }
    if bbox:
        params['bbox'] = bbox
    if cql_filter:
        params['CQL_FILTER'] = cql_filter

    for _ in range(3):  # 3 intentos
        try:
            response = session.get(url, params=params, timeout=30)
            if response.status_code == 200:
                return gpd.read_file(BytesIO(response.content))
        except:
            time.sleep(1)
    return gpd.GeoDataFrame()

def get_catastro_info(**kwargs):
    if 'x' in kwargs and 'y' in kwargs:
        x, y = kwargs['x'], kwargs['y']
        lon, lat = transformer.transform(x, y)
        punto = Point(lon, lat)
        buffer = 0.00005  # ~5 metros
        bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"

        # Provincia
        gdf = _wfs_request("AU:AdministrativeUnit", bbox)
        provincia = ca = "N/A"
        if not gdf.empty and gdf.intersects(punto).any():
            row = gdf[gdf.intersects(punto)].iloc[0]
            provincia = row.get('nationalProvinceName', 'N/A')
            ca = row.get('nationalCountryName', 'N/A')

        # Municipio
        gdf = _wfs_request("AU:AdministrativeBoundary", bbox)
        municipio = "N/A"
        if not gdf.empty and gdf.intersects(punto).
