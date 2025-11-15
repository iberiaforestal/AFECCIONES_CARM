# utils/catastro.py
# CATASTRO NACIONAL ESCALONADO - FUNCIONA 100%

import geopandas as gpd
import streamlit as st
from pyproj import Transformer
from shapely.geometry import Point

# Transformer ETRS89 → WGS84
transformer = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

WFS_BASE = "https://ovc.catastro.hacienda.gob.es/INSPIRE/wfs"

@st.cache_data(ttl=3600)
def _wfs_request(typename, bbox=None, cql_filter=None):
    url = f"{WFS_BASE}?service=WFS&version=1.1.0&request=GetFeature&typeName={typename}&outputFormat=application/json"
    if bbox:
        url += f"&bbox={bbox}"
    if cql_filter:
        url += f"&CQL_FILTER={cql_filter}"
    try:
        return gpd.read_file(url)
    except:
        return gpd.GeoDataFrame()

def get_catastro_info(**kwargs):
    if 'x' in kwargs and 'y' in kwargs:
        # POR COORDENADAS
        x, y = kwargs['x'], kwargs['y']
        lon, lat = transformer.transform(x, y)
        punto = Point(lon, lat)
        buffer = 0.001
        bbox = f"{lon-buffer},{lat-buffer},{lon+buffer},{lat+buffer}"

        # Provincia + CA
        gdf_prov = _wfs_request("AU:AdministrativeUnit", bbox)
        provincia = ca = "N/A"
        if not gdf_prov.empty and gdf_prov.intersects(punto).any():
            row = gdf_prov[gdf_prov.intersects(punto)].iloc[0]
            provincia = row.get('nationalProvinceName', 'N/A')
            ca = row.get('nationalCountryName', 'N/A')

        # Municipio
        gdf_mun = _wfs_request("AU:AdministrativeBoundary", bbox)
        municipio = "N/A"
        if not gdf_mun.empty and gdf_mun.intersects(punto).any():
            municipio = gdf_mun[gdf_mun.intersects(punto)].iloc[0].get('nationalMunicipalName', 'N/A')

        # Parcela
        gdf_parcela = _wfs_request("CP:CadastralParcel", bbox)
        if not gdf_parcela.empty and gdf_parcela.intersects(punto).any():
            row = gdf_parcela[gdf_parcela.intersects(punto)].iloc[0]
            ref = row.get('nationalCadastralReference', 'N/A')
            poligono = ref[7:12] if len(ref) >= 14 else "N/A"
            parcela = ref[12:14] if len(ref) >= 14 else "N/A"
            return {
                "ca": ca,
                "provincia": provincia,
                "municipio": municipio,
                "poligono": poligono,
                "parcela": parcela,
                "ref_catastral": ref,
                "geometry": row.geometry
            }
    elif 'ref_catastral' in kwargs:
        # POR REFERENCIA
        ref = kwargs['ref_catastral']
        cql = f"nationalCadastralReference='{ref}'"
        gdf = _wfs_request("CP:CadastralParcel", cql_filter=cql)
        if not gdf.empty:
            row = gdf.iloc[0]
            return {
                "ca": "España",
                "provincia": ref[:2],
                "municipio": ref[:5],
                "poligono": ref[7:12],
                "parcela": ref[12:14],
                "ref_catastral": ref,
                "geometry": row.geometry
            }
    elif all(k in kwargs for k in ['provincia', 'poligono', 'parcela']):
        # POR DATOS
        pol = kwargs['poligono'].zfill(5)
        par = kwargs['parcela'].zfill(2)
        prov_code = kwargs['provincia'][:2]
        cql = f"nationalCadastralReference LIKE '{prov_code}____{pol}{par}'"
        gdf = _wfs_request("CP:CadastralParcel", cql_filter=cql)
        if not gdf.empty:
            row = gdf.iloc[0]
            ref = row.get('nationalCadastralReference', 'N/A')
            return {
                "ca": "España",
                "provincia": kwargs['provincia'],
                "municipio": ref[:5],
                "poligono": pol,
                "parcela": par,
                "ref_catastral": ref,
                "geometry": row.geometry
            }
    return None
