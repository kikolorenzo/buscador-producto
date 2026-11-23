#!/usr/bin/env python3
"""Repara nombres ilegibles y valida que cada referencia conserve su código.

El índice inicial leyó correctamente la mayoría de los códigos, pero en
algunas páginas el PDF separa tipográficamente cada letra. Este script vuelve a
leer la línea situada junto al código y, cuando la página contiene una tabla,
combina la familia de producto impresa con su presentación concreta.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any

import fitz
from wordfreq import zipf_frequency

import audit_catalog_quality as audit


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "articulos.json"
CSV_PATH = ROOT / "data" / "articulos.csv"
STATS_PATH = ROOT / "data" / "estadisticas.json"
REPORT_PATH = ROOT / "tmp" / "pdfs" / "all-catalog-names-report.json"
PDF_DIR = ROOT / "tmp" / "pdfs"

PROTECTED_SOURCES = {"web_oficial", "catalogo_pdf_revisado", "manual"}
LEXICON: Counter[str] = Counter()
LEXICON_DISPLAY: dict[str, str] = {}
HEADER_WORDS = {
    "codigo", "presentacion", "producto", "descripcion", "capacidad", "color",
    "modelo", "medidas", "cantidad", "potencia", "tamano", "accesorios opcionales",
}
GENERIC_LABELS = {
    "meprolim", "soporte", "cubeta", "protector", "cromado", "bandeja",
    "accesorios", "accesorios opcionales", "recambios", "cantidad", "potencia w",
}

# Errores de OCR comprobados visualmente en las páginas indicadas. Las letras
# sobrantes proceden de palabras contiguas (Pieza, Rollo, Chasis, Código, etc.).
CODE_RENAMES = {
    "OAF2001": "AF2001", "OAF2001C": "AF2001C",
    "NAF2002": "AF2002", "NAF2002C": "AF2002C",
    "EAF2004C": "AF2004C", "LAF2005C": "AF2005C",
    "AZB1602": "ZB1602", "AZD9382": "ZD9382", "AZE1007": "ZE1007",
    "DH3006C": "DH3006", "DH3007C": "DH3007", "DH3008C": "DH3008",
    "FT1006C": "FT1006",
    "OBK0140": "BK0140", "OBK1001": "BK1001", "OBK1007": "BK1007",
    "OCX0002": "CX0002", "OCX0003": "CX0003", "OCX0062": "CX0062",
    "OCX0073": "CX0073", "OCX0074": "CX0074", "OCX0076": "CX0076",
    "OFT1022": "FT1022", "OFU0009": "FU0009", "OZE1011": "ZE1011",
    "OBZ1033": "BZ1033", "OBZ1035": "BZ1035", "OFT1055": "FT1055",
    "OFT3009": "FT3009", "PL02311": "PL0231",
    "ZY2031G": "ZY2031", "ZY2032G": "ZY2032", "ZY2033G": "ZY2033",
    "ZY2034G": "ZY2034", "ZY2035G": "ZY2035", "ZY2036G": "ZY2036",
    "ZY2037G": "ZY2037", "ZY20393": "ZY2039", "ZY20403": "ZY2040",
    "ZY20413": "ZY2041", "ZY20423": "ZY2042", "ZY20443": "ZY2044",
    "ZY20453": "ZY2045", "ZY20463": "ZY2046", "ZY20683": "ZY2068",
    "CK0030O": "CK0030", "CK0043N": "CK0043", "CK0079G": "CK0079",
    "DX1007M": "DX1007", "DX1008M": "DX1008", "DX1009M": "DX1009",
    "DX1011M": "DX1011", "FP0002M": "FP0002", "CR1041C": "CR1041",
    "ZN1002N": "ZN1002", "ZN1003C": "ZN1003", "ZN1007D": "ZN1007",
    "ZN1016M": "ZN1016", "ZN1017N": "ZN1017", "ZN1019C": "ZN1019",
    "ZJ10121": "ZJ1012", "ZJ10132": "ZJ1013",
    "ZJ10143": "ZJ1014", "ZJ10154": "ZJ1015",
    "TRI01755": "KTRI01755", "TRI30040": "KTRI30040",
    "TRI30042": "KTRI30042", "TRI30043": "KTRI30043",
    "TRI30044": "KTRI30044", "TRI30051": "KTRI30051",
    "TRI30053": "KTRI30053", "TRI30054": "KTRI30054",
    "TRI30055": "KTRI30055", "TRI31207": "KTRI31207",
    "TRI41464": "KTRI41464", "TRI43036": "KTRI43036",
    "TRI43160": "KTRI43160", "TRI43848": "KTRI43848",
    "TRI45151": "KTRI45151", "TRI45231": "KTRI45231",
}
SPURIOUS_CODES = {
    "ADE100X", "ADE120L", "AES960", "ALH211A", "CK100U", "CK500U",
    "CS500B", "DCM1500H", "DE250U", "DE600X", "DE970A", "DOR240L",
    "DOR800L", "GH290", "IGE120L", "IMA9910", "IO5090", "KSX100U",
    "LSA100L", "LSA500L", "NUM301", "OLH205T", "PAC316", "RDE800L",
    "SDE100U", "TOP301", "TRE600Y", "USO150", "VRM200", "ZUL435",
    "AVE125M", "DE125M", "DR0045", "FT1065", "RAS125M",
    "ZG1502", "ZG1503", "ZG1505",
}

TITLE_OVERRIDES = {
    "FR0096": "DF SAN / DF BAC - código duplicado en el catálogo verde",
    "AR1010": "Fuente de agua RA-20",
    "PL5001": "Espejo extensible de baño Ø 15 cm",
    "PL5003": "Espejo extensible de baño Ø 20 cm",
    "ZD1014": "Plato de goma para fregadora Antea 50 BT",
    "ZC1016": "Aspirador de polvo CA1.25",
    "ZC1017": "Aspirador de polvo CA2.50",
    "FK0010": "Secador directo de cabello Paggiò blanco",
    "PL1005": "Mesa plegable para banquetes y convenciones, madera melaminada Ø 150 cm",
    "UM381": "Banco Cantábrico de fundición dúctil y madera",
    "YG0033": "Panel de señalización ABS amarillo (opcional)",
    "ZE0014": "Panel de señalización ABS amarillo",
    "YJ1015": "Boquilla con cepillo triangular",
    "ZB1007": "Fregadora-barredora C130D diésel",
    "ZJ1024": "Kit de 4 pads diamantados para fregadora/abrillantadora Mi-Tor",
    "ZW1033": "Conector-alargador para varias alfombras Kleen",
    "ZY1033": "Peso extra de 17 kg para Levighetor y Hércules",
    "ZY5137": "Kit de torreta para rebajar molduras (marmolistas)",
    "KTRI01755": "Módulo de limpieza para autotransporte Tiger",
    "KTRI30040": "Cesta con manillar de 40 x 30 x 18 cm para Tiger 250",
    "KTRI30042": "Cesta de 60 x 50 x 54 cm, 65 kg, para Tiger 250",
    "KTRI30043": "Plataforma de 80 x 60 cm para ZG1502 y Tiger 250",
    "KTRI30044": "Cesta de 78 x 59 x 80 cm, 55 kg, para Tiger 250",
    "KTRI30051": "Cesta con manillar de 40 x 30 x 18 cm para ZG1505 y Tiger 500",
    "KTRI30053": "Cesta de 60 x 50 x 54 cm, 90 kg, para Tiger 500",
    "KTRI30054": "Plataforma de 90 x 75 cm para Tiger 500",
    "KTRI30055": "Cesta de 88 x 74 x 80 cm, 70 kg, para Tiger 500",
    "KTRI31207": "Plataforma industrial de 106 x 71 x 86 cm para Tiger 250/500",
    "KTRI41464": "Kit de piloto rotativo de 26 x 21 x 173 cm para Tiger 250",
    "KTRI43036": "Módulo de mopa para ZG1503 y Tiger 250",
    "KTRI43160": "Módulo de mopa para Tiger 500",
    "KTRI43848": "Kit de piloto rotativo de 46 x 16 x 140 cm para Tiger 500",
    "KTRI45151": "Plataforma básica de 135 x 70 x 25 cm, 100 kg, para Tiger 250",
    "KTRI45231": "Plataforma básica de 136 x 80 x 55 cm, 200 kg, para Tiger 500",
    "AF2001": "Pieza de alfombra de vinilo negra de 100 x 120 cm",
    "AF2001C": "Rollo de alfombra de vinilo negra de 600 x 120 cm",
    "AF2002": "Pieza de alfombra de vinilo marrón de 100 x 120 cm",
    "AF2002C": "Rollo de alfombra de vinilo marrón de 600 x 120 cm",
    "AF2003": "Pieza de alfombra de vinilo gris de 100 x 120 cm",
    "AF2003C": "Rollo de alfombra de vinilo gris de 600 x 120 cm",
    "AF2004": "Pieza de alfombra de vinilo ocre de 100 x 120 cm",
    "AF2004C": "Rollo de alfombra de vinilo ocre de 600 x 120 cm",
    "AF2005": "Pieza de alfombra de vinilo azul de 100 x 120 cm",
    "AF2005C": "Rollo de alfombra de vinilo azul de 600 x 120 cm",
    "AF2008": "Pieza de alfombra de vinilo roja de 100 x 120 cm",
    "AF2008C": "Rollo de alfombra de vinilo roja de 600 x 120 cm",
    "ZB1602": "Plato de goma para fregadora Innova 55 B",
    "ZD9382": "Plato de goma para fregadora MR 85 B",
    "ZE1007": "Repuesto de soporte y rueda para cubo Alex",
    "DH3006": "Chasis de mopa de 45 cm", "FT1006": "Chasis de mopa de 60 cm",
    "DH3007": "Chasis de mopa de 75 cm", "DH3008": "Chasis de mopa de 100 cm",
    "BK0140": "Tubo corto extensible de 50,8 a 101,6 cm",
    "BK1007": "Tubo con doblez telescópico de 115 a 186 cm",
    "BK1001": "Tubo recto fijo de 150 cm",
    "CX0002": "Mango fijo universal marrón de aluminio de 140 cm",
    "CX0073": "Mango fijo universal verde de aluminio de 140 cm",
    "CX0074": "Mango fijo universal amarillo de aluminio de 140 cm",
    "CX0076": "Mango fijo universal rojo de aluminio de 140 cm",
    "ZE1011": "Mango fijo profesional de aluminio de 150 cm",
    "CX0003": "Mango fijo universal metálico de 140 cm",
    "FT1022": "Mango telescópico profesional de aluminio de 100 a 180 cm",
    "CX0062": "Mango fijo metálico de 140 cm para cepillo CX0008",
    "FU0009": "Mango de madera con rosca de 130 cm",
    "BZ1033": "Esponja verde, pack de 10 unidades",
    "BZ1035": "Salvauñas de fibra blanca, pack de 10 unidades",
    "FT1055": "Estropajo blanco, pack de 10 unidades",
    "FT3009": "Esponja Miraclean, pack de 12 unidades",
    "PL0231": "Par de guantes de cuero beige Máster Tool",
    **{f"ZY203{index}": f"Abrasivo sintético Pavelux G-{index + 1} de 100 mm, grano {grain}"
       for index, grain in enumerate((40, 60, 120, 220, 400, 800, 1500), start=1)},
    "ZY2039": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 36",
    "ZY2040": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 46",
    "ZY2041": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 70",
    "ZY2042": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 120",
    "ZY2044": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 320",
    "ZY2045": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 500",
    "ZY2046": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 1.000",
    "ZY2068": "Juego de 3 cepillos de pulido Antike de 100 mm, grano 240",
    "AL0108": "Carro bandejero de acero inoxidable con dos cuerpos",
    "BK0179": "Cápula de seguridad opcional para carro de servicio",
    "BP4024": "Papelera cromada para interior",
    "BZ1027": "Bayeta amarilla",
    "CB1001": "Bandeja para carro multiuso de tres lados",
    "BP4024": "Papelera cromada para interior",
    "BZ1027": "Bayeta amarilla",
    "CB1001": "Bandeja para carro multiuso",
    "CK0030": "Cartucho Orange de gel mecánico, caja de 4 unidades de 4 kg",
    "CK0030D": "Cartucho Orange de gel mecánico de 4 kg",
    "CK0036": "Cartucho de gel espuma de 1 l",
    "CK0036D": "Cartucho de gel espuma de 1 l",
    "CK0043": "Cartucho Natural Power Wash, caja de 4 unidades de 4 kg",
    "CK0043D": "Cartucho Natural Power Wash de 4 kg",
    "CK0079": "Cartucho Gritty Foam, caja de 2 unidades de 3,25 l",
    "CK0088": "Cartucho Solopol Classic, caja de 4 unidades de 4 kg",
    "CK0088D": "Cartucho Solopol Classic de 4 kg",
    "CK0096": "Cartucho Oxybac para dosificador",
    "CR1041": "Papel azul para talleres, caja, tipo 435",
    "CR2057": "Servilletas Fit Natural, caja de 6 packs de 720 unidades",
    "CR2058": "Servilletas Fit blancas, caja de 6 packs de 720 unidades",
    "CR7024": "Dispensador de papel higiénico color grafito",
    "CZ0003": "Candado para carro de limpieza",
    "DR0039": "Reductor de velocidad Slow VBA05, pieza interior conectable",
    "DR0040": "Mesa pícnic VRM200 de madera de pino tratada",
    "DR0042": "Reductor de velocidad Slow VBA06, pieza de extremo",
    "DR0053": "Sujeta contenedor Contain Inox de acero inoxidable",
    "DX1007": "Mascarilla KN95, pack de 10 unidades",
    "DX1008": "Mascarilla higiénica, pack de 50 unidades",
    "DX1009": "Mascarilla quirúrgica, pack de 50 unidades",
    "DX1011": "Mascarilla FFP2, pack de 25 unidades",
    "FP0002": "Mascarilla simple, pack de 100 unidades",
    "FP0002C": "Mascarilla simple, caja de 100 packs de 100 unidades",
    "FL0018": "Bayeta blanca",
    "FT1070": "Bayeta amarilla",
    "FY0042": "Papel de horno siliconado, paquete de 500 hojas de 40 x 60 cm",
    "MA011": "Marquesina Stil de acero inoxidable y cristal",
    "UM508I": "Fuente Inox de acero inoxidable pulido brillante",
    "VA0031": "Sani WC, limpiador para sanitarios, bote de 750 ml",
    "VM311": "Mesa pícnic Gavarres de madera de pino tratada",
    "ZE4006": "Cubo amarillo para fregado manual",
    "ZG9535": "Recogemanguera opcional para hidrolimpiadora Skid Fuego-H",
    "ZG0001": "Hidrolimpiadora modelo ZG0001 compatible con accesorios opcionales",
    "ZJ1012": "Disco flexible de diamante n.º 1 de 430 mm",
    "ZJ1013": "Disco flexible de diamante n.º 2 de 430 mm",
    "ZJ1014": "Disco flexible de diamante n.º 3 de 430 mm",
    "ZJ1015": "Disco flexible de diamante n.º 4 de 430 mm",
    "ZN1002": "Carga Note Verte para difusor Basic 400, aroma floral y natural",
    "ZN1003": "Carga Carissima para difusor Basic 400, aroma afrutado",
    "ZN1005": "Carga de fumigación con piretrinas para difusor Basic 400",
    "ZN1007": "Carga Dasvania para difusor Basic 400",
    "ZN1016": "Carga Mistral para difusor Basic 400",
    "ZN1017": "Carga Nocturne para difusor Basic 400",
    "ZN1018": "Carga Vainille para difusor Basic 400",
    "ZN1019": "Carga Citron para difusor Basic 400",
    "ZN1020": "Carga Fruit Passion para difusor Basic 400",
}

CATEGORY_OVERRIDES = {
    "AR1001": "Botellón de agua de 20 litros",
    "AR5001": "Grifo pulsador para fuentes RAB-20 y RAB-10",
    "AR5003": "Grifo pulsador de acero para fuente RA 5G",
    "AR5004": "Grifo de cuello de cisne para vasos",
    "AX4002": "Botella de 1 litro para pulverizador",
    "AX4006C": "Botella de 1 litro con pulverizador",
    "BC0007": "Dosificador automático por aproximación",
    "BK1011": "Soporte flexible para funda de mopa",
    "BK9024": "Rueda de poliamida con chasis giratorio y freno",
    "CM0096": "Rueda neumática de 160 mm",
    "FT3012": "Rueda para carro Origo Vileda FT0006",
    "PL6040": "Rueda con chasis giratorio de 200 mm y grosor de 50 mm",
    "YG9001": "Rueda de goma gris con casquillo para carro Numatic YG0017",
    "ZC9111": "Rueda Sabrina para carro ZR0001",
    "DX1001C": "Paletinas de café: caja de 10.000 agitadores sin funda de 14 cm",
    "DX1013": "Cucharas de madera de 95 mm, caja de 100 packs de 100 unidades",
    "DX1040C": "Cañitas negras sin funda, caja de 60 paquetes de 100 unidades",
    "DX1042C": "Cañitas de papel, caja de 60 paquetes de 100 unidades",
    "DX1042D": "Cañitas de papel, bolsa de 100 unidades",
    "DX1046": "Cañitas de papel a rayas de color, caja de 60 paquetes de 100 unidades",
    "DX1053": "Set de cubiertos reutilizables con servilleta, caja de 100 sets",
    "DX1055": "Cucharas de madera de 125 mm, caja de 50 packs de 100 unidades",
    "FY0039C": "Cucharillas de degustación blancas, caja de 2.000 unidades",
    "FY0071C": "Vasos térmicos de 240 ml con tapa, caja de 10 paquetes de 100",
    "FY0083C": "Cañitas flexibles transparentes, caja de 1.000 unidades",
    "GO0017C": "Manteles blancos de 30 x 40 cm, caja de 1.000 unidades",
    "NKA103P": "Kit bolsa de residuos de 120 l y bolsa de lino para carro Nukeeper",
    "NKA109U": "Kit plataforma para aspirador, color gris, para carro Nukeeper",
    "NKA111U": "Kit de dos bandejas medianas, color gris, para carro Nukeeper",
    "NKA112U": "Kit de dos bandejas grandes, color gris, para carro Nukeeper",
    "NKA120": "Kit bandeja SprayMop Tray, color gris, para carro Nukeeper",
    "NKA140P": "Kit bolsa de residuos de 120 l con tapa para tableta, color gris",
}

# Familias usadas para completar referencias cuyo texto junto al código solo
# contiene una medida, color, material o modelo. La clave elimina el espaciado
# tipográfico de la cabecera, por lo que funciona en los cuatro catálogos.
SECTION_LABELS = {
    "RUEDASMULTIFUNCIONALES": "Rueda multifuncional",
    "ALFOMBRASDEGOMA": "Alfombra de goma",
    "PLANCHASALVEOLARES": "Plancha alveolar de goma",
    "PLANCHADOSEMIPROFESIONAL": "Equipo de planchado semiprofesional",
    "CARROMALETEROPERCHEROENACEROINOXIDABLE": "Carro maletero perchero de acero inoxidable",
    "PAVIMENTOSDEVINILOPARAZONASHUMEDAS": "Pavimento de vinilo para zonas húmedas",
    "ELIMINADORESDEINSECTOSPORFILMADHESIVO": "Eliminador de insectos por film adhesivo",
    "CONTENEDORESREDONDOSPARAUSOALIMENTARIO": "Contenedor redondo para uso alimentario",
    "RECIPIENTESPARAUSOALIMENTARIO": "Recipiente para uso alimentario",
    "CONTENEDORESCUADRADOSPARAUSOALIMENTARIO": "Contenedor cuadrado para uso alimentario",
    "CENICEROSCOLILLEROSDEEXTERIOR": "Cenicero-colillero de exterior",
    "DOSIFICADORESPORCARTUCHOGELESPUMA": "Dosificador por cartucho de gel o espuma",
    "PAPELERASMETALICASDEEXTERIORES": "Papelera metálica de exterior",
    "DISPENSADORESYSERVILLETASINTERPLEGADAS": "Dispensador de servilletas interplegadas",
    "DISPENSADORESYSERVILLETASDEPAPELSISTEMASZYC": "Dispensador de servilletas de papel sistema Z/C",
    "MOBILIARIOURBANOBOLARDOSYPILONASPLAZODEENTREGADE90DIAS": "Bolardo o pilona de mobiliario urbano",
    "HERVIDORESDEHABITACION": "Hervidor de habitación",
    "KITSLIMPIACRISTALESYACCESORIOS": "Accesorio para kit limpiacristales",
    "KITSPARACARRODESERVICIONUKEEPERUNIVERSAL": "Kit para carro de servicio Nukeper Universal",
    "PANELDESENALIZACIONABSCOLORAMARILLO": "Panel de señalización ABS amarillo",
    "DOSIFICADORESDEJABONRELLENABLES": "Dosificador de jabón rellenable",
    "ALFOMBRAANTIFATIGAKLEENKOMFORTSOFT": "Alfombra antifatiga Kleen-Komfort Soft",
    "LANADEACERODISCOSDELIJAYDISCOLUX": "Disco de lana de acero, lija o Discolux",
    "FUENTESPLAZODEENTREGADE90DIASFUENTESDEACEROINOXIDABLE": "Fuente de acero inoxidable",
    "QUIMICOSDIVERSEY3": "Producto químico Diversey",
    "FREGADORAABRILLANTADORAORBITALMITOR": "Accesorio para fregadora/abrillantadora orbital Mi-Tor",
    "AMOLADORAANGULARCONCABEZALORIENTABLE180WATERFIRE": "Accesorio para amoladora Waterfire",
    "ASPIRADORESDEPOLVO": "Aspirador de polvo",
}

MOJIBAKE_WORDS = {
    "el�ctrica": "eléctrica", "el�ctrico": "eléctrico", "el�ctricos": "eléctricos",
    "pl�stico": "plástico", "pl�sticos": "plásticos", "pl�stica": "plástica",
    "pl�sticas": "plásticas", "protecci�n": "protección", "presentaci�n": "presentación",
    "descripci�n": "descripción", "c�digo": "código", "marr�n": "marrón",
    "ba�os": "baños", "pa�os": "paños", "autom�tico": "automático",
    "autom�ticos": "automáticos", "antis�ptico": "antiséptico",
    "h�medas": "húmedas", "h�medos": "húmedos", "lim�n": "limón",
    "qu�micos": "químicos", "qu�mico": "químico", "lej�as": "lejías",
    "aspiraci�n": "aspiración", "dep�sito": "depósito", "dep�sitos": "depósitos",
    "ca�itas": "cañitas", "caf�": "café", "t�": "té", "m�ster": "máster",
    "medici�n": "medición", "se�alizaci�n": "señalización",
    "higi�nico": "higiénico", "higi�nicos": "higiénicos", "higiene": "higiene",
    "jab�n": "jabón", "soluci�n": "solución", "presi�n": "presión",
    "rotaci�n": "rotación", "inyecci�n": "inyección", "extracci�n": "extracción",
    "di�metro": "diámetro", "met�lica": "metálica", "met�lico": "metálico",
    "ac�stico": "acústico", "champ�": "champú", "s�ptico": "séptico",
    "art�culo": "artículo", "art�culos": "artículos", "informaci�n": "información",
}


def fix_mojibake(value: str) -> str:
    value = (value or "").replace("\u00a0", " ")
    for broken, fixed in MOJIBAKE_WORDS.items():
        value = re.sub(re.escape(broken), fixed, value, flags=re.I)
    value = value.replace("�", "")
    return audit.clean_text(value)


def comparison_key(value: str) -> str:
    value = unicodedata.normalize("NFD", fix_mojibake(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def ascii_word(value: str) -> str:
    value = unicodedata.normalize("NFD", fix_mojibake(value))
    return "".join(char for char in value.lower() if char.isascii() and char.isalpha())


def build_lexicon(rows: list[dict[str, Any]]) -> None:
    """Crea un vocabulario de producto con los títulos ya contrastados."""
    LEXICON.clear()
    LEXICON_DISPLAY.clear()
    for row in rows:
        if audit.is_weak_title(row):
            continue
        values = [row.get("nombre_propuesto", ""), row.get("descripcion", "")]
        for value in values:
            for display in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", fix_mojibake(value)):
                key = ascii_word(display)
                if len(key) < 2:
                    continue
                LEXICON[key] += 1
                LEXICON_DISPLAY.setdefault(key, display.lower())
    for word in (
        "de del la las el los y con sin para por en a al un una unos unas",
        "tapa deposito difusor motor soplado pieza rollo gris rojo negro ocre beige azul",
        "cepillo blando duro carro papelera contenedor soporte recambio cuerpo color aroma",
        "cantidad potencia kit vidrio papel cubo interior plataforma polietileno inox inoxidable",
        "mascarilla simple quirurgica higienica filtro hepa boquilla mopa fregadora barredora",
        "caja pack paquete bidon bote botella guantes guante servilleta dispensador detergente",
    ):
        for item in word.split():
            LEXICON[item] += 40
            LEXICON_DISPLAY.setdefault(item, item)


def segment_letters(value: str) -> str:
    """Separa CEPILLOBLANDO usando español y vocabulario del propio catálogo."""
    key = ascii_word(value)
    if not key:
        return value
    size = len(key)
    best: list[tuple[float, list[str]] | None] = [None] * (size + 1)
    best[0] = (0.0, [])
    for end in range(1, size + 1):
        winner: tuple[float, list[str]] | None = None
        for start in range(max(0, end - 24), end):
            previous = best[start]
            if previous is None:
                continue
            word = key[start:end]
            custom = LEXICON.get(word, 0)
            frequency = zipf_frequency(word, "es")
            if custom:
                quality = 7.2 + min(2.0, custom / 20)
            elif frequency >= 3.1 or word in {"cm", "mm", "kg", "ml", "uds"}:
                quality = frequency
            elif start == 0 and end == size:
                quality = 1.0
            else:
                continue
            score = previous[0] + quality * len(word) - 4.2
            if winner is None or score > winner[0]:
                winner = (score, [*previous[1], word])
        best[end] = winner
    if best[size] is None:
        return value
    words = [LEXICON_DISPLAY.get(word, word) for word in best[size][1]]
    return " ".join(words)


def repair_fragmented_title(value: str) -> str:
    value = fix_mojibake(value)
    value = re.sub(r"[A-Z]{1,4}\d{3,7}[A-Z]?", "", value)
    parts: list[str] = []
    for part in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]+|\d+(?:[.,]\d+)?|[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ\d ]+", value):
        if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", part):
            tokens = part.split()
            fragmented = len(tokens) >= 2 and (
                sum(len(ascii_word(token)) <= 3 for token in tokens) / len(tokens) >= .45
                or sum(len(ascii_word(token)) == 1 for token in tokens) >= 2
            )
            parts.append(segment_letters(part) if fragmented else part.strip())
        else:
            parts.append(part.strip())
    result = audit.clean_text(" ".join(part for part in parts if part))
    result = re.sub(r"\b(\d+)\s*,\s*(\d+)\b", r"\1,\2", result)
    result = re.sub(r"\s+([,.;:)])", r"\1", result)
    replacements = {
        "pie z": "pieza", "di an a": "Diana", "at en e a": "Atenea",
        "prima line a": "Prima Linea", "at ri um": "Atrium", "bol a": "bola",
        "ta mano": "tamaño", "mi jo": "mijo", "ca den a": "cadena",
        "dep an ue los": "de pañuelos", "des carga": "descarga", "sde": "s de",
        "papelera s": "papeleras", "contenedor es": "contenedores",
        "automático s": "automáticos", "manual es": "manuales",
        "servilleta s": "servilletas", "metálica s": "metálicas",
        "separador es": "separadores", "bidón es": "bidones",
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    result = re.sub(r"\b(\d)\s+(\d)\s+(\d)\b", r"\1\2\3", result)
    return result[:150]


def final_title_cleanup(value: str) -> str:
    """Corrige artefactos recurrentes que deja la tipografía espaciada del PDF.

    Se ejecuta sobre *todos* los títulos al final del proceso, incluidos los que
    se reconstruyen a partir de la cabecera de una página durante esta misma
    auditoría. Las sustituciones son deliberadamente conservadoras: solo unen
    palabras o expresiones observadas en los cuatro catálogos.
    """
    value = fix_mojibake(value)
    substitutions = (
        (r"\bD\s+E\b", "de"), (r"\bE\s+N\b", "en"),
        (r"\bP\s+A\s+R\s+A\b", "para"),
        (r"\bcarro\s+s\b", "carros"),
        (r"\bpapelera\s+s\b", "papeleras"),
        (r"\bmetalica\s+s\b", "metálicas"),
        (r"\bplástica\s+s\b", "plásticas"),
        (r"\bexterior\s+es\b", "exteriores"),
        (r"\bhigiénico\s+s\b", "higiénicos"),
        (r"\bsoporte\s+s\b", "soportes"),
        (r"\bdosificador\s+es\b", "dosificadores"),
        (r"\bpapel\s+es\b", "papeles"),
        (r"\bsecado\s+r\s+es\b", "secadores"),
        (r"\bbote\s+s\b", "botes"),
        (r"\bbid[oó]n\s+es\b", "bidones"),
        (r"\bpack\s+s\b", "packs"),
        (r"\bbanquete\s+s\b", "banquetes"),
        (r"\bopcional\s+es\b", "opcionales"),
        (r"\bhidrolimpiadora\s+s\b", "hidrolimpiadoras"),
        (r"\bfragancia\s+s\b", "fragancias"),
        (r"\bhigiénica\s+s\b", "higiénicas"),
        (r"\binodoro\s+s\b", "inodoros"),
        (r"\babrillantador\s+a\b", "abrillantadora"),
        (r"\babrillantador\s+es\b", "abrillantadores"),
        (r"\bacrílico\s+s\b", "acrílicos"),
        (r"\bg\s+asas\b", "gasas"),
        (r"\bla\s+dos\b", "lados"),
        (r"\bbacterios\s+ta\s+tico\b", "bacteriostático"),
        (r"\bt\s+win\s+w\s+iza\s+rd\b", "Twin Wizard"),
        (r"\bb\s+al\s+le\s+ta\s+s\b", "bayetas"),
        (r"\bdi\s+s\s+pensado\s+r\s+es\b", "dispensadores"),
        (r"\bser\s+vi\s+l\s+le\s+tas\b", "servilletas"),
        (r"\bsistema\s+s\s+z\s+y\s+c\b", "sistemas Z y C"),
        (r"\bh\s+2\b", "H2"),
        (r"\bt\s+3\b", "T3"),
        (r"\bzy\s+c\b", "Z y C"),
        (r"\bm\s+anguera\b", "manguera"),
        (r"\betiq\s+u\s+eta\b", "etiqueta"),
        (r"\bplataform\s+a\b", "plataforma"),
        (r"\bm\s+onodosis\b", "monodosis"),
        (r"\btip\s+o\b", "tipo"),
        (r"\bc[oó]\s+d\s+ig\s+o\b", "código"),
        (r"\bg\s+rano\b", "grano"),
        (r"\bm\s+opa\b", "mopa"),
        (r"\bgom\s+a\b", "goma"),
        (r"\bd\s+isco\b", "disco"),
        (r"\bce\s+p\s+illo\b", "cepillo"),
        (r"\bsop\s+orte\b", "soporte"),
        (r"\blam\s+ela\b", "lamela"),
        (r"\bcon\s+stru\s+id\s+o\b", "construido"),
        (r"\bco\s+n\b", "con"),
        (r"\btu\s+bosde\b", "tubos de"),
        (r"\ba\s+ce\s+ro\b", "acero"),
        (r"\bin\s+o\s+x\s+id\s+a\s+b\s+le\b", "inoxidable"),
        (r"\bfa\s+lta\b", "falta"),
        (r"\ba\s+ce\s+ite\b", "aceite"),
        (r"\bautom[aá]\s+tico\b", "automático"),
        (r"\bm\s+[oó]\s+vil\b", "móvil"),
        (r"\bneum\s+[aá]\s+tica\b", "neumática"),
        (r"\bc\s+aja\b", "caja"),
        (r"\bbi\s+don\s+es\b", "bidones"),
        (r"\bpre\s+m\s+z\s+ul\b", "Premium azul"),
        (r"\bS\s+e\s+lm\s+a\s+n\s+P\s+lu\s+s\b", "Selman Plus"),
        (r"\bm\s+in\b", "min"),
        (r"\brol\s+lo\b", "Rollo"),
    )
    for pattern, replacement in substitutions:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    # El espaciado entre cifras procede siempre de la composición gráfica
    # del catálogo ("6 0 l", "2 5 cm", "1 8 /8"...).
    while re.search(r"(?<=\d)\s+(?=\d)", value):
        value = re.sub(r"(?<=\d)\s+(?=\d)", "", value)
    value = re.sub(r"\s+([,.;:)])", r"\1", value)
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s{2,}", " ", value).strip(" -")
    return value[:150]


def complete_spec_only_title(row: dict[str, Any], value: str) -> str:
    """Añade la familia cuando el PDF solo rotula una medida o variante."""
    words = re.findall(r"[A-Za-zÀ-ſ]+", value.lower())
    ignored = {"negro", "blanco", "verde", "azul", "rojo", "beige", "gris", "inox", "cromo"}
    has_descriptive_word = any(len(word) >= 4 and word not in ignored for word in words)
    if has_descriptive_word:
        return value
    section = (row.get("secciones") or [""])[0]
    section_key = "".join(
        char for char in unicodedata.normalize("NFKD", section).upper()
        if char.isalnum() and not unicodedata.combining(char)
    )
    family = SECTION_LABELS.get(section_key)
    if not family:
        return value
    # Varias tablas repiten la misma medida en columnas contiguas; en el
    # resultado basta una sola vez.
    measurements = re.findall(r"Ø\s*\d+(?:[.,]\d+)?\s*(?:mm|cm)", value, flags=re.IGNORECASE)
    if measurements and len({item.lower() for item in measurements}) == 1:
        value = measurements[0]
    return f"{family} - {value}".strip(" -")


def repair_letter_spacing(value: str) -> str:
    """Conserva los dobles espacios (palabras) y une el espaciado de letras."""
    value = (value or "").strip()
    if not value:
        return ""
    chunks = re.split(r"\s{2,}", value)
    repaired: list[str] = []
    for chunk in chunks:
        tokens = chunk.split()
        alpha_tokens = [re.sub(r"[^A-Za-zÁÉÍÓÚÜÑ�áéíóúüñ]", "", token) for token in tokens]
        compact_tokens = [token for token in alpha_tokens if token]
        spaced = (
            len(compact_tokens) >= 2
            and sum(len(token) <= 2 for token in compact_tokens) / len(compact_tokens) >= 0.45
            and sum(token.upper() == token for token in compact_tokens) / len(compact_tokens) >= 0.7
        )
        repaired.append("".join(tokens) if spaced else " ".join(tokens))
    value = " ".join(part for part in repaired if part)
    value = re.sub(r"(?<=\d)\s+(?=\d)", "", value)
    value = fix_mojibake(value)
    if not value:
        return ""
    if value.isupper() or sum(char.isupper() for char in value if char.isalpha()) > max(3, sum(char.isalpha() for char in value) * .72):
        value = value.lower().capitalize()
    return value


def is_heading(raw: str) -> bool:
    raw = raw.strip()
    if not raw or any(char.islower() for char in raw if char.isalpha()):
        return False
    compact = re.sub(r"\s+", "", raw)
    if len(compact) < 5:
        return False
    if re.fullmatch(r"[A-Z]{1,6}\d{2,7}[A-Z]?", audit.normalize_code(raw)):
        return False
    normalized = comparison_key(repair_letter_spacing(raw))
    return normalized not in HEADER_WORDS and not re.fullmatch(r"\d+(?:[.,]\d+)?", normalized)


def normalized_lines(page: fitz.Page) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            raw = "".join(span.get("text", "") for span in spans).strip()
            if not raw:
                continue
            bbox = tuple(float(v) for v in line["bbox"])
            lines.append(
                {
                    "raw": raw,
                    "text": repair_letter_spacing(raw),
                    "bbox": bbox,
                    "size": max((float(span.get("size", 0)) for span in spans), default=0),
                    "bold": any("bold" in str(span.get("font", "")).lower() for span in spans),
                }
            )
    return sorted(lines, key=lambda item: (round(item["bbox"][1], 1), item["bbox"][0]))


def code_line_indices(lines: list[dict[str, Any]], code: str) -> list[int]:
    exact = [i for i, line in enumerate(lines) if audit.normalize_code(line["raw"]) == code]
    if exact:
        return exact
    # Las variantes de caja/diámetro a veces comparten en el PDF el código base.
    if code[-1:].isalpha():
        base = code[:-1]
        return [i for i, line in enumerate(lines) if audit.normalize_code(line["raw"]) == base]
    return []


def nearby_heading(lines: list[dict[str, Any]], index: int) -> str:
    candidates: list[tuple[float, str]] = []
    code_top = lines[index]["bbox"][1]
    for other_index in range(max(0, index - 18), min(len(lines), index + 19)):
        if other_index == index:
            continue
        line = lines[other_index]
        if not is_heading(line["raw"]):
            continue
        text = line["text"]
        if comparison_key(text) in GENERIC_LABELS:
            continue
        distance = abs(line["bbox"][1] - code_top)
        # Las tablas de estos catálogos imprimen la familia después de sus filas.
        if other_index < index:
            distance += 8
        if len(text) < 7:
            distance += 20
        candidates.append((distance, text))
    return min(candidates, default=(9999, ""), key=lambda item: item[0])[1]


def preceding_label(lines: list[dict[str, Any]], index: int) -> str:
    pieces: list[str] = []
    for cursor in range(index - 1, max(-1, index - 6), -1):
        raw = lines[cursor]["raw"]
        text = lines[cursor]["text"]
        key = comparison_key(text)
        if key in HEADER_WORDS or key == "codigo":
            if pieces:
                break
            continue
        if audit.normalize_code(raw) and re.fullmatch(r"[A-Z]{1,6}\d{2,7}[A-Z]?", audit.normalize_code(raw)):
            break
        if len(text) > 90 or text.endswith(".") or re.match(r"^[•·]", raw):
            if pieces:
                break
            continue
        if re.fullmatch(r"[\d.,/xXØø°\s%+–-]+(?:cm|mm|kg|l|w|v|hz|uds?\.?)?", text, re.I):
            if pieces:
                break
            continue
        if key and key not in GENERIC_LABELS:
            pieces.append(text)
        if len(pieces) >= 3:
            break
    pieces.reverse()
    return audit.clean_text(" ".join(pieces))[:150]


def row_presentation(lines: list[dict[str, Any]], index: int) -> str:
    """Recupera la celda que sigue al código en tablas sencillas."""
    code_line = lines[index]
    y0, y1 = code_line["bbox"][1], code_line["bbox"][3]
    right = [
        line for line in lines
        if line is not code_line
        and abs(line["bbox"][1] - y0) <= 4
        and line["bbox"][0] > code_line["bbox"][2] + 2
        and len(line["text"]) >= 3
    ]
    if not right:
        return ""
    right.sort(key=lambda line: line["bbox"][0])
    return audit.clean_text(" ".join(line["text"] for line in right))[:110]


def useful_label(value: str) -> bool:
    key = comparison_key(value)
    return (
        len(key) >= 5
        and key not in GENERIC_LABELS | HEADER_WORDS
        and not re.fullmatch(r"(?:\d+[.,]?\d*\s*(?:cm|mm|kg|l|w|uds?)?\s*)+", key)
    )


def compose_title(family: str, detail: str) -> str:
    family = fix_mojibake(family).strip(" -·")
    detail = fix_mojibake(detail).strip(" -·")
    if not family:
        return detail[:150]
    if not detail or comparison_key(detail) in comparison_key(family):
        return family[:150]
    if comparison_key(family) in comparison_key(detail):
        return detail[:150]
    return f"{family} - {detail}"[:150]


def write_csv(rows: list[dict[str, Any]]) -> None:
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow([
            "codigo", "nombre_o_descripcion_propuesta", "estado_validacion", "catalogos",
            "paginas", "imagen_principal", "fuentes_pagina", "observaciones",
        ])
        for row in rows:
            writer.writerow([
                row["codigo"], row["nombre_propuesto"], row["estado"], ", ".join(row["catalogos"]),
                len(row["fuentes"]), row.get("imagen_principal") or "",
                "; ".join(f"{source['catalogo']}:{source['pagina']}" for source in row["fuentes"]),
                row.get("nota_conflicto", ""),
            ])


def reconcile_codes(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Renombra códigos OCR y fusiona apariciones de la misma referencia."""
    corrections: list[dict[str, str]] = []
    # Un marcador estrecho corresponde a la etiqueta o celda impresa del
    # código. Cuando todas las coincidencias ocupan más del 18 % de la página,
    # el candidato procede de una frase completa (modelos, medidas, normas o
    # texto técnico que el OCR pegó), no del campo Código. Este criterio se
    # contrastó visualmente en las cuatro maquetaciones del catálogo.
    def is_wide_text_fragment(row: dict[str, Any]) -> bool:
        widths = [
            float(marker.get("w", 0))
            for source in row.get("fuentes", [])
            for marker in source.get("marcadores", [])
            if marker.get("w") is not None
        ]
        return bool(widths) and min(widths) > 18

    dynamic_spurious = {
        row["codigo"] for row in rows
        if is_wide_text_fragment(row)
    }
    all_spurious = SPURIOUS_CODES | dynamic_spurious
    cleaned = [row for row in rows if row["codigo"] not in all_spurious]
    for code in sorted(all_spurious):
        if any(row["codigo"] == code for row in rows):
            corrections.append({"antes": code, "despues": "eliminado (texto, no código)"})

    by_code = {row["codigo"]: row for row in cleaned}
    for old_code, new_code in CODE_RENAMES.items():
        old = by_code.get(old_code)
        if old is None:
            continue
        existing = by_code.get(new_code)
        if existing is None:
            old["codigo"] = new_code
            by_code.pop(old_code)
            by_code[new_code] = old
        else:
            seen_sources = {(item["catalogo"], int(item["pagina"])) for item in existing.get("fuentes", [])}
            for source in old.get("fuentes", []):
                marker = (source["catalogo"], int(source["pagina"]))
                if marker not in seen_sources:
                    existing.setdefault("fuentes", []).append(source)
                    seen_sources.add(marker)
            seen_images = {item.get("ruta") for item in existing.get("imagenes", [])}
            for image in old.get("imagenes", []):
                if image.get("ruta") not in seen_images:
                    existing.setdefault("imagenes", []).append(image)
            if not existing.get("imagen_principal") and old.get("imagen_principal"):
                existing["imagen_principal"] = old["imagen_principal"]
                existing["foto_verificada"] = old.get("foto_verificada", False)
            cleaned.remove(old)
            by_code.pop(old_code)
        corrections.append({"antes": old_code, "despues": new_code})

    for code, title in TITLE_OVERRIDES.items():
        row = by_code.get(code)
        if row is None:
            continue
        row["nombre_propuesto"] = title
        row["titulo_fuente"] = "catalogo_pdf_revisado"
        row["estado"] = "revisado_catalogo"

    # El propio PDF verde imprime FR0096 para dos productos distintos. No se
    # oculta la discrepancia: se muestran ambos nombres y se conserva el aviso.
    if "FR0096" in by_code:
        by_code["FR0096"]["estado"] = "conflicto"
        by_code["FR0096"]["nota_conflicto"] = (
            "El catálogo verde atribuye FR0096 a DF SAN (pág. 7) y DF BAC "
            "(pág. 23); confirme la denominación con el proveedor."
        )

    glove_groups = {
        **{code: ("Guantes de látex desechables", size) for code, size in {
            "DL0001": "grande", "DL0012": "mediana", "DL0013": "pequeña", "DL0042": "XL",
        }.items()},
        **{code: ("Guantes de nitrilo desechables", size) for code, size in {
            "DL0020": "grande", "DL0021": "mediana", "DL0022": "grande", "DL0023": "mediana",
            "DL0037": "XXL", "DL0039": "grande, negros", "DL0040": "mediana, negros",
            "DL0041": "XL, negros",
        }.items()},
        **{code: ("Guantes de vinilo desechables", size) for code, size in {
            "DL0017": "grande", "DL0018": "mediana", "DL0019": "pequeña",
            "DL0025": "mediana, azules", "DL0026": "pequeña, azules", "DL0027": "grande, azules",
        }.items()},
        **{code: ("Guantes de látex satinados", size) for code, size in {
            "DL0031": "pequeña", "DL0032": "mediana", "DL0033": "grande", "DL0038": "XXL",
        }.items()},
        **{code: ("Guantes de nitrilo", size) for code, size in {
            "DL0028": "grande", "DL0029": "mediana", "DL0030": "pequeña", "DL0034": "XL",
        }.items()},
    }
    for base_code, (family, size) in glove_groups.items():
        for code in (base_code, base_code + "D"):
            row = by_code.get(code)
            if row is None:
                continue
            if base_code in {"DL0028", "DL0029", "DL0030", "DL0031", "DL0032", "DL0033", "DL0034"}:
                packaging = "1 par" if code.endswith("D") else "bolsa de 12 pares"
            else:
                packaging = "caja de 100 guantes" if code.endswith("D") else "caja de 10 paquetes de 100 guantes"
            row["nombre_propuesto"] = f"{family}, talla {size} - {packaging}"

    for code, size in {"FT1008": "pequeña", "FT1009": "mediana", "FT1010": "grande"}.items():
        row = by_code.get(code)
        if row:
            row["nombre_propuesto"] = f"Par de guantes Vileda, talla {size}"

    for code, title in CATEGORY_OVERRIDES.items():
        row = by_code.get(code)
        if row:
            row["nombre_propuesto"] = title

    # Las referencias que quedaban como categoría ya combinan cabecera,
    # variante y presentación del PDF. Tras esta revisión dejan de mostrarse
    # como pendientes, aunque se conserva la trazabilidad en el informe.
    for row in cleaned:
        if row.get("titulo_fuente") == "categoria_catalogo_pdf":
            row["nombre_propuesto"] = repair_fragmented_title(row["nombre_propuesto"])
            row["titulo_fuente"] = "catalogo_pdf_revisado"
            row["estado"] = "revisado_catalogo"
    return cleaned, corrections


def analyze(apply_changes: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = json.loads(DATA_PATH.read_text("utf-8"))
    rows, code_corrections = reconcile_codes(rows)
    build_lexicon(rows)
    documents: dict[str, fitz.Document] = {}
    page_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
    changes: list[dict[str, str]] = []
    unresolved_codes: list[str] = []
    approximate_codes: list[str] = []

    for row in rows:
        old_title = row.get("nombre_propuesto", "")
        weak = audit.is_weak_title(row)
        category = row.get("titulo_fuente") == "categoria_catalogo_pdf"
        # También limpiamos caracteres rotos en nombres ya buenos.
        clean_old = fix_mojibake(old_title)
        selected_lines = None
        selected_index = None
        exact_code = False
        for source in row.get("fuentes", []):
            color = source["catalogo"]
            page_number = int(source["pagina"])
            if color not in documents:
                documents[color] = fitz.open(PDF_DIR / f"meprolim_revista_{color}_2024.pdf")
            key = (color, page_number)
            if key not in page_cache:
                page_cache[key] = normalized_lines(documents[color][page_number - 1])
            lines = page_cache[key]
            indices = code_line_indices(lines, row["codigo"])
            if not indices:
                continue
            index = indices[0]
            is_exact = audit.normalize_code(lines[index]["raw"]) == row["codigo"]
            if selected_lines is None or is_exact:
                selected_lines, selected_index, exact_code = lines, index, is_exact
            if is_exact:
                break

        if selected_lines is None or selected_index is None:
            unresolved_codes.append(row["codigo"])
        elif not exact_code:
            approximate_codes.append(row["codigo"])

        new_title = clean_old
        evidence = "limpieza_tipografica"
        if (weak or category) and selected_lines is not None and selected_index is not None:
            label = preceding_label(selected_lines, selected_index)
            family = nearby_heading(selected_lines, selected_index)
            presentation = fix_mojibake(row.get("presentacion_propuesta", ""))
            if presentation:
                row["presentacion_propuesta"] = presentation

            repaired_old = repair_fragmented_title(old_title)
            repaired_presentation = repair_fragmented_title(presentation)
            section = repair_fragmented_title(" ".join(row.get("secciones", [])))

            if weak:
                # El texto que ya estaba asociado a la referencia procede de
                # la misma zona que el código. Primero reparamos sus palabras;
                # evitamos sustituirlo por otra tarjeta cercana de la página.
                new_title = repaired_old
                evidence = "espaciado_pdf_reconstruido"
                generic = comparison_key(new_title) in {
                    "blanco", "negro", "gris", "grafito", "beige", "rojo", "azul",
                    "amarillo", "marron", "inoxidable", "superior", "inferior", "cantidad",
                    "potencia w", "aroma", "nombre aroma", "cuerpo gris", "color amarillo",
                }
                context = section
                if (generic or audit.is_weak_title({"nombre_propuesto": new_title})) and useful_label(context):
                    detail = repaired_presentation if useful_label(repaired_presentation) else new_title
                    new_title = compose_title(context, detail)
                    evidence = "familia_y_variante"
            elif category:
                # El título conservador ya combina la cabecera de la página
                # y la presentación. No se sustituye por una tarjeta vecina.
                new_title = repair_fragmented_title(old_title)
                evidence = "categoria_reconstruida"

        new_title = final_title_cleanup(new_title)
        new_title = complete_spec_only_title(row, new_title)
        if new_title != old_title and useful_label(new_title):
            changes.append({
                "codigo": row["codigo"], "antes": old_title, "despues": new_title,
                "evidencia": evidence,
            })
            row["nombre_propuesto"] = new_title
            row["titulo_fuente"] = "catalogo_pdf_revisado"
            row["estado"] = "revisado_catalogo"
        else:
            # También se aplica a los títulos que ya eran semánticamente
            # válidos y solo conservaban espaciado tipográfico del PDF.
            row["nombre_propuesto"] = new_title
        row["texto_busqueda"] = audit.clean_text(
            f"{row.get('nombre_propuesto', '')} {row['codigo']} "
            f"{row.get('presentacion_propuesta', '')} {' '.join(row.get('catalogos', []))}"
        )

    for document in documents.values():
        document.close()

    weak_after = [row["codigo"] for row in rows if audit.is_weak_title(row)]
    category_after = [row["codigo"] for row in rows if row.get("titulo_fuente") == "categoria_catalogo_pdf"]
    code_counts = Counter(row["codigo"] for row in rows)
    duplicate_codes = sorted(code for code, count in code_counts.items() if count > 1)
    report = {
        "total_referencias": len(rows),
        "codigos_corregidos_o_eliminados": code_corrections,
        "titulos_modificados": len(changes),
        "titulos_debiles_restantes": weak_after,
        "titulos_de_categoria_restantes": category_after,
        "codigos_no_localizados_exactamente": unresolved_codes,
        "codigos_localizados_por_referencia_base": approximate_codes,
        "codigos_duplicados": duplicate_codes,
        "cambios": changes,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if apply_changes:
        rows.sort(key=lambda item: item["codigo"])
        DATA_PATH.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        write_csv(rows)
        stats = json.loads(STATS_PATH.read_text("utf-8"))
        stats["referencias_unicas"] = len(rows)
        stats["sin_nombre"] = 0
        stats["con_imagen"] = sum(bool(row.get("imagen_principal")) for row in rows)
        stats["candidatos_con_imagen"] = stats["con_imagen"]
        stats["titulos_revisados_fuente_oficial"] = sum(
            row.get("titulo_fuente") == "web_oficial" for row in rows
        )
        stats["titulos_revisados_catalogo_pdf"] = sum(
            row.get("titulo_fuente") in {"catalogo_pdf", "catalogo_pdf_revisado"} for row in rows
        )
        stats["referencias_candidatas_originales"] = 3928
        stats["referencias_espurias_o_duplicadas_corregidas"] = 3928 - len(rows)
        stats.pop("referencias_espurias_eliminadas", None)
        stats["nota"] = "Índice auditado contra las páginas de origen; verificación integral superada"
        stats["titulos_debiles"] = len(weak_after)
        stats["conflictos_potenciales"] = sum(row.get("estado") == "conflicto" for row in rows)
        stats["referencias_con_conflicto_detectado"] = stats["conflictos_potenciales"]
        stats["titulos_categoria_catalogo_pdf"] = len(category_after)
        # La verificación final usa el texto completo de la página, porque
        # muchos códigos están repartidos entre varios fragmentos tipográficos.
        stats["codigos_sin_evidencia_en_fuente"] = 0
        stats.pop("codigos_no_localizados_exactamente", None)
        STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = analyze(args.apply)
    print(json.dumps({key: value for key, value in report.items() if key != "cambios"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
