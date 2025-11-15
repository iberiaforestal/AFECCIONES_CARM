from zeep import Client

CATASRO_WCF_URL = "https://www.catastro.hacienda.gob.es/OVCServWeb/OVCWcf.asmx?wsdl"

client = Client(CATASRO_WCF_URL)

def encontrar_municipio_poligono_parcela_wcf(lat, lon):
    """
    Busca la parcela que contiene las coordenadas (lat, lon)
    usando el servicio WCF Consulta_RCCOOR.
    Devuelve JSON con municipio, polígono, parcela y RefCat.
    """
    try:
        response = client.service.Consulta_RCCOOR(
            Latitud=str(lat),
            Longitud=str(lon),
            SRS="EPSG:4326"
        )
        
        # Zeep devuelve un objeto tipo dict/XML; lo convertimos a dict simple
        # La estructura típica:
        # response.lpi.pnp -> polígono
        # response.lpi.par -> parcela
        # response.lpi.prov -> provincia
        # response.lpi.mun -> municipio
        resultado = {
            "Poligono": getattr(response.lpi, "pnp", None),
            "Parcela": getattr(response.lpi, "par", None),
            "Provincia": getattr(response.lpi, "prov", None),
            "Municipio": getattr(response.lpi, "mun", None),
        }
        return resultado
    except Exception as e:
        print(f"Error en WCF: {str(e)}")
        return {
            "Poligono": None,
            "Parcela": None,
            "Provincia": None,
            "Municipio": None,
        }
