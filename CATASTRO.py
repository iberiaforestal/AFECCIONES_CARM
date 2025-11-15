# coding=utf-8
import requests
import xmltodict
import json

try:
    __version__ = __import__('pkg_resources') \
        .get_distribution(__name__).version
except Exception as e:
    __version__ = 'unknown'


class Catastro(object):
    """Library developed in python. This library allow to access the public web services of the Portal of Spanish Catastro and obtains the results in json format.
    """

    home_url = "http://ovc.catastro.meh.es/ovcservweb/"

    @classmethod
    def ConsultaProvincia():
        """Proporciona un listado de todas las provincias de España.

           Proporciona un listado de todas las provincias españolas en
           las que tiene competencia la Dirección general del Catastro.
           :return: Retorna los datos que devuelve el servicio del catastro formateados en JSON
           :return_type: json
        """

        url = home_url + "OVCCallejero.asmx/ConsultaProvincia"
        salida_json = json.dumps(
            xmltodict.parse(
                response.content, process_namespaces=False, xml_attribs=False),
            ensure_ascii=False)
        return salida_json

    @classmethod
    def ConsultaMunicipioJSon(provincia, municipio=None):
        """Proporciona un listado de todos los municipios de una provincia.

            Proporciona un listado de todos los nombres de los municipios de una
            provincia (parámetro "Provincia"),así como sus códigos (de Hacienda
            y del INE), cuyo nombre Servicios web del Catastro 5 contiene la cadena
            del parámetro de entrada "Municipio". En caso de que este último
            parámetro no tenga ningún valor, el servicio devuelve todos los
            municipios de la  provincia.También proporciona información de si
            existe cartografía catastral (urbana o rústica) de cada municipio.

            :param str: Nombre de la provincia
            :param str: Opcional , nombre del municipio

            :return: Retorna los datos que devuelve el servicio del catastro formateados en JSON
            :return_type: json
        """

        params = {'Provincia': provincia}
        if municipio:
            params['Municipio'] = municipio
        else:
            params['Municipio'] = ''
        url = home_url + "OVCCallejero.asmx/ConsultaMunicipio"
        salida_json = json.dumps(
            xmltodict.parse(
                response.content, process_namespaces=False, xml_attribs=False),
            ensure_ascii=False)
        return salida_json

    @classmethod
    def Consulta_DNPPPJSon(provincia, municipio, poligono, parcela):
        """Proporciona los datos catastrales no protegidos de un inmueble

           Este servicio es idéntico al de "Consulta de DATOS CATASTRALES NO
           PROTEGIDOS de un inmueble identificado por su localización" en todo
           excepto en los parámetros de entrada.

           :param str: Nombre de la provincia
           :param str: Nombre del municipio
           :param str: Codigo del poligono
           :param str: Codigo de la parcela

           :return: Retorna los datos que devuelve el servicio del catastro formateados en JSON
           :return_type: json
        """

        params = {
            'Provincia': provincia,
            'Municipio': municipio,
            'Poligono': poligono,
            'Parcela': parcela
        }
        url = home_url + "OVCCallejero.asmx/Consulta_DNPPP"
        salida_json = json.dumps(
            xmltodict.parse(
                response.content, process_namespaces=False, xml_attribs=False),
            ensure_ascii=False)
        return salida_json


    @classmethod
    def ConsultaRCCOORJSon(srs, x, y):
        """A partir de unas coordenadas se obtiene la referencia catastral.

           A partir de unas coordenadas (X e Y) y su sistema de referencia se
           obtiene la referencia catastral de la parcela localizada en ese punto
           así como el domicilio (municipio, calle y número o polígono, parcela y
           municipio).

           :param str,int: Sistema de coordenadas
           :param str,int,float: Coordanda x
           :param str,int,float: Coordenada Y

           :return: Retorna los datos que devuelve el servicio del catastro formateados en JSON
           :return_type: json
        """

        params = {"Coordenada_X": str(x), "Coordenada_Y": str(y)}
        if type(srs) == str:
            params["SRS"] = srs
        else:
            params["SRS"] = "EPSG:" + str(srs)
        url = home_url + "OVCCoordenadas.asmx?op=Consulta_RCCOOR"
        salida_json = json.dumps(
            xmltodict.parse(
                response.content, process_namespaces=False, xml_attribs=False),
            ensure_ascii=False)
        return salida_json

    @classmethod
    def ConsultaCPMRCJSon(provicia, municipio, srs, rc):
        """Proporciona la localizacion de una parcela.

           A partir de la RC de una parcela se obtienen las coordenadas X, Y en el
           sistema de referencia en el que está almacenado el dato en la D.G. del
           Catastro, a menos que se especifique lo contrario en el parámetro
           opcional SRS que se indica en la respuesta, así como el domicilio
           (municipio, calle y número o polígono, parcela y unicipio).

           :param str: Nombre de la provincia
           :param str: Nombre del municipio
           :param str,int: Sistema de coordenadas
           :param str: Referencia catastral

           :return: Retorna los datos que devuelve el servicio del catastro formateados en JSON
           :return_type: json
        """

        params = {
            'SRS': srs,
            'Provincia': provicia,
            'Municipio': municipio,
            'RC': rc
        }
        url = home_url + "OVCCoordenadas.asmx/Consulta_CPMRC"
        salida_json = json.dumps(
            xmltodict.parse(
                response.content, process_namespaces=False, xml_attribs=False),
            ensure_ascii=False)
        return salida_json


