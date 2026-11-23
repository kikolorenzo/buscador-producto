#!/usr/bin/env python3
"""Completa y valida la información visible de todas las referencias.

El código impreso en los PDF es la identidad histórica del artículo. La web
oficial se usa cuando el SKU coincide o cuando nombre y contexto son
compatibles; algunos códigos han sido reutilizados y no se pueden cruzar a
ciegas. Las fichas incompatibles tampoco aportan descripción ni fotografía.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import unicodedata
from collections import Counter
from typing import Any

import fitz

import audit_catalog_quality as audit
import repair_all_catalog_names as repair


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "articulos.json"
CSV = ROOT / "data" / "articulos.csv"
STATS = ROOT / "data" / "estadisticas.json"
PDF_DIR = ROOT / "tmp" / "pdfs"
OFFICIAL = PDF_DIR / "official-products-problematic.json"
REPORT = PDF_DIR / "complete-product-data-report.json"

STOPWORDS = {
    "de", "del", "la", "las", "el", "los", "y", "con", "sin", "para",
    "por", "en", "a", "al", "un", "una", "unos", "unas", "o", "codigo",
    "código", "caja", "pack", "ud", "uds", "unidad", "unidades",
}
PRODUCT_WORDS = set(audit.PRODUCT_TITLE_TERMS) | {
    "abrillantadora", "agitador", "alfombra", "almohadilla", "armario",
    "banco", "bandera", "barra", "barredora", "base", "bayeta", "bolsa",
    "boquilla", "bote", "botella", "carretilla", "cartucho", "cesta",
    "cinturón", "colillero", "cordón", "cristalizadora", "cuchara", "depósito",
    "escalera", "escoba", "espátula", "estropajo", "fuente", "gamuzas",
    "guantes", "haragán", "hidrolimpiadora", "lámpara", "lavamanos",
    "lavamoquetas", "limpiacristales", "mango", "mascarilla", "mesa", "mopa",
    "pastilla", "papel", "papelera", "paño", "pedal", "percha", "pistola",
    "plataforma", "plumero", "pulidora", "rascador", "recogedor", "rueda",
    "secador", "secamanos", "silla", "tapa",
}
GENERIC_TITLES = {
    "meprolim", "accesorios", "accesorios opcionales", "recambios", "soporte",
    "cubeta", "protector", "cromado", "cantidad", "potencia w",
    "solicite presupuesto", "circular", "recambio", "profesional",
    "datos técnicos", "film adhesivo", "carga dinámica", "motor (tipo/cc)",
    "doble acción", "pulsador", "basculante", "transparente", "polietileno",
    "polipropileno", "metálica", "metálico", "aluminio", "acero inox",
}
ACRONYMS = {
    "abs": "ABS", "appcc": "APPCC", "df": "DF", "inox": "INOX",
    "pva": "PVA", "pvc": "PVC", "qs": "QS", "spp": "SPP", "uv": "UV",
    "wc": "WC", "vileda": "Vileda", "tork": "Tork", "ecomix": "Ecomix",
    "w": "W", "v": "V",
}

# Códigos cuyo significado actual en la web difiere del producto que aparece
# en estos PDF. Se conservaron tras contrastar nombre, página y fotografía.
PRESERVE_CATALOG_CODES = {
    "BC1008", "BX1064", "BX3032", "BX4009", "BX4015", "BX9010",
    "DZ0008", "FR0029", "FR0104", "FR0124", "FS0030", "ZB1016", "ZG0013",
}

# Modelos de máquinas que el extractor inicial confundió con referencias al
# encontrarlos dentro de la descripción de baterías/cargadores. En la tabla
# de la página 84 del catálogo rojo los códigos de venta son CW1007, CW1015,
# ZD9339 y YG2002, no estos nombres de modelo.
SPURIOUS_MODEL_CODES = {
    "CB130", "CS120", "CS700", "CS700B", "CS700H", "NBV190", "NBV190N",
    # Fragmentos de frases como «de 100 m/l» o «de 200 mm» que cumplen por
    # casualidad el patrón alfanumérico de un SKU.
    "DE100", "DE100L", "DE100M", "DE200",
    # Nombres de modelo impresos junto a un código de venta diferente.
    "AL0033C", "AL0035C", "AL0036C", "UM1100M", "UM1100P",
    "AUM1640", "AUM320", "AUM374", "NUM379M", "OCH292", "SUM340",
    "UUM396H", "YUM392B", "CR2055Y",
    "BK0149Y", "BK0186Y", "YBK0250", "DE405", "DE750", "DE800",
    # Nombres de modelo, normas técnicas y frases de apoyo que aparecen en
    # la misma página que el código comercial real.
    "CM4050", "CS120B", "CS120D", "CT400", "DAC120", "DE120L",
    "ELO110", "ELO915", "GER250G", "GER500G", "LES120L", "MOD100",
    "PRO1500", "PRO3000", "RSV130", "SM1705", "UFO290V",
    "EN1082", "EN12477", "EN374", "EN381", "EN388", "EN407", "EN421",
    "EN511", "EN659", "BC1012Y", "AZG0013", "AZG0014", "SUM511",
    "AL0018Y", "AL0025Y", "AL0089Y", "AL7000Y", "BK0026Y",
    "BK0221Y", "FT0004Y", "ZE1006Y",
}

CODE_RENAMES = {
    "BX6108M": "BX6108", "BX6109M": "BX6109", "BX6110M": "BX6110",
    "BX6111M": "BX6111", "BX6112M": "BX6112", "BX6116M": "BX6116",
    "BX6123N": "BX6123", "BX6124N": "BX6124", "BX6125N": "BX6125",
    "BX6126N": "BX6126", "BX6127N": "BX6127",
    "CK0054U": "CK0054", "CK0063C": "CK0063", "CK0062H": "CK0062",
}

SPLIT_REPLACEMENTS = (
    (r"\bAm\s+arillo\b", "amarillo"), (r"\bA\s+zul\b", "azul"),
    (r"\bG\s+ris\b", "gris"), (r"\bR\s+ojo\b", "rojo"),
    (r"\bN\s+egro\b", "negro"), (r"\bB\s+lanco\b", "blanco"),
    (r"\bV\s+erde\b", "verde"), (r"\bm\s+l\b", "ml"),
    (r"\bm\s+m\b", "mm"), (r"\bm\s+2\b", "m²"), (r"\bm\s+3\b", "m³"),
    (r"\bC\s+EP\s+ILLO\b", "cepillo"), (r"\bP\s+LATO\b", "plato"),
    (r"\bDEGOMA\b", "de goma"), (r"\bD\s+EP[ÓO]\s+SITO\b", "depósito"),
    (r"\bAG\s+UA\b", "agua"), (r"\bYCHAMP[ÚU]\b", "y champú"),
    (r"\bP\s+ISTO\s+LA\b", "pistola"), (r"\bP\s+LA\s+NCHA\b", "plancha"),
    (r"\bREC\s+IC\s+LADO\b", "reciclado"), (r"\bC\s+IR\s+CULAR\b", "circular"),
    (r"\bC\s+IB\s+ELES\b", "Cibeles"), (r"\bSCUDER\s+IA\b", "Scuderia"),
    (r"\bRECAMB\s+IO\b", "recambio"), (r"\bSkrap+p?\s+er\b", "Skraper"),
    (r"\bC\s+aja\b", "Caja"), (r"\bG\s+R(\d+)\b", r"GR\1"),
    (r"\bmonodosis\s+(\d+)\s+m\s*l\b", r"monodosis de \1 ml"),
    (r"\bonodosis\s+(\d+)\s+m\s*l\b", r"monodosis de \1 ml"),
    (r"\bC\s*[ÓO]\s*D\.?\b", ""), (r"\bD\s+ESC\s+RIPC\s+I[ÓO]\s+N\b", ""),
    (r"\bCAPAC\s+ID\s+AD\b", "capacidad"), (r"\bG\s+rano\b", "grano"),
    (r"\bsegm\s+entos\b", "segmentos"), (r"\bb\s+olsas\b", "bolsas"),
    (r"\bU\s+nidad(?:es)?\b", "unidades"), (r"\bPrem\s+ium\b", "Premium"),
    (r"\bJab\s+[óo]n\b", "Jabón"), (r"\bC\s+artucho\b", "cartucho"),
    (r"\bcon\s+tenedor(?:es)?\b", "contenedor"),
    (r"\balfombra\s+s\b", "alfombras"), (r"\brizo\s+s\b", "rizos"),
    (r"\bselectiva\s+s\b", "selectivas"), (r"\bpalet\s+s\b", "palets"),
    (r"\bl[ií]quido\s+s\b", "líquidos"), (r"\bindustrial\s+es\b", "industriales"),
    (r"\baspirador\s+a\s+s\b", "aspiradoras"),
    (r"\bm\s+[óo]\s+vil\b", "móvil"), (r"\bneum\s+[aá]\s+tica\b", "neumática"),
    (r"\bem\s+p\s+otra\s+r\b", "empotrar"), (r"\bEcom\s+ix\b", "Ecomix"),
    (r"\bXtrem\s+pure\s+m\s+ultinet\b", "Xtrem Pure Multinet"),
    (r"\bC\s+argador\b", "Cargador"), (r"\bcom\s+pleto\b", "completo"),
    (r"\bG\s+atillo\b", "Gatillo"), (r"\bb\s+oquilla\b", "boquilla"),
    (r"\bD\s+isco\b", "Disco"), (r"\bm\s+et[aá]lico\b", "metálico"),
    (r"\bM\s+edida\b", "Medida"), (r"\bH\s+ardner\b", "Hardner"),
    (r"\blo\s+n\s+gran\s+ge\b", "Long Range"),
    (r"\bpresi[oó]\b", "presión"), (r"\bb\s+en\s+zc\b", "Benz C"),
    (r"\bC\s+EN\s+TRAL\b", "central"), (r"\bTub\s+o\b", "tubo"),
    (r"\bcom\s+binada\b", "combinada"), (r"\bD\s+U\s+LEVO\b", "Dulevo"),
    (r"\bM\s+ED\s+IA\b", "Media"), (r"\bespum\s+a\b", "espuma"),
    (r"\bbi\s+donde\b", "bidón de"), (r"\blitro\s+s\b", "litros"),
    (r"\bin\s+dustr\s+ia\s+l\b", "industrial"),
    (r"\bm\s+[áa]\s+quinas\b", "máquinas"), (r"\bEsf[eé]r\s+ic\s+a\b", "Esférica"),
    (r"\bpar\s+k\s+in\b", "Parking"), (r"\bRec\s+ta\s+ngular\b", "Rectangular"),
    (r"\bextr\s+em\s+o\b", "extremo"), (r"\bbater\s*[íi]\s+a\b", "batería"),
    (r"\bAmar\s+il\s+lo\b", "amarillo"), (r"\bPl[aá]st\s+ico\b", "plástico"),
    (r"\bb\s+otes\b", "botes"), (r"\bH\s+arag[aá]n\b", "Haragán"),
    (r"\bb\s+otellas\b", "botellas"), (r"\bsecado\s+ra\b", "secadora"),
    (r"\bPROF\s+ESIO\s+NAL\b", "profesional"), (r"\bmi\s*-\s*to\s+r\b", "Mi-Tor"),
    (r"\bta\s+xxi\b", "Delta XXI"), (r"\bdel\s+ta\b", "Delta"),
    (r"\bAja\b", "Caja"), (r"^aja\b", "Caja"), (r"^arrafa\b", "Garrafa"),
    (r"\bbarredorra\b", "barredora"), (r"\s*/\s*", "/"),
    (r"\bm\s+icrofibra\b", "microfibra"), (r"\bpap\s+el\b", "papel"),
    (r"\bm\s+adera\b", "madera"), (r"\bem\s+b\s+olsados\b", "embolsados"),
    (r"\bp\s+ostre\b", "postre"), (r"\bm\s+edio\b", "medio"),
    (r"\bN\s+um\s+atic\b", "Numatic"), (r"\bm\s+em\s+brana\b", "membrana"),
    (r"\bEASYM\s+IX\b", "EASYMIX"),
)

PVA_DESCRIPTION = (
    "Bayetas recubiertas de alcohol polivinílico (PVA) que limpian sin dejar rastro. "
    "Lavables hasta 100 veces. Medidas: 35 × 38 cm. Color {color}."
)
MANUAL_OVERRIDES: dict[str, dict[str, Any]] = {
    "FT1036": {
        "nombre_propuesto": "Pack de 5 bayetas PVA Micro Vileda azules",
        "descripcion": PVA_DESCRIPTION.format(color="azul"),
        "presentacion_propuesta": "Pack de 5 bayetas; caja de 20 packs",
        "estado": "revisado_fuente_oficial", "titulo_fuente": "web_oficial",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "FT1037": {
        "nombre_propuesto": "Pack de 5 bayetas PVA Micro Vileda rojas",
        "descripcion": PVA_DESCRIPTION.format(color="rojo"),
        "presentacion_propuesta": "Pack de 5 bayetas; caja de 20 packs",
        "estado": "revisado_fuente_oficial", "titulo_fuente": "web_oficial",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "FT1062": {
        "nombre_propuesto": "Pack de 5 bayetas PVA Micro Vileda verdes",
        "descripcion": PVA_DESCRIPTION.format(color="verde"),
        "presentacion_propuesta": "Pack de 5 bayetas; caja de 20 packs",
        "estado": "revisado_catalogo", "titulo_fuente": "catalogo_pdf_revisado",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "FT1070": {
        "nombre_propuesto": "Pack de 5 bayetas PVA Micro Vileda amarillas",
        "descripcion": PVA_DESCRIPTION.format(color="amarillo"),
        "presentacion_propuesta": "Pack de 5 bayetas; caja de 20 packs",
        "estado": "revisado_catalogo", "titulo_fuente": "catalogo_pdf_revisado",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "FR0096": {
        "nombre_propuesto": "Gel de manos DF SAN sin perfume, bidón de 5 kg",
        "presentacion_propuesta": "Bidón de 5 kg",
        "estado": "revisado_fuente_oficial", "titulo_fuente": "web_oficial",
        "descripcion_fuente": "web_oficial", "nota_conflicto": None, "alternativas": [],
    },
    "AA0801": {
        "nombre_propuesto": "Cepillo duro para lavamoquetas y abrillantadora ES 420",
        "descripcion": "Cepillo duro compatible con la lavamoquetas y abrillantadora ES 420.",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "AA0803": {
        "nombre_propuesto": "Plato de goma para lavamoquetas y abrillantadora ES 420",
        "descripcion": "Plato de goma compatible con la lavamoquetas y abrillantadora ES 420.",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "AA0826": {
        "nombre_propuesto": "Depósito de agua y champú de 10 l para ES 420",
        "descripcion": "Depósito de 10 l para agua y champú, compatible con la ES 420.",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "ZZ1001": {
        "nombre_propuesto": "Lanza con cepillo para moquetas (opcional)",
        "descripcion": "Lanza opcional con cepillo para la limpieza de moquetas.",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
    "AH1022": {
        "nombre_propuesto": "Pistola de vapor para planchado semiprofesional",
        "descripcion": "Pistola de vapor para equipos de planchado semiprofesional.",
        "descripcion_fuente": "catalogo_pdf_revisado",
    },
}


PAGE_121_PRODUCTS: dict[str, tuple[str, str]] = {
    "ZY2001": ("Diamante metálico Ø100 para mármol MS1, grano 60", "Caja de 3 uds.; modelo MS1; grano 60"),
    "ZY2002": ("Diamante metálico Ø100 para mármol MS2, grano 120", "Caja de 3 uds.; modelo MS2; grano 120"),
    "ZY2029": ("Diamante metálico Ø100 para mármol MS0, grano 40", "Caja de 3 uds.; modelo MS0; grano 40"),
    "ZY2033": ("Diamante trapezoidal metálico para mármol MS0, grano 40", "Caja de 3 uds.; modelo MS0; grano 40"),
    "ZY2034": ("Diamante trapezoidal metálico para mármol MS1, grano 60", "Caja de 3 uds.; modelo MS1; grano 60"),
    "ZY2035": ("Diamante trapezoidal metálico para mármol MS2, grano 120", "Caja de 3 uds.; modelo MS2; grano 120"),
    "ZY2047": ("Diamante metálico Ø100 para cemento medio/abrasivo CS00, grano 20", "Caja de 3 uds.; modelo CS00; grano 20"),
    "ZY2048": ("Diamante metálico Ø100 para cemento medio/abrasivo CS0, grano 40", "Caja de 3 uds.; modelo CS0; grano 40"),
    "ZY5045": ("Diamante metálico Ø100 para cemento medio/abrasivo DA00, grano 20", "Caja de 3 uds.; modelo DA00; grano 20"),
    "ZY5103": ("Diamante metálico Ø100 para cemento medio/abrasivo CS1, grano 60", "Caja de 3 uds.; modelo CS1; grano 60"),
    "ZY5104": ("Diamante metálico Ø100 para cemento medio/abrasivo CS2, grano 120", "Caja de 3 uds.; modelo CS2; grano 120"),
    "ZY1025": ("Diamante metálico trapezoidal de resina/cemento Skraper, 2 + 2 segmentos", "Pack de 9 uds.; Skraper; 2 + 2 segmentos"),
    "ZY1026": ("Diamante metálico trapezoidal de resina/cemento Skraper, 2 segmentos", "Pack de 9 uds.; Skraper; 2 segmentos"),
    "ZY5010": ("Diamante metálico trapezoidal de resina/cemento Skraper, 1 + 1 segmentos", "Pack de 9 uds.; Skraper; 1 + 1 segmentos"),
    "ZY5002": ("Diamante metálico trapezoidal para cemento Skraper CS00, grano 20", "Pack de 9 uds.; modelo CS00; grano 20"),
    "ZY2007": ("Diamante metálico Ø100 para granito y gres GS1, grano 20", "Caja de 3 uds.; modelo GS1; grano 20"),
    "ZY2008": ("Diamante metálico Ø100 para granito y gres GS2, grano 40", "Caja de 3 uds.; modelo GS2; grano 40"),
    "ZY2009": ("Diamante metálico Ø100 para granito y gres GS3, grano 60", "Caja de 3 uds.; modelo GS3; grano 60"),
    "ZY5085": ("Diamante metálico Ø100 para terrazo MTS0, grano 30", "Caja de 3 uds.; modelo MTS0; grano 30"),
    "ZY5086": ("Diamante metálico Ø100 para terrazo MTS1, grano 70", "Caja de 3 uds.; modelo MTS1; grano 70"),
    "ZY5087": ("Diamante metálico Ø100 para terrazo MTS2, grano 120", "Caja de 3 uds.; modelo MTS2; grano 120"),
    "ZY5008": ("Diamante trapezoidal para cemento duro DD00 Skraper, grano 20", "Pack de 9 uds.; modelo DD00 Skraper; grano 20"),
    "ZY5004": ("Diamante trapezoidal para cemento semiduro DT00 Skraper, grano 20", "Pack de 9 uds.; modelo DT00 Skraper; grano 20"),
    "ZY5005": ("Diamante trapezoidal para cemento semiduro DT0 Skraper, grano 40", "Pack de 9 uds.; modelo DT0 Skraper; grano 40"),
    "ZY5006": ("Diamante trapezoidal para cemento semiduro DA00 Skraper, grano 20", "Pack de 9 uds.; modelo DA00 Skraper; grano 20"),
    "ZY5007": ("Diamante trapezoidal para cemento semiduro DA0 Skraper, grano 40", "Pack de 9 uds.; modelo DA0 Skraper; grano 40"),
    "ZY5018": ("Diamante trapezoidal para cemento semiduro DT1 Skraper, grano 60", "Pack de 9 uds.; modelo DT1 Skraper; grano 60"),
    "ZY5019": ("Diamante trapezoidal para cemento semiduro DT2 Skraper, grano 120", "Pack de 9 uds.; modelo DT2 Skraper; grano 120"),
    "ZY5143": ("Diamante trapezoidal para cemento semiduro BT00 Skraper Arrow Quick Lock", "Pack de 9 uds.; modelo BT00 Skraper Arrow Quick Lock"),
    "ZY5158": ("Diamante trapezoidal para cemento semiduro PCD Skraper Quick Lock", "Pack de 9 uds.; modelo PCD Skraper Quick Lock"),
    "ZY5117": ("Diamante resinoide Ø100 para mármol MK3, grano 60", "Caja de 3 uds.; modelo MK3; grano 60"),
    "ZY5099": ("Diamante resinoide Ø100 para mármol MK4, grano 120", "Caja de 3 uds.; modelo MK4; grano 120"),
    "ZY5100": ("Diamante resinoide Ø100 para mármol MK5, grano 240", "Caja de 3 uds.; modelo MK5; grano 240"),
    "ZY5101": ("Diamante resinoide Ø100 para mármol MK6, grano 400", "Caja de 3 uds.; modelo MK6; grano 400"),
    "ZY5102": ("Diamante resinoide Ø100 para mármol MK7, grano 800", "Caja de 3 uds.; modelo MK7; grano 800"),
    "ZY5112": ("Diamante resinoide Ø100 para mármol MK8, grano 1500", "Caja de 3 uds.; modelo MK8; grano 1500"),
    "ZY2056": ("Diamante resinoide Ø100 para terrazo MTK3, grano 60", "Caja de 3 uds.; modelo MTK3; grano 60"),
    "ZY2057": ("Diamante resinoide Ø100 para terrazo MTK4, grano 120", "Caja de 3 uds.; modelo MTK4; grano 120"),
    "ZY2058": ("Diamante resinoide Ø100 para terrazo MTK5, grano 220", "Caja de 3 uds.; modelo MTK5; grano 220"),
    "ZY2059": ("Diamante resinoide Ø100 para terrazo MTK6, grano 400", "Caja de 3 uds.; modelo MTK6; grano 400"),
    "ZY2060": ("Diamante resinoide Ø100 para terrazo MTK7, grano 800", "Caja de 3 uds.; modelo MTK7; grano 800"),
    "ZY2069": ("Diamante resinoide Ø100 para terrazo MTK8, grano 1500", "Caja de 3 uds.; modelo MTK8; grano 1500"),
    "ZY2061": ("Diamante resinoide de velcro Ø100 para granito y gres GCK3, grano 60", "Caja de 3 uds.; modelo GCK3; grano 60"),
    "ZY2062": ("Diamante resinoide de velcro Ø100 para granito y gres GCK4, grano 120", "Caja de 3 uds.; modelo GCK4; grano 120"),
    "ZY2063": ("Diamante resinoide de velcro Ø100 para granito y gres GCK5, grano 240", "Caja de 3 uds.; modelo GCK5; grano 240"),
    "ZY2064": ("Diamante resinoide de velcro Ø100 para granito y gres GCK6, grano 400", "Caja de 3 uds.; modelo GCK6; grano 400"),
    "ZY5021": ("Diamante resinoide de velcro Ø75 para cemento GR3, grano 60", "Caja de 9 uds.; modelo GR3; grano 60"),
    "ZY5022": ("Diamante resinoide de velcro Ø75 para cemento GR4, grano 120", "Caja de 9 uds.; modelo GR4; grano 120"),
    "ZY5023": ("Diamante resinoide de velcro Ø75 para cemento GR5, grano 220", "Caja de 9 uds.; modelo GR5; grano 220"),
    "ZY5024": ("Diamante resinoide de velcro Ø75 para cemento GR6, grano 400", "Caja de 9 uds.; modelo GR6; grano 400"),
    "ZY5025": ("Diamante resinoide de velcro Ø75 para cemento GR7, grano 800", "Caja de 9 uds.; modelo GR7; grano 800"),
    "ZY5026": ("Diamante resinoide de velcro Ø75 para cemento GR8, grano 1500", "Caja de 9 uds.; modelo GR8; grano 1500"),
    "ZY5151": ("Diamante resinoide Ø75 Jumper X-Line Green para cemento/terrazo GR3, grano 60", "Caja de 9 uds.; modelo GR3; grano 60"),
    "ZY5152": ("Diamante resinoide Ø75 Jumper X-Line Green para cemento/terrazo GR4, grano 120", "Caja de 9 uds.; modelo GR4; grano 120"),
    "ZY5153": ("Diamante resinoide Ø75 Jumper X-Line Green para cemento/terrazo GR5, grano 220", "Caja de 9 uds.; modelo GR5; grano 220"),
    "ZY5154": ("Diamante resinoide Ø75 Jumper X-Line Green para cemento/terrazo GR6, grano 400", "Caja de 9 uds.; modelo GR6; grano 400"),
    "ZY5155": ("Diamante resinoide Ø75 Jumper X-Line Green para cemento/terrazo GR7, grano 800", "Caja de 9 uds.; modelo GR7; grano 800"),
    "ZY5156": ("Diamante resinoide Ø75 Jumper X-Line Green para cemento/terrazo GR8, grano 1500", "Caja de 9 uds.; modelo GR8; grano 1500"),
}

# Página 122 contrastada visualmente: cada tabla comparte cabeceras, por lo
# que la extracción lineal había asignado el primer nombre a todas sus filas.
PAGE_122_PRODUCTS: dict[str, tuple[str, str]] = {
    **{
        f"ZY{code}": (f"Diamante resinoide Ø100 para granito y gres {model}, grano {grain}", f"Caja de 3 uds.; modelo {model}; grano {grain}")
        for code, model, grain in (
            ("2010", "GK3", 60), ("2011", "GK4", 120), ("2012", "GK5", 240),
            ("2013", "GK6", 400), ("2014", "GK7", 800), ("2015", "GK8", 1500),
            ("2030", "GK8", 3000),
        )
    },
    **{
        f"ZY{code}": (f"Diamante resinoide Ø100 Jumper X-Line Green para cemento/terrazo {model}, grano {grain}", f"Caja de 3 uds.; modelo {model}; grano {grain}")
        for code, model, grain in (
            ("5159", "GR3", 60), ("5160", "GR4", 120), ("5161", "GR5", 220),
            ("5162", "GR6", 400), ("5163", "GR7", 800), ("5139", "GR8", 1500),
        )
    },
    **{
        f"ZY{code}": (f"Diamante resinoide de velcro Ø100 Jumper Green para cemento {model}, grano {grain}", f"Caja de 3 uds.; modelo {model}; grano {grain}")
        for code, model, grain in (
            ("5038", "CK3", 60), ("5039", "CK4", 120), ("5040", "CK5", 220),
            ("5105", "CK6", 400), ("5106", "CK7", 800), ("5107", "CK8", 1800),
        )
    },
    **{
        f"ZY{code}": (f"Diamante resinoide Jumper Yellow X-Line Ø100 para mármol {model}, grano {grain}", f"Caja de 3 uds.; modelo {model}; grano {grain}")
        for code, model, grain in (
            ("5164", "GR3", 60), ("5165", "GR4", 120), ("5166", "GR5", 240),
            ("5167", "GR6", 400), ("5168", "GR7", 800), ("5169", "GR8", 1500),
        )
    },
    **{
        f"ZY{code}": (f"Disco Jaguar Flex resinoide de velcro Ø150 para terrazo/mármol, grano {grain}", f"1 disco; Ø150; grano {grain}")
        for code, grain in zip(("5126", "5127", "5128", "5129", "5130", "5131", "5132"), (30, 60, 120, 220, 400, 800, 1800))
    },
    **{
        f"ZY{code}": (f"Disco Jaguar Flex resinoide de velcro Ø125 para terrazo/mármol, grano {grain}", f"1 disco; Ø125; grano {grain}")
        for code, grain in zip(("5119", "5120", "5121", "5122", "5123", "5124", "5125"), (30, 60, 120, 220, 400, 800, 1800))
    },
    "ZY5036": ("Disco radial metálico Ø125 para Waterfire", "1 disco; Ø125"),
    "ZY5037": ("Disco radial metálico Ø150 para Waterfire", "1 disco; Ø150"),
    "ZY3018": ("Beton Shield, químico abrillantador/hidrofugante", "Bidón de 5 kg"),
    "ZY3020": ("Stone Soap, químico abrillantador/hidrofugante", "Bidón de 5 kg"),
    "ZY3017": ("Kristal Blue, químico abrillantador", "Bidón de 3,8 kg"),
    "ZY5094": ("Kristal Green, químico abrillantador", "Bidón de 3,8 kg"),
    "ZY5095": ("Kristal Black, químico abrillantador", "Bidón de 3,8 kg"),
    "ZY1008": ("Plato acelerador de 150-350 RPM, Ø430 mm", "Ø430 mm"),
    "ZY1011": ("Plato de tracción Quick Attach con velcro, Ø200 mm", "Ø200 mm"),
    "ZY1013": ("Plato dentado, Ø430 mm", "Ø430 mm"),
    "ZY1023": ("Cubreaspiración para pulidora Levighetor", ""),
    "ZY1027": ("Plato de tracción Quick Attach, Ø200 mm", "Ø200 mm"),
    "ZY1028": ("Kit de 3 platos trapezoidales, Ø200 mm", "Kit de 3 uds.; Ø200 mm"),
    "ZY1029": ("Kit de 3 platos para púas de abujardar, Ø200 mm", "Kit de 3 uds.; Ø200 mm"),
    "ZY5001": ("Kit de 3 platos, Ø240 mm", "Kit de 3 uds.; Ø240 mm"),
    "ZY5020": ("Plato con velcro, Ø240 mm", "Ø240 mm"),
    "ZY5055": ("Base de plato con perno, Ø200 mm", "Ø200 mm"),
    "ZY5146": ("Plato Ready Lock, Ø240 mm", "Ø240 mm"),
    "ZY9055": ("Portadiamante modelo AS", "Modelo AS"),
    "ZY9061": ("Plato Minielle", ""),
}

TITLE_FIXES = {
    "AA0006": "Aspirador peinador BAT 18",
    "AA0808": "Cepillo blando para lavamoquetas y abrillantadora ES 420",
    "AL0023": "Bandeja portaobjetos de acero para carro de limpieza",
    "AL0071": "Escurridor inferior para carro multiservicio de 250 l",
    "AL0072": "Escurridor superior para carro multiservicio de 250 l",
    "AL0074": "Tapa superior de acero inoxidable para papelera AL0064",
    "AL4010": "Mosquetón dorado para cordón de poste separador",
    "AL9113": "Suplemento de 45 × 45 × 50 cm para carro de limpieza",
    "AL9131": "Tubo lateral de acero inoxidable para carros AL0034, AL0035 y AL0038",
    "AL9532": "Aro inferior para soporte de escobilla de WC",
    "AL9639": "Rejilla inferior de acero inoxidable para bolsa de carro",
    "AL9632": "Soporte para tubo de carro de limpieza",
    "AL9642": "Protector de goma de recambio para carro de desbarazado AL0078",
    "AL9643": "Aspiradora para carro de limpieza",
    "AM0501": "Cinta antideslizante para pavimentos de zonas húmedas",
    "AU3008": "Carretilla portamaletas de aluminio con soporte delantero plegable",
    "AX4001": "Pulverizador manual para productos de limpieza",
    "AZ0084": "Tapa roja para caja apilable Tecnibox",
    "BA0019": "Papelera exterior Millennium con tapa, 65 l",
    "BA0020": "Papelera exterior Millennium sin tapa, 65 l",
    "BA0095": "Contenedor para residuos de 2.400 l",
    "BA0502": "Contenedor para residuos de 3.200 l",
    "BA4001": "Poste galvanizado para empotrar papelera de exterior",
    "BE0510": "Papelera exterior Prima Linea de ABS, 50 l",
    "BE0511": "Papelera exterior Prima Linea de ABS, 120 l",
    "BE0550": "Papelera exterior Tradition de hierro fundido, 80 l",
    "BE0560": "Papelera exterior Phoenix de ABS, 150 l",
    "BE0529": "Depósito interior opcional para papelera Scuderia de 60 l",
    "BK0045": "Cubo interior opcional para contenedor a pedal de 90 l",
    "BK0049": "Cubo interior opcional para contenedor a pedal de 50 l",
    "BK0054": "Plataforma rodante para contenedores redondos alimentarios",
    "BK0070": "Tapa con dos aperturas para papelera exterior BK0069, negra o beige",
    "BK0131": "Tapa giratoria transparente para contenedor redondo alimentario",
    "BK0152": "Plataforma rodante para contenedor cuadrado alimentario de 151,4 l",
    "BK0236": "Cenicero-colillero Infinity de exterior",
    "BK0034": "Carro portaherramientas con cuatro cajones y compartimento con llave",
    "BK0085": "Mopa húmeda para sistema de fregado manual con mopa plana",
    "BK0288": "Cono plegable de señalización amarillo",
    "BX6145": "Estación de pie para soporte con dosificador automático",
    "BX6144D": "Cartucho de 800 ml de loción antiséptica Dermogen Dry",
    "BX8005": "Dispensador bacteriostático electrónico Twin Wizard, color grafito",
    "BX1151": "Kit de instalación para 3 equipos EasyMix, caudal de 4 l/min",
    "BX1152": "Kit de instalación para 4 equipos EasyMix, caudal de 4 l/min",
    "BX1153": "Kit de instalación para 1 equipo EasyMix, caudal de 16 l/min",
    "BX1155": "Kit de instalación para 3 equipos EasyMix, caudal de 16 l/min",
    "BX1156": "Kit de instalación para 4 equipos EasyMix, caudal de 16 l/min",
    "BX4176": "Kit de conexión al suministro de agua para 1 equipo EasyMix",
    "BX6142": "Dispensador automático blanco para cartucho antiséptico de 800 ml",
    "BX6143": "Dispensador automático negro para cartucho antiséptico de 800 ml",
    "BX6147": "Dispensador manual blanco para cartucho antiséptico de 800 ml",
    "BX6148": "Dispensador manual negro para cartucho antiséptico de 800 ml",
    "BX8007": "Caja de 6 cartuchos Tribac de 360 ml para dispensador Twin Wizard",
    "BX8008": "Caja de 6 cartuchos Tribac Fresco de 360 ml para dispensador Twin Wizard",
    "BX9004": "Kit CM para urinarios",
    "BX9005": "Kit CM para cisternas",
    "BX9006": "Mecha común para kit de urinario o cisterna",
    "BZ1013D": "Colgador para WC o urinario",
    "BZ1027": "Bayeta multiuso amarilla",
    "BZ1028": "Bayeta multiuso azul",
    "BZ1029": "Bayeta multiuso roja",
    "BZ1036": "Fibra abrasiva verde",
    "BZ1037": "Salvauñas con fibra abrasiva",
    "CL1003": "Papelera metálica de exterior con cabezal y cenicero",
    "CL1024": "Recipiente individual para papelera metálica de recogida selectiva",
    "CL1025": "Conjunto de 3 recipientes para papelera metálica de recogida selectiva",
    "CL1023": "Papelera metálica de exterior, Ø70 cm",
    "CL1027": "Papelera metálica de recogida selectiva con 3 recipientes",
    "CL1028": "Papelera metálica de exterior de 170 cm",
    "CL1033": "Papelera metálica de exterior con dos recipientes",
    "CL1023": "Papelera metálica de exterior, Ø70 cm",
    "CL1027": "Papelera metálica de recogida selectiva con 3 recipientes y cenicero",
    "CL1028": "Papelera metálica de exterior de 170 cm",
    "CL1033": "Papelera metálica de exterior con 2 recipientes",
    "CR1018C": "Caja de cubretapas de inodoro Tork V1",
    "CR1116": "Servilletas de papel Tork",
    "CR2007": "Soporte Tork Performance para papel industrial",
    "CR2071": "Dispensador Tork Constant de ambientador, color blanco",
    "CR2072": "Dispensador Tork Constant de ambientador, color negro",
    "CR2073D": "Carga Tork Brisa, bote individual",
    "CR7018": "Dispensador Tork para servilletas plegadas, ABS grafito, modelo CR7018",
    "CR7019": "Dispensador Tork para servilletas plegadas, ABS grafito, modelo CR7019",
    "CR1177": "Papel azul para dispensador manual, caja de 6 bobinas de 612 servicios",
    "CR2069": "Papel Nature para dispensador manual, caja de 6 bobinas de 612 servicios",
    "CR2056": "Dispensador Tork PeakServe de gran capacidad, ABS grafito, modelo CR2056",
    "CR2064": "Dispensador Tork PeakServe de gran capacidad, ABS grafito, modelo CR2064",
    "CR7012": "Percha de acero inoxidable para baño",
    "CX0058": "Carretilla portamaletas de acero inoxidable con soporte delantero plegable",
    "DH0013": "Fregona para limpieza profesional",
    "DH5001": "Paquete de 5 gasas tejidas cubremopa seca de 50 cm",
    "DH5004": "Paquete de 12 gasas tejidas cubremopa seca de 50 cm",
    "DH5005": "Paquete de 12 gasas tejidas cubremopa seca de 80 cm",
    "DH5006": "Paquete de 12 gasas tejidas cubremopa seca de 120 cm",
    "DU0026": "Banco exterior modular de 1 m de ancho",
    "FK0016": "Espejo de baño de doble cara",
    "FK0046": "Recambio de escobilla para soporte de WC, modelo anterior",
    "FK0108": "Tendedero para baño",
    "FK0115D": "Papelera individual para interior",
    "FK0115": "Pack de 3 papeleras de cartón para interior",
    "FK0009": "Secador directo de cabello Piccolo Evolution blanco",
    "FK0021": "Papelera metálica de acero inoxidable para interior",
    "FK0042": "Secamanos Meprolim blanco con sensor",
    "FK0011": "Secador directo de cabello negro y plata, 1.250 W",
    "FK0095": "Percha para baño",
    "FL0001": "Pack de 5 bayetas de microfibra azules",
    "FL0002": "Pack de 5 bayetas de microfibra rojas",
    "FL0003": "Pack de 5 bayetas de microfibra amarillas",
    "FL0004": "Pack de 5 bayetas de microfibra verdes",
    "FL0007": "Pack de 5 bayetas de microfibra multiuso azules",
    "FL0008": "Pack de 5 bayetas de microfibra multiuso rojas",
    "FL0009": "Pack de 5 bayetas de microfibra multiuso amarillas",
    "FL0010": "Pack de 5 bayetas de microfibra multiuso verdes",
    "FL0012": "Pack de 12 bayetas con base de microfibra azules",
    "FL0013": "Pack de 12 bayetas con base de microfibra rojas",
    "FL0014": "Pack de 12 bayetas con base de microfibra grises",
    "FL0015": "Pack de 12 bayetas con base de microfibra amarillas",
    "FL0016": "Pack de 12 bayetas con base de microfibra verdes",
    "FL0018": "Pack de 12 bayetas con base de microfibra blancas",
    "FL0019": "Pack de 10 bayetas multiuso",
    "FP0006C": "Caja de 10 packs de material desechable de higiene",
    "FS0026": "Tapa plana para recipiente alimentario",
    "FW0004": "Papelera interior con forro de vinilo marrón, 12 l",
    "FW0005": "Papelera interior con forro de vinilo blanco, 12 l",
    "FW0006": "Papelera interior con forro de vinilo negro, 12 l",
    "FW0007": "Papelera interior con forro de vinilo gris, 12 l",
    "FW0008": "Papelera interior con forro de vinilo azul, 12 l",
    "FW0009": "Papelera interior con forro de vinilo verde, 12 l",
    "FW0010": "Papelera interior con forro de vinilo burdeos, 12 l",
    "FT1045": "Prensa de recambio para sistema de fregado UltraSpeed",
    "FT1063": "Mopa Express para kit limpiacristales",
    "GA0001": "Robot fregador Scrubber 50 Pro",
    "GA0002": "Robot fregador Scrubber 75",
    "GA0003": "Robot barredor Vacuum 40",
    "LY0020": "Cambiapañales horizontal",
    "LY0004": "Contenedor amarillo con pedal, 45 l",
    "LY0010": "Contenedor amarillo con pedal, 45 l",
    "LY0005": "Contenedor gris con pedal, 45 l",
    "LY0006": "Contenedor blanco con pedal, 45 l",
    "LY0011": "Contenedor gris con pedal, 87 l",
    "LY0031": "Papelera marrón de recogida selectiva, 60 l",
    "PL1039": "Papelera de plástico con pedal",
    "PL6143": "Kit de conversión para aspirador CA15 Plus",
    "PRO1500": "Eliminador de insectos PRO 1500 de policarbonato, mural o con soporte, 15 W",
    "PRO3000": "Eliminador de insectos PRO 3000 de policarbonato colgante, 30 W",
    "YF0001": "Fregadora limpiaescaleras EC 52",
    "YF1001": "Cepillos Tynex para fregadora limpiaescaleras EC 52",
    "YG0038": "Fregadora compacta 244NX",
    "YG9026": "Filtro HEPA para aspiradores Numatic Henry, PRP-180 Basic y RSV130",
    "YG9056": "Media bandeja superior para carro Numatic NuKeeper Universal",
    "YG0025": "Carro de limpieza con puertas Numatic SM1705",
    "YG0045": "Carro de limpieza compacto Numatic MM6",
    "YG1007": "Paquete de 10 bolsas para aspiradores Numatic",
    "YJ1001": "Juego de accesorios incluidos para limpiador de vapor Tidy Vap",
    "YJ1007": "Boquilla corta para limpiador de vapor Tidy Vap",
    "YK0006": "Papelera de polietileno para vasos desechables",
    "ZB0015": "Barredora de gasolina CS120",
    "ZB0017": "Barredora de batería CS120",
    "ZB0025": "Fregadora-barredora eléctrica C120",
    "ZB0026": "Fregadora-barredora bifuel C120",
    "ZB0028": "Fregadora-barredora tripulada Combimac I30",
    "ZB0007": "Barredora de conductor a pie CS500 BT",
    "ZB0063": "Hidrolimpiadora autónoma de agua fría CIC 40 EM Thermic",
    "ZB0064": "Hidrolimpiadora monofásica de agua caliente CIH 10",
    "ZB1120": "Filtro HEPA para aspiradores de polvo y líquido CA100 y CA110.2",
    "ZB1974": "Kit de labios No Shore para fregadora Antea 50 BT",
    "ZB1841": "Kit de labios para fregadoras MR85 B e Innova Comfort 85",
    "ZB9998": "Boquilla plana para aspirador CA15 Plus",
    "ZC9021": "Filtro de recambio para aspirador CA15 Plus",
    "ZC1010": "Aspirador de polvo y líquido CA30, depósito de 25 l",
    "ZC1011": "Aspirador de polvo y líquido CA60, depósito de 43 l",
    "ZC5022": "Boquilla fija para aspiradores de polvo y líquido CA100 y CA110.2",
    "ZC9286": "Manguera para aspirador de polvo y líquido FU20.1 WD",
    "ZD0013": "Fregadora MR85 B",
    "ZD0026": "Fregadora Fimop",
    "ZD0030": "Fregadora-barredora eléctrica GMG Combinata",
    "ZD0031": "Barredora de conductor a pie FSW5-B",
    "ZD9374": "Kit de labios de látex para fregadora Antea 50 BT",
    "ZD9368": "Cepillo de nylon para fregadoras MR85 B e Innova Comfort 85",
    "ZD9476": "Cepillo lateral para fregadora Magna 90-B",
    "ZE4002": "Pinza azul para prensa de fregado manual",
    "ZE4004": "Cubo azul de 6 l para fregado manual",
    "ZE4005": "Cubo rojo de 6 l para fregado manual",
    "ZE4006": "Cubo amarillo de 6 l para fregado manual",
    "ZE4007": "Cubo verde de 6 l para fregado manual",
    "ZG8009": "Lanza de detergente para hidrolimpiadora PW-C45",
    "ZG2002": "Cargador de batería para aspiradores Numatic",
    "ZG0013": "Hidrolimpiadora monofásica PW-C45 DP1310P4M",
    "ZG0014": "Hidrolimpiadora trifásica PW-C45 DP1915P4T",
    "ZG9008": "Conectores de manguera para hidrolimpiadora",
    "ZG9154": "Lanza turbo para hidrolimpiadora ZG0014",
    "ZG9193": "Lanza turbo para hidrolimpiadora ZG0013",
    "ZG9990": "Kit eyector para hidrolimpiadora",
    "ZH1102": "Escobilla de recambio para WC",
    "ZJ0009": "Fregadora-abrillantadora orbital Mi-Tor",
    "ZJ1001": "Depósito opcional para monodiscos y abrillantadoras",
    "ZP0025": "Soporte para papel tissue",
    "ZP5007": "Dispensador cromado de bolsas higiénicas para baño",
    "ZP5009": "Dispensador blanco de bolsas higiénicas para baño",
    "ZY0023": "Complementos para maquinaria Klindex",
    "ZY5061": "Corona diamantada DT0, grano 40",
    "ZY5067": "Corona diamantada DT00, grano 20",
    "VA0283": "Cargador externo Euro de 70 A",
    "VA0284": "Panel eléctrico 14604-70, 220-240 V y 50-60 Hz",
    "VA0285": "Actuador de parada completo 18602-40",
    "VA0286": "Soporte 19621-49",
    "VA0287": "Carcasa de cepillo 56021-36",
    "VA0288": "Anillo de retención 2911/17, 17 A",
    "VA0289": "Anillo de sellado 17420-83, 16/49 5 × 1",
    "VA0290": "Polea Poly-V 17420-86, 8 J 50",
    "YC0025": "Barredora vial eléctrica D.Zero²",
    "AK0001": "Papelera de interior de polipropileno reciclado, 40 l",
    "AF1006C": "Alfombra de vinilo en rizos Degofil de 16 mm, diseño y dimensiones a medida",
    "AF2007": "Pieza de alfombra de vinilo naranja de 100 × 120 cm",
    "AF2007C": "Rollo de alfombra de vinilo naranja de 600 × 120 cm",
    "AL0018Y": "Rueda multifuncional con chasis giratorio a tornillo para cubos",
    "AL0111": "Papelera selectiva circular de acero inoxidable",
    "AL7000Y": "Rueda multifuncional con chasis a tornillo, freno y protección inferior para carros",
    "AL9521": "Rueda neumática trasera para carros AL0025 y AL0028",
    "AL9635": "Rueda de goma elástica con chasis fijo a pletina",
    "AL9636": "Rueda de goma elástica con chasis giratorio a pletina",
    "AL9633": "Rueda de goma elástica de 160 mm",
    "AL9634": "Rueda de goma elástica de 160 mm con chasis a tornillo",
    "AL9637": "Rueda de goma elástica de 160 mm con chasis y freno",
    "AL9638": "Rueda de goma elástica de 160 mm con chasis a pletina y freno",
    "BA4021": "Rueda de 160 mm con chasis y freno para contenedor de 800 l",
    "BA4022": "Rueda de 160 mm con chasis sin freno para contenedor de 800 l",
    "BA2240": "Rueda delantera de 200 mm para contenedores de 90, 120 o 240 l",
    "BE9005": "Rueda de 200 mm con chasis sin freno para contenedor de 800 l",
    "BE9006": "Rueda de 200 mm con chasis y freno para contenedor de 800 l",
    "BK9020": "Kit de dos ruedas neumáticas traseras de 260 mm con eje para carro BK0035",
    "BK9023": "Rueda de 260 mm para carro basculante BK0094",
    "CM0071": "Rueda maciza de 200 × 50 mm con chasis giratorio",
    "CM0072": "Rueda neumática de 200 × 50 mm",
    "CM0078": "Rueda de goma elástica de 200 mm con eje interior fino",
    "CM0093": "Rueda de goma elástica de 200 mm con chasis a pletina",
    "CM0097": "Rueda de goma elástica de 200 mm con chasis y freno",
    "CM0100": "Rueda de goma elástica de 200 mm para L18, grosor 40 mm",
    "CM9522": "Rueda de goma elástica de 100 mm con chasis a tornillo",
    "CM9524": "Rueda neumática de 200 mm con chasis pivotante",
    "CM9532": "Rueda de 160 mm para contenedor de 800 l",
    "PL1024": "Rueda maciza de 260 mm",
    "YG9012": "Rueda de goma elástica de 260 mm para carro Numatic",
    "YG9025": "Rueda de goma elástica de 260 mm con chasis y freno para carro Numatic",
    "YG9028": "Rueda de goma elástica de 260 mm sin chasis para carro Numatic",
    "AL9626": "Rueda de 75 mm con chasis giratorio a tornillo para cubos AL0016-AL0019",
    "CM0104": "Rueda de 75 mm con chasis giratorio a tornillo para cubo ZE1003",
    "FT3002": "Rueda de 75 mm con chasis para sistemas UltraSpeed FT0004/FT0005",
    "AL0093": "Rueda de 75 mm con chasis a tornillo y freno para carros AL0086-AL0090",
    "CM0098": "Rueda de 75 mm de protección inferior para carros AL7000/AL8000",
    "ZE9051": "Kit de cuatro soportes con ruedas de 80 mm para cubo Alex ZE1003",
    "ZE9050": "Rueda de 80 mm con soporte plástico para cubos VDM",
    "CM9523": "Pletina para rueda",
    "CM9528": "Rueda de 100 mm, grosor 32 mm",
    "CM0099": "Rueda de poliamida de 100 mm con chasis giratorio a pletina y freno",
    "CM0101": "Rueda de poliamida de 100 mm con chasis fijo",
    "CM9520": "Rueda de 100 mm con chasis a espárrago, grosor 32 mm",
    "CM0094": "Rueda de 100 mm con chasis giratorio a pletina",
    "CM0095": "Rueda de 100 mm con chasis fijo",
    "AT9104": "Rueda de goma gris de 100 mm",
    "BK9015": "Rueda de 100 mm con casquillo para carros BK0021/BK0026/BK0123",
    "BK9024": "Rueda trasera de 100 mm para carro basculante BK0094",
    "FT3012": "Rueda de 100 mm para carro Origo Vileda FT0006",
    "YG9001": "Rueda de 100 mm con casquillo para carro Numatic YG0017",
    "ZC9111": "Rueda Sabrina de 100 mm para carro ZR0001",
    "CM9529": "Rueda de 125 mm, grosor 32 mm",
    "AL9622": "Rueda de 125 mm con chasis giratorio a pletina",
    "FT9004": "Rueda de 125 mm para carro Vileda",
    "CM0103": "Rueda de poliamida de 125 mm",
    "CM0113": "Rueda de poliamida de 125 mm con chasis giratorio a pletina",
    "ZE9075": "Rueda de 125 mm con chasis Outdoor Soft",
    "CM9527": "Rueda de 125 mm con chasis a tornillo",
    "CM0114": "Rueda de poliamida de 125 mm con chasis fijo",
    "YG9063": "Rueda de 125 mm con chasis y casquillo para carro Numatic",
    "CM9531": "Rueda de 125 mm con chasis giratorio a tornillo y freno",
    "CM0075": "Rueda de goma de 125 mm con casquillo",
    "YG9064": "Rueda de 125 mm con casquillo para carro Numatic",
    "CM0091": "Rueda de goma negra o azul de 150 mm",
    "AL9655": "Rueda de 150 mm con chasis giratorio a tornillo",
    "CM0102": "Rueda de poliamida de 150 mm",
    "AL9656": "Rueda de 150 mm con chasis giratorio a tornillo y freno",
    "CM0090": "Rueda de 150 mm con chasis giratorio a pletina",
    "AL9657": "Rueda de 150 mm con chasis a pletina móvil y freno",
    "CM0092": "Rueda de 150 mm con chasis fijo",
    "ZE9053": "Rueda de 150 mm con chasis giratorio y freno para carro Venecia ZE0013",
    "AL9624": "Rueda delantera de 150 mm con chasis para carro vial AL0025",
    "ZE9054": "Rueda de 150 mm con chasis giratorio sin freno para carro Venecia ZE0013",
    "AL0103": "Carro multiuso corto de acero inoxidable, 84 cm",
    "AL0107": "Carro multiuso de acero inoxidable, 104 cm",
    "AL0110": "Papelera selectiva rectangular de acero inoxidable, 2 departamentos",
    "AL0112": "Carro multiuso largo de acero inoxidable, 104 cm",
    "AL4001": "Poste separador dorado de acero inoxidable",
    "AL4002": "Cordón negro de 1,5 m para poste separador",
    "AL4003": "Cordón beige de 1,5 m para poste separador",
    "AL4014": "Poste separador negro con cinta negra de 2 m",
    "AL9105": "Bandeja de polipropileno para carro AL0035",
    "AL9115": "Tubo lateral de acero inoxidable para carro AL0033",
    "AL9117": "Tubo lateral de acero inoxidable para carro AL0035",
    "AL9122": "Tubo curvado de acero inoxidable para carro AL0036",
    "AL9124": "Bandeja pequeña de polipropileno para carro AL0036",
    "AL9130": "Asa telescópica para carro",
    "AL0089Y": "Rueda multifuncional con chasis a tornillo, freno y protección inferior",
    "AL2078": "Aro para papelera de acero inoxidable de exterior",
    "AL5004": "Armario para 256 llaves de 80 × 69 × 6 cm",
    "AL9527": "Rueda con chasis móvil a tornillo",
    "AM0307": "Gamuza amarilla multiuso",
    "AM0207": "Alfombra mixta Optima 9910 para empotrar en el suelo",
    "AM0309": "Cinta antideslizante transparente de 2,5 cm × 18 m",
    "AM0504": "Pavimento de vinilo beige para zonas húmedas",
    "AL1007": "Bolsa beige plastificada para carro AL0011, 82 × 44 × 75 cm",
    "AL1011": "Bolsa beige plastificada multilínea para carro Aluzinc",
    "AL1013": "Bolsa beige plastificada para carro M1800, 50 × 25 × 95 cm",
    "AZ0086": "Palet verde de retención de líquidos de 1.200 l y carga dinámica de 1.600 kg",
    "BA0400": "Kit para papel para contenedor de pilas de 20 l",
    "BA0401": "Kit para vidrio para contenedor de pilas de 20 l",
    "BA0402": "Kit para papel para contenedor de pilas de 20 l",
    "BA0403": "Kit para vidrio para contenedor de pilas de 20 l",
    "BA0096": "Contenedor completo marrón para residuos, 90 l",
    "BA0021": "Papelera exterior Diana con tapa, 65 l",
    "BA0022": "Papelera exterior Atenea sin tapa, 65 l",
    "BB9002": "Anilla antirrobo de plástico para perchas",
    "BK0043": "Tapa cerrada para contenedor de recogida y separación de residuos",
    "BK0044": "Luz de advertencia para panel de señalización ABS amarillo",
    "BK0078": "Tapa para recipientes BK0077 y BK0250, pack de 6 uds.",
    "BK0091": "Tapa para recipientes BK0088, BK0186 y BK0239, pack de 12 uds.",
    "BK0092": "Tapa para recipientes BK0088, BK0090, BK0149 y BK0187, pack de 6 uds.",
    "BK0097": "Tapa para recipientes BK0099 y BK0199, pack de 12 uds.",
    "BK0143": "Funda para soporte flexible de mopa",
    "BK0160": "Cenicero Infinity de gran capacidad",
    "BK0177": "Cinturón de seguridad para silla infantil",
    "BK0180": "Kit de puerta con cierre para carro de servicio BK0185",
    "BK0200": "Bolsa negra para carro de servicio BK0185",
    "BK0208": "Contenedor cuadrado para uso alimentario, gris o blanco",
    "BK0029": "Papelera exterior multiuso de polipropileno ABS, 56,8 l",
    "BK0290": "Contenedor redondo gris para uso alimentario, 208,2 l",
    "BK0269": "Bolsa de malla para carro de servicio BK0185",
    "BK0218": "Cajón amarillo con cierre para carro de limpieza",
    "BK0069": "Base para papeleras BK0221 y BK0098, color beige o negro",
    "BK0077": "Recipiente redondo alimentario de polietileno con asa, 20,8 l, pack de 6 uds.",
    "BK0088": "Recipiente cuadrado alimentario de policarbonato, 20,8 l, pack de 12 uds.",
    "BK0089": "Recipiente cuadrado alimentario de policarbonato, 11,4 l, pack de 6 uds.",
    "BK0090": "Recipiente cuadrado alimentario de policarbonato, 20,8 l, pack de 6 uds.",
    "BK0099": "Recipiente redondo alimentario de polietileno, 5,7 l, pack de 12 uds.",
    "BK0109": "Recipiente redondo alimentario de polietileno, 7,6 l, pack de 12 uds.",
    "BK0149": "Recipiente cuadrado alimentario de polietileno, 17 l, pack de 6 uds.",
    "BK0186": "Recipiente cuadrado alimentario de polietileno, 7,6 l, pack de 6 uds.",
    "BK0187": "Recipiente cuadrado alimentario de polietileno, 20,8 l, pack de 6 uds.",
    "BK0239": "Recipiente cuadrado alimentario de policarbonato, 1,9 l, pack de 12 uds.",
    "BP4032": "Dispensador de papel higiénico doméstico, acabado mate",
    "BP4042": "Papelera de acero con pedal, negro mate, 5 l",
    "BC9008": "Fluorescente actínico de 6 W para eliminador de insectos",
    "BC9003": "Fluorescente actínico de 11 W para eliminador de insectos",
    "BC9001": "Fluorescente actínico de 15 W para eliminador de insectos",
    "BC9002": "Fluorescente actínico de 20 W para eliminador de insectos",
    "BC1008": "Eliminador de insectos PRO 3000 de policarbonato colgante, 30 W",
    "BE0520": "Papelera exterior Scuderia ABS gris, 60 l",
    "BE0521": "Papelera exterior Scuderia ABS azul, 60 l",
    "BE0522": "Papelera exterior Scuderia ABS verde, 60 l",
    "BE0523": "Papelera exterior Scuderia ABS roja, 60 l",
    "BE0524": "Papelera exterior Scuderia ABS marrón, 60 l",
    "BE0530": "Papelera exterior Atrium de ABS, 50 l",
    "BE0540": "Papelera exterior Ibiza de ABS, 80 l",
    "BX6146": "Sistema de soporte con dosificador automático y estación a pedal",
    "BX1091": "Ecomix Pure Strong, desengrasante en monodosis de 90 ml",
    "BX1165": "Ecomix Pure Strong, desengrasante, bote de 1,5 l",
    "BX1168": "Ecomix Pure Detergente Desinfectant, bote de 1,5 l",
    "BX1169": "Ecomix Pure Apple Floor, friegasuelos, bote de 1,5 l",
    "BX1170": "Ecomix Pure Origin Floor, friegasuelos, bote de 1,5 l",
    "BX1171": "Ecomix Pure Ammonia, limpiador amoniacal, bote de 1,5 l",
    "BX1172": "Ecomix Pure Multiclean, limpiador multiuso, bote de 1,5 l",
    "BX1173": "Ecomix Pure Active, limpiabaños, bote de 1,5 l",
    "BX1174": "Ecomix Pure Kal-Free, limpiador antical higienizante, bote de 1,5 l",
    "BX1177": "Ecomix Pure Lemon Floor, friegasuelos, bote de 1,5 l",
    "BX1178": "Ecomix Pure Bionet, limpiador germicida, bote de 1,5 l",
    "BX6108": "Xtrem Pure Vitro, limpiacristales en monodosis de 33 ml",
    "BX6109": "Xtrem Pure Amonic, limpiador amoniacal en monodosis de 33 ml",
    "BX6110": "Xtrem Pure Multinet, friegasuelos en monodosis de 33 ml",
    "BX6111": "Xtrem Pure Spa, limpiabaños en monodosis de 33 ml",
    "BX6112": "Xtrem Pure Fast, limpiador multiuso en monodosis de 33 ml",
    "BX6116": "Ecomix Pure Detergente Desinfectant, monodosis de 100 ml",
    "BX6123": "Etiqueta Natursafe Plus Degreaser",
    "BX6124": "Etiqueta Natursafe Plus Cleaner",
    "BX6125": "Etiqueta Natursafe Plus Quick",
    "BX6126": "Etiqueta Natursafe Plus Shine",
    "BX6127": "Etiqueta Natursafe Plus Glass",
    "BX8003": "Carga de ambientador en spray Floral Infantil, bote de 250 ml",
    "DZ1003": "Carga de ambientador en spray Té Rojo, bote de 250 ml",
    "DZ1004": "Carga de ambientador en spray Té Verde, bote de 250 ml",
    "DZ1005": "Carga de ambientador en spray Té Jazmín, bote de 250 ml",
    "BX4061": "Solugen N, desengrasante de motores, lata de 10 kg",
    "BX1063": "Cleangen Amolimp, limpiador amoniacal, bidón de 5 l",
    "BX1063C": "Cleangen Amolimp, limpiador amoniacal, caja de 4 bidones de 5 l",
    "BX4007": "Aquagen LT, limpiador amoniacal, bidón de 5 l",
    "BX4007C": "Aquagen LT, limpiador amoniacal, caja de 4 bidones de 5 l",
    "BX4055": "Adigen L, limpiador desincrustante y quitacementos, bidón de 5 l",
    "BX4055C": "Adigen L, limpiador desincrustante y quitacementos, caja de 4 bidones de 5 l",
    "BX4023": "Suciwax CS-400, cristalizador, bidón de 5 kg",
    "BX4023C": "Suciwax CS-400, cristalizador, caja de 4 bidones de 5 kg",
    "BX4087": "Aquagen Deskal, desincrustante, bidón de 5 kg",
    "BX4087C": "Aquagen Deskal, desincrustante, caja de 4 bidones de 5 kg",
    "BX4110": "Aquagen Plus 65 ADX, detergente para lavavajillas, bidón de 10 kg",
    "BX1066": "Aquagen Supra 45, abrillantador para lavavajillas y aguas blandas, bidón de 20 l",
    "BX6067": "Botella pulverizadora de espuma Deskal de 1 l",
    "BX6073": "Etiqueta Xtrem Pure Multinet",
    "BX6077": "Etiqueta Xtrem Pure Amonic",
    "BX6078": "Etiqueta Xtrem Pure Vitro",
    "BX6079": "Etiqueta Xtrem Pure Fast",
    "BX6080": "Etiqueta Xtrem Pure Spa",
    "BX1157": "Etiqueta Ecomix Pure Kal-Free YEC-Mini",
    "BX1162": "Etiqueta Ecomix Pure Breath Green Tea YEC-Mini",
    "BX1163": "Etiqueta Ecomix Pure Breath Floral YEC-Mini",
    "BX6050": "Etiqueta Ecomix Pure Ammonia YEC-Mini",
    "BX6051": "Etiqueta Ecomix Pure Strong YEC-Mini",
    "BX6052": "Etiqueta Ecomix Pure Desinfectant YEC-Mini",
    "BX6053": "Etiqueta Ecomix Pure Lemon Floor YEC-Mini",
    "BX6054": "Etiqueta Ecomix Pure Wash Foam YEC-Mini",
    "BX6055": "Etiqueta Ecomix Pure Germicida YEC-Mini",
    "BX6056": "Etiqueta Ecomix Pure Active YEC-Mini",
    "BX6057": "Etiqueta Ecomix Pure Multiclean YEC-Mini",
    "BX6084": "Caja de 12 botellas dispensadoras de 500 ml",
    "BX6085": "Caja de 12 botellas dosificadoras de 500 ml",
    "BX6086": "Caja de 12 botellas pulverizadoras de 500 ml",
    "BX6140": "Caja de 16 botellas dispensadoras de 1 l",
    "BX6140D": "Botella dispensadora de 1 l",
    "BX6082": "Caja de 12 botellas dosificadoras de 1 l",
    "BX6082D": "Botella dosificadora de 1 l",
    "BX9036": "Caja de 16 botellas espumadoras de 1 l",
    "BX9036D": "Botella espumadora de 1 l",
    "BX9035": "Caja de 16 botellas nebulizadoras de 750 ml",
    "BX9035D": "Botella nebulizadora de 750 ml",
    "BX1126": "Diluidor EasyMix, código impreso para caudales de 4 y 16 l/min",
    "BX4113": "Aquagen Supra 45 AD, abrillantador para lavavajillas, bidón de 10 kg",
    "CR2059": "Dispensador de servilletas interplegadas ABS para mesa",
    "CR2062": "Dispensador de servilletas interplegadas ABS para barra",
    "CR4015": "Cajón con soporte de pie para dosificadores",
    "CK0094": "Dosificador automático negro para cartuchos de desinfección",
    "CL1009": "Papelera metálica selectiva con cabezal y 2 recipientes",
    "CR2073": "Carga Tork Brisa, caja de 6 botes",
    "CR2074": "Carga Tork Floral, caja de 6 botes",
    "CR2074D": "Carga Tork Floral, bote individual",
    "CR2075": "Carga Tork Neutralizador, caja de 6 botes",
    "CR2075D": "Carga Tork Neutralizador, bote individual",
    "CR1098C": "Caja de servilletas azules de 40 × 40 cm, 12 paquetes de 100 uds.",
    "GO0003C": "Caja de servilletas azules de 40 × 40 cm, 24 paquetes de 50 uds.",
    "GO0038C": "Caja de servilletas azules de 40 × 40 cm, 20 paquetes de 100 uds.",
    "GO0040C": "Caja de servilletas azules Filum de 40 × 40 cm, 12 paquetes de 50 uds.",
    "GO0004C": "Caja de servilletas rojas de 40 × 40 cm, 24 paquetes de 50 uds.",
    "GO0023C": "Caja de servilletas rojas de 40 × 40 cm, 16 paquetes de 100 uds.",
    "GO0037C": "Caja de servilletas rojas de 40 × 40 cm, 20 paquetes de 100 uds.",
    "CR1085C": "Caja de servilletas burdeos Premium de 40 × 40 cm, 12 paquetes de 50 uds.",
    "GO0005C": "Caja de servilletas burdeos de 40 × 40 cm, 24 paquetes de 50 uds.",
    "GO0033C": "Caja de servilletas burdeos de 40 × 40 cm, 20 paquetes de 100 uds.",
    "CR7023": "Dosificador de cartucho ABS grafito de 1 l para gel, espuma o alcohol",
    "CR7032": "Dispensador automático de papel en rollo de acero inoxidable",
    "CK0054D": "Crema Universal Protect, cartucho de 1 l",
    "CK0054": "Crema Universal Protect, caja de 6 cartuchos de 1 l",
    "CK0063": "Crema hidratante, caja de 6 cartuchos de 1 l",
    "CK0063D": "Crema hidratante, cartucho de 1 l",
    "CK0082D": "Protector solar factor 30, cartucho de 1 l",
    "CK0090D": "Protector solar factor 50, cartucho de 1 l",
    "CK0036": "Foam Wash, gel espuma, caja de 6 cartuchos de 1 l",
    "CK0036D": "Foam Wash, gel espuma, cartucho de 1 l",
    "CK0064": "Relax Foam Wash, caja de 6 cartuchos de 1 l",
    "CK0064D": "Relax Foam Wash, cartucho de 1 l",
    "CK0065": "Rose Foam Wash, caja de 6 cartuchos de 1 l",
    "CK0065D": "Rose Foam Wash, cartucho de 1 l",
    "CK0067": "Arma Rubis, caja de 6 cartuchos de 1 l",
    "CK0067D": "Arma Rubis, cartucho de 1 l",
    "VA0041": "Bayeta de microfibra Johnson roja, 31 × 34 cm",
    "VA0042": "Bayeta de microfibra Johnson azul, 31 × 34 cm",
    "VA0299": "Bayeta de microfibra Johnson verde, 31 × 34 cm",
    "VA0300": "Bayeta de microfibra Johnson amarilla, 31 × 34 cm",
    "CU0045": "Rollo de 10 bolsas de plástico verdes, 85 × 105 cm",
    "CU0045C": "Caja de 400 bolsas de plástico verdes, 85 × 105 cm",
    "CU0070": "Rollo de 10 bolsas de plástico verdes, 85 × 105 cm",
    "CR7020": "Dosificador automático con sensor para jabón líquido de cartucho, ABS grafito, 1 l",
    "CR7021": "Dosificador de cartucho para gel, espuma o alcohol, color grafito",
    "CR7022": "Dosificador manual para jabón líquido de cartucho, ABS grafito, 1 l",
    "CW0025": "Batería de gel para barredora FSR B",
    "CZ0002": "Cadena de inicio opcional para monedero",
    "CX0007": "Escobón industrial suave de 40 cm",
    "DJ1001": "Bote de crema abrillantadora de 1 kg para máquinas limpiacalzado",
    "DR0005": "Jardinera esférica grande de acero con tratamiento Ferrus, Ø130 × 47 cm",
    "DR0021": "Bolardo abatible Parking H290 de acero zincado, 61 × 25 × 54,5 cm",
    "CS0007": "Disco azul de lana de acero n.º 3, Ø43 cm",
    "CS0008": "Disco azul de lana de acero n.º 3, Ø51 cm",
    "CS0009": "Disco rojo de lana de acero n.º 1, Ø43 cm",
    "CS0010": "Disco rojo de lana de acero n.º 1, Ø51 cm",
    "CS0003": "Rollo de lana de acero n.º 1 fina, 2,5 kg",
    "CS0003C": "Saco de lana de acero n.º 1 fina, 10 kg",
    "CS0004": "Rollo de lana de acero n.º 3 gruesa, 2,5 kg",
    "CS0004C": "Saco de lana de acero n.º 3 gruesa, 10 kg",
    "CS0006": "Rollo de lana de acero n.º 2 rizada, 2,5 kg",
    "CS0006C": "Saco de lana de acero n.º 2 rizada, 10 kg",
    "DR0016": "Banco Neobarcino de fundición dúctil y madera natural, 50 × 50 × 45 cm",
    "DR0008": "Jardinera de madera de pino tratada, modelo UM1640/4, 100 × 100 × 65,5 cm",
    "DR0009": "Bolardo Esquirol H205T de acero zincado, Ø6 × 107 cm",
    "DR0013": "Banco Bretaña UM374 de fundición dúctil y madera, 180 × 63 × 77 cm",
    "DR0015": "Banco Essen UM379M de acero galvanizado, 166 × 62 × 80,5 cm",
    "DR0027": "Bolardo Universal H211AP de acero zincado, Ø30 × 41 cm",
    "DR0029": "Bolardo Hospitalet H214 de acero zincado, Ø9,5 × 100 cm",
    "DR0032": "Bolardo Hospitalet H214E/1C de acero zincado, Ø9,5 × 97 cm",
    "DR0034": "Bolardo Kroc H292 de acero galvanizado, 34,5 × 94 cm",
    "DR0035": "Banqueta City UM392B de acero galvanizado, 186 × 37 × 45 cm",
    "DR0038": "Aparcabicicletas Omega VB01 de acero zincado o inoxidable, 90,5 × 10 × 69,5 cm",
    "DR0041": "Bolardo Via Augusta H2PH de acero zincado, Ø17 × 54 cm",
    "DR0043": "Bolardo Hospitalet Flex H214FCM de acero zincado, Ø10 × 104,5 cm",
    "DR0044": "Banqueta Toledo UM370 de hormigón prefabricado, 200 × 45 × 42,5 cm",
    "DR0046": "Banco Trau UM396H de hormigón prefabricado, 200 × 63 × 51 cm",
    "DR0054": "Banco Valles UM340 de acero zincado, 206,5 × 76 × 85,5 cm",
    "DR0052": "Banco Roda UM320 de fundición dúctil y madera, 199,5 × 62 × 75 cm",
    "DX1003": "Vasos de papel blancos desechables de 240 ml, caja de 20 × 50 uds.",
    "DX1006": "Vasos de papel blancos desechables de 240 ml, caja de 20 × 50 uds.",
    "DX1020": "Tapas para vasos de 118 ml, caja de 10 × 100 uds.",
    "DX1022": "Tapas para vasos de 236 ml, caja de 10 × 100 uds.",
    "DX1043": "Vasos blancos desechables de 210 ml, caja de 500 uds. embolsadas",
    "DX1047": "Vasos transparentes desechables de 330 ml, caja de 25 × 50 uds.",
    "DX1048": "Vasos PET transparentes de 473 ml, caja de 20 × 50 uds.",
    "DX1049": "Tapas de cúpula con agujero de 92 mm, caja de 10 × 100 uds.",
    "DX1050": "Código compartido: vasos de helado Kraft de 120 ml / vasos de chupito transparentes de 35 ml",
    "DX1051": "Vasos de helado Kraft de 240 ml, caja de 20 × 50 uds.",
    "EN421": "Guantes de protección contra contacto directo, norma EN 421",
    "LY0029": "Base con ruedas para papelera de recogida selectiva de 60 l",
    "LY0030": "Papelera roja de recogida selectiva de 60 l",
    "LY0012": "Contenedor con pedal de 87 l, cuerpo gris y tapa roja",
    "LY0013": "Contenedor con pedal de 87 l, cuerpo gris y tapa amarilla",
    "LY0014": "Contenedor con pedal de 87 l, cuerpo gris y tapa verde",
    "LY0015": "Contenedor con pedal de 87 l, cuerpo gris y tapa azul",
    "LY0024": "Contenedor con pedal de 30 l, cuerpo gris y tapa marrón",
    "LY0025": "Contenedor con pedal de 45 l, cuerpo gris y tapa marrón",
    "LY0026": "Contenedor con pedal de 68 l, cuerpo gris y tapa marrón",
    "LY0027": "Contenedor con pedal de 87 l, cuerpo gris y tapa marrón",
    "LY0028": "Contenedor con pedal de 30 l, cuerpo gris y tapa azul",
    "LY0016": "Papelera azul de recogida selectiva, 60 l",
    "LY0017": "Papelera amarilla de recogida selectiva, 60 l",
    "LY0018": "Papelera gris de recogida selectiva, 60 l",
    "PL6169": "Vasos de café blancos desechables de 100 ml, paquete de 100 uds.",
    "FK0070": "Secamanos automático Meprolim de ABS negro mate, 1.500 W",
    "FK0104": "Hervidor de habitación de acero inoxidable, 1 l",
    "FP0001C": "Caja de 20 packs de 100 redes para el pelo",
    "FP0004C": "Caja de 20 packs de 100 manguitos de plástico",
    "FP0005C": "Caja de 20 packs de 100 cubrecalzados de plástico",
    "FR0145": "Masslimp Amidés, detergente desinfectante espumante, bidón de 20 l",
    "FR0144": "Detergente desengrasante profesional",
    "FR0033": "Meprolim E-110, limpiador jabonoso de madera, bote de 1 l",
    "FR0033C": "Meprolim E-110, limpiador jabonoso de madera, caja de 12 botes de 1 l",
    "FR0067": "Meprolim E-260A, limpiacristales, bidón de 5 l",
    "FR0067C": "Meprolim E-260A, limpiacristales, caja de 4 bidones de 5 l",
    "FR0030": "Biofresh Meprolim Lima, ambientador, bidón de 5 kg",
    "FR0030C": "Biofresh Meprolim Lima, ambientador, caja de 4 bidones de 5 kg",
    "FR0032": "Biofresh Meprolim Cerámica, ambientador, bidón de 5 kg",
    "FR0032C": "Biofresh Meprolim Cerámica, ambientador, caja de 4 bidones de 5 kg",
    "FR2065": "Masslimp Microsan, desinfectante de amonio cuaternario, bidón de 20 l",
    "FR2069": "Vircol, toallitas desinfectantes, cubo de 115 uds. de 30 × 25 cm",
    "FR0045": "Cleangen Universal, detergente espumante multiuso, bote de 1 l",
    "FR0045C": "Cleangen Universal, detergente espumante multiuso, caja de 12 botes de 1 l",
    "FR2048": "Meprolim E-260A, limpiacristales, bote de 1 l",
    "FR2048C": "Meprolim E-260A, limpiacristales, caja de 12 botes de 1 l",
    "FR2061": "TAP Meprolim, sellador de suelos, bidón de 5 l",
    "FR2061C": "TAP Meprolim, sellador de suelos, caja de 4 bidones de 5 l",
    "FR2062": "Sanigen Biofinish, humectante y controlador de biofilms, bidón de 5 l",
    "FR2062C": "Sanigen Biofinish, humectante y controlador de biofilms, caja de 4 bidones de 5 l",
    "DZ0008": "Puligen Mobel Fast, pulimento de madera, bote de 1 l",
    "DZ0008C": "Puligen Mobel Fast, pulimento de madera, caja de 12 botes de 1 l",
    "BX4015": "Masstech, limpiador de circuitos cerrados y calderas de baja espuma, bidón de 5 l",
    "BX4015C": "Masstech, limpiador de circuitos cerrados y calderas de baja espuma, caja de 4 bidones de 5 l",
    "FR0052C": "Hydrogel Meprolim, gel hidroalcohólico, caja de 12 botes de 1 l",
    "FR0053C": "Hydrogel Meprolim, gel hidroalcohólico, caja de 4 bidones de 5 l",
    "FS0014": "Cubeta de policarbonato GN 1/2, 3,4 l",
    "FS0022": "Cubeta de policarbonato GN 1/1, 7,2 l",
    "FS0023": "Cubeta de policarbonato GN 1/1, 12 l",
    "FS0024": "Cubeta de policarbonato GN 1/2, 5 l",
    "DZ1001": "Ambientador Blue floral a granel, bidón de 5 l",
    "DZ1002": "Ambientador Royal de limón a granel, bidón de 5 l",
    "DZ1001C": "Ambientador Blue floral a granel, caja de 4 bidones de 5 l",
    "DZ1002C": "Ambientador Royal de limón a granel, caja de 4 bidones de 5 l",
    "PL0285": "Lejía alimentaria Tagoten, botella de 2 l",
    "UM392": "Banco City de acero galvanizado, 186 × 58 × 81,5 cm",
    "UM392S": "Silla City de acero galvanizado, 65 × 58 × 81,5 cm",
    "UM320S": "Silla Roda de fundición dúctil y madera, 59,5 × 62 × 75 cm",
    "UM345": "Banco Goteborg de madera tropical tratada, 165 × 65 × 91,5 cm",
    "UM345L": "Banco largo Goteborg de madera tropical tratada, 230 × 65 × 91,5 cm",
    "UM345S": "Silla Goteborg de madera tropical tratada, 68 × 65 × 91,5 cm",
    "UM368": "Banco Ergo de fundición dúctil y madera, 180 × 66 × 83 cm",
    "UM370R": "Banco Toledo de hormigón prefabricado, 200 × 56 × 84,5 cm",
    "UM371L": "Banco Ela de hormigón armado, 300 × 80 × 42 cm",
    "UM372": "Banco Kube de hormigón prefabricado, 200 × 50 × 45 cm",
    "UM376": "Banco Arenal de hormigón prefabricado y madera tropical, 190 × 45 × 87 cm",
    "UM379S": "Silla Essen de acero galvanizado, 55 × 62 × 80,5 cm",
    "UM388": "Banco de fundición dúctil con imprimación epoxi, 206 × 73 × 85 cm",
    "UM395": "Banco Alea de acero galvanizado y madera, 209,5 × 67 × 88 cm",
    "UM395B": "Banqueta Alea de acero galvanizado y madera, 210 × 67,5 × 59,8 cm",
    "UM396E": "Banco Trau de hormigón prefabricado, 200 × 63 × 51 cm",
    "UM397": "Banco Leman de fundición dúctil y madera, 230 × 60 × 83 cm",
    "UM397B": "Banqueta Leman de fundición dúctil y madera, 230 × 54,5 × 45 cm",
    "UM398": "Banco Mate de madera y acero inoxidable, 200 × 77 × 84,5 cm",
    "UM305S": "Silla Barcino de fundición dúctil y madera, 54 × 70 × 78,5 cm",
    "UM502": "Fuente Barcino de fundición con imprimación epoxi, Ø63 × 39,5 × 125 cm",
    "UM508": "Fuente Fonti de fundición con imprimación epoxi, Ø31 × 20 × 98,5 cm",
    "UM511": "Fuente Atlas de hierro con tratamiento Ferrus, 30 × 150 × 101 cm",
    "UM530": "Código compartido: fuente Trevi de acero zincado / fuente Fonti de hormigón",
    "UM1111": "Jardinera Aro de acero con tratamiento Ferrus, Ø81 × 56 cm",
    "UM1115": "Jardinera Oval de acero con tratamiento Ferrus, 100 × 40 × 52,5 cm",
    "UM1372": "Jardinera Kube de hormigón prefabricado, 58 × 58 × 58 cm",
    "UM1555": "Jardinera Dara de acero con tratamiento Ferrus, 74,5 × 74,5 × 50 cm",
    "UM16401": "Jardinera de pino tratado UM1640-1, 180 × 60 × 45 cm",
    "UM16402": "Jardinera de pino tratado UM1640-2, 100 × 50 × 45 cm",
    "UM16405": "Jardinera de pino tratado UM1640-5, 60 × 60 × 45 cm",
    "UM16406": "Jardinera de pino tratado UM1640-6, 100 × 100 × 100 cm",
    "UM304B": "Banqueta Neobarcino de fundición dúctil y madera, 180 × 63 × 65,5 cm",
    "UM304L": "Banco largo Neobarcino de fundición dúctil y madera, 300 × 71 × 80 cm",
    "UM340B": "Banqueta Valles de acero zincado, 208 × 50 × 47 cm",
    "UM340D": "Banco doble Valles de acero zincado, 208 × 150 × 85 cm",
    "UM350": "Banco Nórdico de madera de pino, 175 × 56 × 85,5 cm",
    "UM510": "Fuente Egea de acero con tratamiento Ferrus, Ø19 × 103 cm",
    "UM527": "Fuente Set de acero galvanizado, 40 × 15 × 100 cm",
    "UM540I": "Fuente Dual de acero inoxidable, 70 × 75 × 104 cm",
    "UM1160": "Jardinera Olea circular de chapa de acero, Ø75 × 75 cm",
    "UM1204": "Jardinera Ner de chapa de acero, 60 × 60 × 78 cm",
    "UM1210": "Jardinera Rami de chapa de acero, 50 × 50 × 103 cm",
    "UM1220": "Jardinera Olea cuadrada de chapa de acero, 75 × 75 × 75 cm",
    "YF9006": "Cepillo central para barredora manual Picobello 101",
    "YF9007": "Cepillo lateral para barredora manual Picobello 101",
    "YC9045": "Cepillo central para barredoras 700 EH/SH",
    "YC9135": "Cepillo lateral para barredoras 700 EH/SH",
    "UM1152": "Jardinera rectangular de acero con tratamiento Ferrus, 100 × 42,5 × 52 cm",
    "UM398E": "Banco extremo Mate de madera y acero inoxidable, 200 × 73 × 86 cm",
    "YG0011": "Aspirador de mochila inalámbrico RSB 140 con batería de litio y cargador",
    "ZB2314": "Mochila Long Range opcional para pistola electrostática E-Spray",
    "ZB0024": "Aspirador de polvo de mochila CA Back B con batería",
    "ZB0012": "Fregadora Vispa Evo Essential",
    "ZB1018": "Fregadora Media 65 BT",
    "ZB1480": "Fregadora Ultra 120 B a batería",
    "ZB1481": "Fregadora Ultra 120 G a gasolina",
    "ZD0014": "Fregadora Genie 35 B",
    "ZD0022": "Fregadora IMX-50 B",
    "ZD9449": "Labio delantero para fregadora Fimop",
    "ZD9450": "Labio trasero para fregadora Fimop",
    "ZD9447": "Labio delantero para fregadora Genie XS",
    "ZD9448": "Labio trasero para fregadora Genie XS",
    "ZB8045": "Cepillo de nylon para fregadora Genie XS",
    "ZB9446": "Batería para fregadora Genie XS",
    "ZB1725": "Labio delantero para fregadora Genie 35 B",
    "ZB1709": "Labio trasero para fregadora Genie 35 B",
    "ZD1010": "Cepillo de nylon para fregadora Genie 35 B",
    "ZB1800": "Labio delantero para fregadora Optima 100 B",
    "ZB1799": "Labio trasero para fregadora Optima 100 B",
    "ZB2001": "Cepillo de nylon para fregadoras Optima 100 B y C100 B Essential",
    "ZB2290": "Labio delantero para fregadora C100 B Essential",
    "ZB2289": "Labio trasero para fregadora C100 B Essential",
    "ZB9592": "Labio delantero para fregadora-barredora C130",
    "ZB9604": "Labio trasero para fregadora-barredora C130",
    "ZB2063": "Cepillo para fregadora-barredora C130",
    "ZB2064": "Plato para fregadora-barredora C130",
    "ZB1601": "Cepillo de nylon para fregadora Innova 55 B",
    "ZB2000": "Cepillo de nylon para fregadora MMG 75 B",
    "ZB2055": "Plato de goma para fregadora C85 B",
    "ZB2145": "Kit de labios para fregadora MMG 75 B",
    "ZB2296": "Cepillo de nylon para fregadoras GL Pro y Vispa Evo Essential",
    "ZB2308": "Kit de labios para fregadoras GL Pro y Vispa Evo Essential",
    "ZB3153": "Cepillo de nylon para fregadora C85 B",
    "ZD1013": "Cepillo de nylon para fregadoras L20 E, IMX-50 B y Antea 50 BT",
    "ZD9354": "Kit de labios estándar para fregadoras L20 E, IMX-50 B, Antea 50 BT e Innova 55 B",
    "ZB1016": "Fregadora C100 B Essential",
    "ZB1346": "Boquilla de cuerpo para aspiradores CA30/CA60",
    "ZB1351": "Recambio de boquilla de suelo para aspiradores CA30/CA60",
    "ZB1352": "Recambio de aspiración de agua para aspiradores CA30/CA60",
    "ZB1557": "Tubo curvado para aspiradores CA30/CA60",
    "ZC5025": "Cepillo redondo para aspiradores CA30/CA60",
    "ZC9178": "Tubo recto para aspiradores CA30/CA60",
    "ZC9203": "Manguera para aspiradores CA30/CA60",
    "YG9002": "Manguera para aspiradores Numatic",
    "YG9003": "Boquilla combinada para suelos de aspiradores Numatic",
    "YG9088": "Boquilla para tapicerías con cepillo de aspiradores Numatic",
    "ZB1328": "Tubo extensible para aspirador CA15 Plus",
    "ZB1350": "Manguera para aspirador CA15 Plus",
    "ZB1375": "Boquilla combinada para suelos del aspirador CA15 Plus",
    "ZB0062": "Hidrolimpiadora trifásica de agua fría CIC 30",
    "ZB0065": "Hidrolimpiadora trifásica de agua caliente CIH 30",
    "ZB0066": "Hidrolimpiadora trifásica de agua caliente CIH 50",
    "ZG0005": "Hidrolimpiadora trifásica de agua caliente PW-H101 Plus",
    "ZC5020": "Kit Heavy Vac antiestático Ø40 mm para aspiradoras industriales",
    "ZC5023": "Kit Heavy Vac antiestático Ø50 mm para aspiradoras industriales",
    "ZC5028": "Kit Heavy Vac estándar Ø50 mm para aspiradoras industriales",
    "ZC5029": "Kit Heavy Vac extra Ø50 mm para aspiradoras industriales",
    "ZC5030": "Kit Heavy Vac extra Ø40 mm para aspiradoras industriales",
    "ZC1037": "Aspirador de polvo TO55L/TO30L",
    "ZC1038": "Aspirador de polvo TNG55",
    "ZC1039": "Aspirador de polvo TLT70",
    "ZB1347": "Tubo curvado para aspirador CA15 Plus",
    "ZB9995": "Tubo recto para aspirador CA15 Plus",
    "ZB9997": "Cepillo redondo para aspirador CA15 Plus",
    "ZC5011": "Manguera para aspiradores CA100, CA110.2, PRO58 3WDM y P750.3 WDM S",
    "ZC9184": "Tubo recto y curvado para aspiradores CA100, CA110.2, PRO58 3WDM y P750.3 WDM S",
    "ZC9185": "Boquilla de suelo para aspiradores CA100, CA110.2, PRO58 3WDM y P750.3 WDM S",
    "ZC9186": "Boquilla de aspiración de agua para aspiradores CA100, CA110.2, PRO58 3WDM y P750.3 WDM S",
    "ZC5009": "Boquilla plana para aspiradores CA100, CA110.2, PRO58 3WDM y P750.3 WDM S",
    "ZB1086": "Cepillo redondo para aspiradores CA100, CA110.2, PRO58 3WDM y P750.3 WDM S",
    "ZC3001": "Boquilla para tapicerías de lavamoquetas Extract P25",
    "ZC3002": "Boquilla para suelos de lavamoquetas Extract P25",
    "ZC3003": "Tubo recto para lavamoquetas Extract P25",
    "ZC3004": "Manguera para lavamoquetas Extract P25",
    "YG9086": "Juego de dos cepillos de nylon para fregadora Compact 244NX",
    "YG9068": "Juego de dos platos de goma para fregadora Compact 244NX",
    "YG9069": "Kit de labios para fregadora Compact 244NX",
    "ZB9009": "Labio de secado para fregadora Abila 17 B, referencia ZB9009",
    "ZB9010": "Labio de secado para fregadora Abila 17 B, referencia ZB9010",
    "ZB9011": "Labio de secado para fregadora Abila 17 B, referencia ZB9011",
    "ZB1651": "Kit de labios para fregadoras Versa 65 BT y Media 65 BT",
    "ZD1011": "Cepillo de nylon para fregadoras Versa 65 BT y Media 65 BT",
    "ZD1012": "Plato de goma para fregadoras Versa 65 BT y Media 65 BT",
    "ZD9308": "Kit de labios para fregadora Innova Comfort 75",
    "ZD9350": "Cepillo de nylon para fregadora Innova Comfort 75",
    "ZD9355": "Plato de goma para fregadora Innova Comfort 75",
    "ZB9227": "Labio delantero para fregadora Ultra 120 B",
    "ZB9226": "Labio trasero para fregadora Ultra 120 B",
    "ZB1886": "Cepillo de nylon para fregadora Ultra 120 B",
    "ZB0060": "Hidrolimpiadora monofásica de agua fría CIC 15",
    "ZB0061": "Hidrolimpiadora monofásica de agua fría CIC 20",
    "ZG0006": "Hidrolimpiadora de agua fría a gasolina Benz C",
    "YF9006": "Cepillo central para barredora manual Picobello 101",
    "YF9007": "Cepillo lateral para barredora manual Picobello 101",
    "ZB2294": "Cepillo central para barredoras CS90 B/D",
    "ZB1459": "Cepillo lateral para barredoras CS90 B/D",
    "ZB1400": "Cepillo central para barredoras CS120 B/D",
    "ZB1401": "Cepillo lateral para barredoras CS120 B/D",
    "ZD1033": "Cepillo central para barredoras FSR B/Hybrid",
    "ZD1024": "Cepillo lateral para barredoras FSR B/Hybrid",
    "ZC5027": "Kit de accesorios para aspiradoras industriales",
    "ZD9477": "Cepillo central para barredora Fimap",
    "ZE1008": "Cubo doble de fregado Sky completo, 25 + 10 l, prensa opcional",
    "ZG2001": "Boquilla para hidrolimpiadora de agua fría a gasolina Benz C",
    "ZG8037": "Campana limpiasuelos de 350 mm para hidrolimpiadora",
    "ZG9084": "Boquilla de alta presión 1504 para hidrolimpiadora",
    "ZG9136": "Boquilla de alta presión 15045 para hidrolimpiadora",
    "ZG9775": "Boquilla de alta presión 2505 para hidrolimpiadora",
    "ZG9896": "Boquilla de alta presión 25075 para hidrolimpiadora",
    "ZG9973": "Kit enrollador de manguera para hidrolimpiadora",
    "ZJ1016": "Disco de microfibra para suelos y parquet, accesorio TPO 43 Spray",
    "ZJ1018": "Disco de microfibra para moquetas y alfombras, accesorio TPO 43 Spray",
    "ZJ1022": "Pad abrasivo marrón para fregadora/abrillantadora orbital Mi-Tor",
    "ZJ1023": "Pad abrasivo rojo para fregadora/abrillantadora orbital Mi-Tor",
    "ZJ1002": "Cepillo de nylon para monodisco CM50 Plus",
    "ZJ1003": "Plato de goma para monodisco CM50 Plus",
    "ZJ1005": "Cepillo de nylon para monodisco TP43 G",
    "ZJ1006": "Plato de goma para monodisco CM4050",
    "ZJ1007": "Cepillo de nylon para monodisco CM4050",
    "ZJ1009": "Cepillo de nylon para abrillantadora monodisco TF33",
    "ZJ1010": "Plato de goma para abrillantadora monodisco TF33",
    "ZJ1011": "Cepillo de nylon para monodisco orbital TPO43",
    "ZJ1020": "Plato de goma para monodisco orbital TPO43",
    "ZR1001": "Boquilla completa para suelos de lavamoquetas Pequeña Sabrina",
    "ZR1002": "Boquilla completa para suelos de lavamoquetas Grande Sabrina y Grace",
    "ZR1008": "Boquilla de plástico para tapicerías",
    "ZR9032": "Cepillo de recambio para lavamoquetas Elite-Silent",
    "ZR9075": "Manguera completa para lavamoquetas Grande Sabrina y Grace",
    "ZR9076": "Kit de labios para lavamoquetas Sharon Brush",
    "ZR9082": "Gatillo completo para lavamoquetas Sabrina",
    "ZR9086": "Boquilla de aluminio para tapicerías",
    "ZR9090": "Cepillo de recambio para lavamoquetas Sharon Brush",
    "CR4026C": "Caja de servilletas plegadas en Z Tork Universal, 2 capas, 23 × 22 cm",
    "CR4029C": "Caja de servilletas plegadas en Z Tork Advanced, 2 capas, 23 × 25 cm",
    "CR4030C": "Caja de servilletas plegadas en Z Tork Flushable, 2 capas, 23 × 23 cm",
    "CR4032C": "Caja de servilletas plegadas en Z Tork Universal, 1 capa, 23 × 23 cm",
    "CR4011C": "Caja de servilletas plegadas en Z Tork Universal, 1 capa, 23 × 25 cm",
    "CR7008C": "Caja de servilletas plegadas en Z Meprolim, 2 capas, 23 × 31 cm",
    "CR1159C": "Caja de servilletas plegadas en C Tork Advanced, 2 capas, 31 × 25 cm",
    "CR1160C": "Caja de servilletas plegadas en C Tork Universal, 2 capas, 31 × 25 cm",
    "CR7015": "Dispensador Tork H2 grande de ABS grafito",
    "CR7016": "Dispensador Tork H2 mediano de ABS grafito",
    "CR7017": "Dispensador Tork H2 pequeño de sobremesa, ABS grafito",
    "CR2070": "Pack de 45 paños plegados sin tejer para desengrasado y limpieza",
    "CR2070C": "Caja de 8 packs de 45 paños plegados sin tejer para desengrasado y limpieza",
    "CR1177": "Caja de 6 bobinas azules de papel Tork, 612 servicios",
    "CR2069": "Caja de 6 bobinas Nature de papel Tork, 612 servicios",
    "CR1010C": "Caja de 8 rollos de papel para camilla Tork Universal, 1 capa, 0,59 × 50 m",
    "CR1063C": "Caja de 2 rollos de papel para camilla Tork Universal, 1 capa, 0,59 × 185 m",
    "CR7007C": "Caja de 6 rollos de papel para camilla Tork Universal, 2 capas, 0,59 × 70 m",
    "CR1130C": "Caja de 6 rollos de papel para camilla Tork Universal, 2 capas, 0,6 × 5 m",
    "CR1170C": "Caja de 8 packs de 40 paños Tork Premium azules sin tejer",
    "CR1171C": "Caja de 8 packs de 40 paños Tork Premium verdes sin tejer",
    "CR1172C": "Caja de 8 packs de 40 paños Tork Premium amarillos sin tejer",
    "CR1173C": "Caja de 8 packs de 40 paños Tork Premium rojos sin tejer",
    "CR1175": "Pack de 60 paños industriales Tork sin tejer",
    "CR4031C": "Caja de 15 packs de 250 servilletas plegadas en Z Tork Advanced verdes, 2 capas",
    "CR4038C": "Caja de 5 packs de 100 paños industriales Tork de 3 capas",
    "CR4039": "Dispensador abierto blanco para paños Tork sin tejer",
    "CR7013": "Dispensador automático Tork de papel en rollo, ABS grafito",
    "CR7014": "Dispensador manual Tork de papel en rollo, ABS grafito",
    "CR7025": "Dispensador Tork Mini Jumbo de ABS grafito para rollos de hasta Ø25 cm",
    "CR7026": "Dispensador higiénico Tork T3 de ABS grafito",
    "CR7027": "Dispensador higiénico Tork T6 de ABS grafito",
    "CR7031": "Dispensador mediano Tork de ABS grafito para papel de manos en rollo",
    "CR2060": "Dispensador doble blanco Tork SmartOne",
    "CR2063": "Dispensador blanco Tork PeakServe de gran consumo",
    "CR2039": "Papelera Tork de ABS negro para interior, 50 l",
    "CR2066": "Papelera Tork de ABS blanco para interior, 50 l",
    "CR1039C": "Caja de toallas Tork H2 Premium, 4 capas, 34 × 23 cm",
    "CR1053C": "Caja de toallas Tork H2 Advanced, 4 capas, 34 × 23 cm",
    "CR1066C": "Caja de toallas Tork H2 Advanced, 3 capas, 25,5 × 21,2 cm",
    "CR1118": "Papel higiénico doméstico Tork Premium, 2 capas, pack de 108 rollos",
    "CR1122": "Papel higiénico doméstico Tork Premium, 2 capas, 300 servicios, pack de 60 rollos",
    "CR1155": "Papel higiénico doméstico Tork, 2 capas, 200 servicios, pack de 108 rollos",
    "CR2061": "Dispensador doble Tork SmartOne de ABS grafito",
    "CR7028": "Dispensador Tork SmartOne de ABS grafito",
    "CR7029": "Dispensador Tork SmartOne Mini de ABS grafito",
    "G00032": "Papel industrial Ecolabel de 2 capas, caja de 6 rollos",
    "G00044": "Papel industrial azul Ecolabel de 2 capas",
    "G00048": "Papel industrial Ecolabel de 1 capa",
    "CK0062": "Hair & Body Wash, gel para cabello y cuerpo, caja de 6 cartuchos de 1 l",
    "CK0062D": "Hair & Body Wash, gel para cabello y cuerpo, cartucho de 1 l",
    "CK0092": "Refresh Luxury 3 en 1, gel para cabello y cuerpo, caja de 6 cartuchos de 1 l",
    "CK0092D": "Refresh Luxury 3 en 1, gel para cabello y cuerpo, cartucho de 1 l",
    "FS0015": "Tapa con asa para cubeta de policarbonato GN 1/2",
    "FS0027": "Tapa con asa para cubeta de policarbonato GN 1/2",
    "FS0025": "Tapa con asa para cubeta de policarbonato GN 1/1",
    "BX1150": "Kit de instalación para 2 equipos EasyMix, caudal de 4 l/min",
    "BX1154": "Kit de instalación para 2 equipos EasyMix, caudal de 16 l/min",
    "BX4177": "Código compartido: kit de conexión a suministro de agua / diluidor Ecomix Mini-F",
    "ZY2016": "Disco metálico ML1 para terrazo, mármol y Waterfire, grano 60",
    "ZY2017": "Disco verde ML2 para terrazo, mármol y Waterfire, grano 120",
    "ZY2018": "Disco verde oscuro ML3 para terrazo, mármol y Waterfire, grano 220",
    "ZY2019": "Disco negro ML4 para terrazo, mármol y Waterfire, grano 440",
    "ZY2020": "Disco rojo ML5 para terrazo, mármol y Waterfire, grano 800",
    "ZY2021": "Disco amarillo ML6 para terrazo, mármol y Waterfire, grano 1500",
    "ZY3019": "Endurecedor de cemento Hardner concentrado, bidón de 5 kg",
    "ZY3029": "Endurecedor de cemento Hardner, bidón de 1.000 kg",
    "ZY3029D": "Endurecedor de cemento Hardner, bidón de 5 kg",
    "ZY5011": "Kit de 3 discos completos para abujardar, Ø200 mm",
    "ZY5012": "Kit de 3 discos completos para abujardar, Ø240 mm",
    "ZY5013": "Rodillo suelto de púas grandes para abujardar",
    "ZY5014": "Rodillo suelto de púas estándar para abujardar",
    "ZY5113": "Disco de lija Ø14 cm, grano 36, terminal cerámica, pack de 30 uds.",
    "ZY5114": "Disco de lija Ø14 cm, grano 60, terminal papel, pack de 30 uds.",
    "ZY5115": "Disco de lija Ø14 cm, grano 80, terminal papel, pack de 30 uds.",
    "ZY5116": "Disco de lija Ø14 cm, grano 100, terminal papel, pack de 30 uds.",
    "ZY5062": "Disco de lija Ø16 cm, grano 36, terminal papel",
    "ZY5063": "Disco de lija Ø24 cm, grano 36, terminal papel",
    "ZY5064": "Disco de lija Ø36 cm, grano 36, terminal papel",
    "ZY5079": "Disco Discolux Ø24 cm",
    "ZY5080": "Disco Discolux Ø20 cm",
    "ZY5081": "Disco Discolux Ø43 cm",
    "ZY5142": "Disco Discolux Ø61 cm",
    "ZY5058": "Corona diamantada Ø240 para cemento duro DD00, grano 20",
    "ZY5059": "Corona diamantada Ø240 para cemento duro DD0, grano 40",
    "ZY5088": "Corona diamantada Ø240 para cemento duro DD1, grano 60",
    "ZY5089": "Corona diamantada Ø240 para cemento duro DD2, grano 140",
    "ZY5144": "Corona diamantada Ø240 para cemento duro TCK00, 6 segmentos",
    "ZY5048": "Corona diamantada Ø240 para cemento medio/duro/abrasivo DA1, 6 segmentos, grano 70",
    "ZY5049": "Corona diamantada Ø240 para cemento medio/duro/abrasivo DA2, 6 segmentos, grano 140",
    "ZY5050": "Corona diamantada Ø240 para cemento medio/duro/abrasivo DA00, 12 segmentos, grano 20",
    "ZY5051": "Corona diamantada Ø240 para cemento medio/duro/abrasivo DA0, 12 segmentos, grano 40",
    "ZY5082": "Corona diamantada Ø240 para cemento medio/duro/abrasivo DA00, 6 segmentos, grano 20",
    "ZY5046": "Corona diamantada Ø200 para cemento duro DA1, grano 60",
    "ZY5047": "Corona diamantada Ø200 para cemento duro DA2, grano 120",
    "ZY5083": "Corona diamantada Ø200 para cemento duro DA00, grano 20",
    "ZY5090": "Corona diamantada Ø200 para cemento duro DA0, grano 40",
    "ZY5145": "Corona diamantada Ø200 para cemento duro DA00, 1 segmento, grano 20, caja de 9 uds.",
    "ZY5054": "Corona diamantada Ø240 para granito y gres CF00, 12 segmentos, grano 20",
    "ZY5108": "Corona diamantada Ø240 para granito y gres GS0, 6 segmentos, grano 40",
    "ZY5110": "Corona diamantada Ø240 para granito y gres CD0, 6 segmentos, grano 40",
    "ZY5149": "Corona diamantada Ø240 para granito y gres CD1, 6 segmentos, grano 240",
    "ZY5150": "Corona diamantada Ø240 para granito y gres CD2, 6 segmentos, grano 240",
    "ZY5056": "Corona diamantada Ø200 para cemento duro DD00, grano 20",
    "ZY5057": "Corona diamantada Ø200 para cemento duro DD0, grano 40",
    "ZY5060": "Corona diamantada Ø200 para cemento duro DT0, grano 40",
    # Revisión visual de fichas que conservaban encabezados, especificaciones
    # o nombres de otros elementos de la misma página en lugar del artículo.
    "AA0819": "Difusor para lavamoquetas y abrillantadora ES 420",
    "AA0009": "Soplador de superficies FB 45",
    "AA0015": "Lavamoquetas a espuma seca Carpet Foam",
    "AA0820": "Tapa de depósito con difusor para ES 420",
    "AA0821": "Motor de soplado para lavamoquetas y abrillantadora ES 420",
    "AF5001": "Plancha alveolar de goma con fondo, 150 × 100 cm",
    "AF5002": "Plancha alveolar de goma sin fondo, 150 × 100 cm",
    "AF6005": "Pieza de pavimento de caucho con círculos, 1 × 1 m",
    "AL0047": "Soporte maletero de acero inoxidable con respaldo",
    "AL0075": "Soporte maletero de acero inoxidable sin respaldo",
    "AL0065": "Papelera semicircular basculante de acero inoxidable, 30 l",
    "AL0061": "Papelera circular basculante de chapa verde, 60 l",
    "AL0062": "Papelera circular basculante de acero inoxidable, 60 l",
    "AL0064": "Papelera semicircular basculante de chapa verde, 30 l",
    "AL0070": "Papelera semicircular con cenicero, acero inoxidable forrado de poliuretano negro",
    "AL0080": "Carretilla de acero inoxidable",
    "AL0081": "Carretilla de acero inoxidable con tope delantero",
    "AL0091": "Pedal de apertura para carro de recogida selectiva AL0099",
    "AL0028": "Carro de servicio exterior modelo 640",
    "AL0038": "Carro de servicio modelo 20 con ruedas elásticas",
    "AL7000": "Carro de servicio de acero inoxidable y madera, 4 bolsas y ruedas elásticas",
    "AL8000": "Carro de servicio de acero inoxidable con mueble de madera y bandeja de 80 cm",
    "AL0102": "Papelera con tapa abatible de acero inoxidable",
    "AL1026": "Bolsa azul plastificada para medio carro AL0037",
    "AL4006": "Cordón rojo de 1,5 m para poste separador",
    "AM1008": "Pack de 10 gamuzas beige para cristales",
    "AM1009D": "Salvauñas abrasivo Scotch-Brite Hi-Pro negro",
    "AZ0022": "Bac abierto de polipropileno, 150 l",
    "AZ0085": "Palet Heavy encajable negro, carga dinámica de 250 kg",
    "AZ0087": "Bac cerrado de polipropileno, 75 l",
    "BK0065": "Recipiente para uso alimentario con ruedas, 79 l",
    "BK0080": "Recipiente para uso alimentario con ruedas, 99 l",
    "BK0103": "Tapa para contenedor redondo alimentario de 75,7 l",
    "BK0151": "Tapa para contenedor cuadrado alimentario de 106 l",
    "BK0168": "Tapa para contenedor redondo alimentario de 121,1 l",
    "BK0209": "Tapa para contenedor cuadrado alimentario de 151,4 l",
    "BK0234": "Tapa con forma opcional para contenedor basculante BK0094",
    "BA4030": "Pedal para contenedor de residuos de 800 l",
    "BE0001": "Contenedor de residuos de 800 l, cuerpo gris y tapa azul",
    "BE0005": "Papelera multiuso de polietileno de alta densidad, 50 l",
    "BE0009": "Contenedor de residuos de 120 l, cuerpo gris y tapa azul",
    "BE0010": "Contenedor de residuos de 240 l, cuerpo gris y tapa azul",
    "BE0011": "Papelera multiuso de polietileno verde o grafito, 50 l",
    "BE0015": "Contenedor de residuos completo gris claro, 1.000 l",
    "BE0016": "Contenedor de residuos completo amarillo, 360 l",
    "BE0020": "Contenedor de residuos completo azul, 120 l",
    "BE0021": "Contenedor de residuos completo amarillo, 120 l",
    "BE0022": "Contenedor de residuos completo verde, 120 l",
    "BE0023": "Contenedor de residuos completo azul, 240 l",
    "BE0024": "Contenedor de residuos completo amarillo, 240 l",
    "BE0025": "Contenedor de residuos completo verde, 240 l",
    "BE0026": "Contenedor de residuos completo azul, 800 l",
    "BE0027": "Contenedor de residuos completo verde, 800 l",
    "BE0028": "Contenedor de residuos completo amarillo, 800 l",
    "BZ1011": "Rejilla de goma para urinario o cisterna, caja de 24 uds.",
    "BZ1017": "Estropajo de acero inoxidable en bola de 20 g",
    "BZ1017D": "Bolsa de 2 estropajos de acero inoxidable en bola de 20 g",
    "BX4180": "Aquagen Frozen, limpiador de cámaras frigoríficas, bidón de 5 l",
    "BX4188": "Dermogenol, gel hidroalcohólico, bote de 500 ml con dosificador",
    "BX4190": "Solugen N, aditivo para petróleo o gasoil, bidón de 5 l",
    "BX4197": "Aquagen Plastic, limpiador de muebles de plástico y lonas, bote de 750 ml",
    "BX4196": "Adigen L, limpiador desincrustante y quitacementos, botella de 1 l",
    "BX6144": "Caja de 6 cartuchos de 800 ml de loción antiséptica Dermogen Dry",
    "CB0001": "Carro multiuso de malla metálica con tres lados",
    "CK0097": "Soporte de pie de aluminio para dosificador",
    "CL1032": "Papelera exterior con cabezal y cenicero, 92 cm",
    "CR1154": "Caja de 36 cubos de 100 pañuelos faciales Premium blancos",
    "CR2031": "Dosificador automático con sensor para cartucho de jabón de 1 l, acero inoxidable",
    "CR2065": "Soporte de pie pintado en grafito para dosificador",
    "CR4040C": "Caja de 5 packs de 50 paños Tork Premium 530 azules",
    "CR4036": "Pack de 2 rollos de papel industrial Universal azul, 2 capas",
    "CR7010": "Caja de 12 packs de 410 servilletas PeakServe de 22,5 × 20,1 cm",
    "CR1176": "Caja de 12 packs de 150 servilletas tissue vainilla de 40 × 40 cm",
    "CX0028": "Escoba de mijo con mango de madera",
    "DH0001D": "Paño de rejilla de 40 × 40 cm, unidad",
    "DH0005D": "Paño para polvo amarillo de 40 × 40 cm, unidad",
    "DH2001": "Soporte con mopa seca de 45 cm",
    "DH2002": "Soporte con mopa seca de 75 cm",
    "DH0023": "Caja de 12 paños multiuso de 50 × 60 cm",
    "DL0016": "Guantes de polietileno, caja de 100 bolsas de 100 guantes",
    "DL0016D": "Guantes de polietileno, bolsa de 100 guantes",
    "DL0017": "Guantes de vinilo desechables, talla grande - caja de 10 paquetes de 100 guantes",
    "DL0022": "Guantes de nitrilo desechables, talla pequeña - caja de 10 paquetes de 100 guantes",
    "DL0022D": "Guantes de nitrilo desechables, talla pequeña - caja de 100 guantes",
    "DL0023": "Guantes de nitrilo desechables, talla XL - caja de 10 paquetes de 100 guantes",
    "DL0023D": "Guantes de nitrilo desechables, talla XL - caja de 100 guantes",
    "DL0038": "Guantes de látex satinados, talla XXL - bolsa de 12 pares",
    "DX1014C": "Caja de 10.000 agitadores con funda",
    "DR0014": "Aparcabicicletas Arvelo VBF06 de acero pintado o cincado",
    "FC0002": "Pinza para mopa de escurridor automático",
    "FK0063": "Espejo de baño con luz de Ø20 cm",
    "FT0009": "Sistema compacto de fregado Ultra Spin Mini completo",
    "FT3013": "Rollo de 200 servicios de bayeta Microroll",
    "FR0088": "Masstech I522 para circuitos cerrados y calderas, baja espuma, bidón de 5 l",
    "FR0104": "Meprolim Limpiador neutro, bidón de 5 l",
    "FR0129": "Masslimp H-331, desinfectante base amonio cuaternario, bidón de 20 l",
    "FR0137": "Mopass Meprolim, abrillantador captador de polvo, bote de 1 l",
    "G6000": "Manguera de alta presión para hidrolimpiadora, 10 o 20 m según modelo",
    "GO0041C": "Caja de 2 packs de 500 manteles Nature de 30 × 40 cm",
    "LE0002": "Cepillo eléctrico Rotaclean Classic para limpieza de cristales",
    "LE0013": "Solución Lewi para limpieza de cristales",
    "LY0007": "Contenedor verde con pedal, 45 l",
    "LY0008": "Contenedor azul con pedal, 45 l",
    "LY0009": "Contenedor rojo con pedal, 45 l",
    "LY0021": "Cubo con prensa para fregado manual",
    "MOD1551": "Tolva de acero acoplable",
    "PL0197": "Brocha de 21 × 3 cm",
    "AK3009": "Escalera profesional de aluminio, 2 × 14 peldaños",
    "PL0312": "Salfumant Agua Fuerte, bote de 1,5 l",
    "FR0143": "Suamil, acondicionador textil Wellness Nature, bidón de 20 l",
    "MA021": "Marquesina Iris de acero reciclable y cristal",
    "ZM0027": "Kit limpiacristales completo",
    "BP4019": "Papelera Touch Bin, 50 l",
    "BC1004": "Parrilla Pritec de acero inoxidable, 40 W",
    "FT0004": "Cubo con prensa UltraSpeed Vileda, 25 l",
    "SAC002": "Manguera de extensión de 10, 15 o 20 m para equipo Sanimix 300",
    "SAC006": "Lanza con trompa de espuma para equipo Sanimix 300",
    "UM363W": "Banco Delta XXI de fundición dúctil y madera",
    "UM364": "Silla Delta XXI de fundición dúctil y madera",
    "UM364L": "Banco largo Delta de fundición dúctil y madera",
    "UM364S": "Silla Delta de fundición dúctil y madera",
    "UM398C": "Banco Central Mate de hormigón y madera",
    "VA0171": "AD Suma Nova L6, bidón de 20 l",
    "VA0172": "AD Suma Nova L6, bidón de 5 l",
    "YJ1003": "Boquilla para suelos para limpiador de vapor Tidy Vap",
    "YJ1004": "Dos cepillos redondos de cerdas de nylon para Tidy Vap",
    "YJ1005": "Cepillo opcional de planchado vertical para Tidy Vap",
    "YJ1006": "Boquilla para cristales para limpiador de vapor Tidy Vap",
    "YJ1010": "Plancha profesional opcional para limpiador de vapor Tidy Vap",
    "YG0019": "Aspirador de mochila RSV 130",
    "YG0021": "Carro de servicio profesional Nuke Eper Universal NKU32FF",
    "ZB0002": "Aspirador de polvo y líquido CA 110.2",
    "ZB1032": "Fregadora-secadora Abila 17 B",
    "ZB1032": "Fregadora-secadora Abila 17 B",
    "ZB1101": "Filtro HEPA de salida opcional para aspirador CA 15 Plus",
    "ZB1294": "Plato de goma para fregadora-secadora Abila 17 B",
    "ZB1433": "Cepillo de nylon para fregadora-secadora Abila 17 B",
    "ZB2312": "Soporte con dosificador automático y estación de pedal, 145 cm",
    "ZB2313": "Correa de hombro para pistola pulverizadora E-Spray",
    "ZC1013": "Filtro HEPA de entrada opcional para aspirador CA 15 Plus",
    "ZC9283": "Lanza con boquilla de dos vías para hidrolimpiadora",
    "ZC9322": "Filtro para aspirador de polvo y líquido FU 20.1 WD",
    "ZD0032": "Fregadora de conductor a pie",
    "ZD9478": "Kit de labios para boquilla de aspiración",
    "ZE0016": "Carro multiusos MX Top 301",
    "ZG0020": "Hidrolimpiadora PW-C 55 DP 2117 PT",
    "ZG0001": "Hidrolimpiadora monofásica de agua caliente PW-H10 Plus I1408A0 M",
    "ZG0063": "Campana limpiapiscinas para hidrolimpiadora",
    "ZG2129": "Recogemanguera opcional para hidrolimpiadora PW-C 55 DP 2117 PT",
    "ZJ0006": "Abrillantadora monodisco TF 33",
    "ZJ0002": "Monodisco de media velocidad CM 4050",
    "ZJ0005": "Monodisco de alta velocidad CM 1500 HS",
    "ZJ0010": "Monodisco TP 43 G",
    "ZJ1017": "Disco de algodón para lavamoquetas monodisco TPO 43 Spray",
    "ZJ1021": "Pad de melamina para fregadora-abrillantadora orbital Mi-Tor",
    "ZM3015": "Tubo extensible multiuso de 3 tramos, de 40 a 120 cm",
    "ZM3016": "Mango telescópico Cleano de 2 tramos, de 70 a 140 cm",
    "ZM3018": "Mango telescópico Cleano de 2 tramos, de 150 a 300 cm",
    "ZN0001": "Difusor de fragancias Basic 400",
    "AL0083": "Carro de limpieza modelo 570/3B de polipropileno",
    "BC1001": "Parrilla colgante Fanari Green de 11 W",
    "BC1003": "Parrilla Pritec inoxidable de 22 W",
    "BC1010": "Parrilla Pritec inoxidable de 30 W",
    "BX4073": "Bidón de 5 kg de suavizante líquido Suavigen Q",
    "BX4073C": "Suavizante líquido Suavigen Q — caja de 4 bidones de 5 kg",
    "BX4098": "Bidón de 20 kg de suavizante Suavigen Q",
    "BX5009": "Bidón de 5 kg de gel blanco Tensogen LB",
    "BX5016": "Bidón de 20,60 kg de detergente para carrocerías Aquagen C",
    "CR1089": "Pack de 12 rollos Mini Jumbo Tork Advanced de 2 capas, gofrados",
    "CR1106": "Caja de 6 rollos medianos Meprolim de 2 capas, gofrados",
    "CR1114": "Pack de 6 rollos higiénicos SmartOne Maxi de 2 capas",
    "CW0006": "Batería de ácido de 12 V y 110 Ah para Abila, Innova y Antea",
    "FK0007": "Secapelos Brittony blanco frontal de 1.600 W",
    "FK0020": "Secapelos Clipper Evolution negro de 1.600 W",
    "FK0082": "Secapelos Brittony negro frontal de 1.600 W",
    "FK0084": "Secapelos Brittony blanco vertical de 1.600 W",
    "YG0012": "Gancho C para mango Numatic",
    "YL0004": "Secamanos Meprolim inoxidable de 2.300 W con sensor",
    "YL0005": "Secamanos Meprolim inoxidable de 2.300 W con pulsador",
    "YL0006": "Secamanos Meprolim inoxidable de 1.500 W con sensor",
    "YL0007": "Secamanos Meprolim blanco de 1.500 W con sensor",
    "YL0008": "Secador de cabello Meprolim blanco de 1.200 W",
    "ZC1012": "Aspiradora trifásica Comac CA30S",
    "ZY0017": "Pulidora monofásica Hercules 601 VS",
    "FY0079": "Paquete de 50 platos de postre de 17 cm",
    "PL0252": "Lejía para lavadora para prendas blancas, botella de 2 l",
    "PL0284": "Lejía para lavadora para prendas de color, botella de 1 l",
    "PL0310": "Lejía para lavadora para prendas de color, botella de 2 l",
    "LE0001": "Equipo autónomo Profi Qleen completo para limpieza de cristales",
    "ZE3008": "Cubo de 15 litros",
    "ZP0019": "Dispensador Mini Jumbo de ABS transparente azul para papel de hasta Ø25 cm",
    "ZP1008": "Dispensador blanco de vasos para fuente de agua",
    "ZW1034": "Loseta entrelazada para áreas húmedas Kleen-Tile",
    "ZY5136": "Kit de abujardado especial para abrir juntas Waterfire",
}

PRESENTATION_FIXES = {
    "AF1006C": "Diseño y dimensiones a medida",
    "AF5001": "Plancha de 150 × 100 cm",
    "AF5002": "Plancha de 150 × 100 cm",
    "AF6005": "Pieza de 1 × 1 m",
    "AZ0086": "Capacidad 1.200 l; carga dinámica 1.600 kg; color verde",
    "BX4061": "Lata de 10 kg",
    "BX6067": "Botella de 1 l",
    "BX6084": "Caja de 12 botellas de 500 ml",
    "BX6085": "Caja de 12 botellas de 500 ml",
    "BX6086": "Caja de 12 botellas de 500 ml",
    "BX9035": "Caja de 16 botellas de 750 ml",
    "BX9035D": "Botella de 750 ml",
    "CS0007": "Color azul; n.º 3; Ø43 cm",
    "CS0008": "Color azul; n.º 3; Ø51 cm",
    "CS0009": "Color rojo; n.º 1; Ø43 cm",
    "CS0010": "Color rojo; n.º 1; Ø51 cm",
    "PL0285": "Botella de 2 l",
    "G6000": "Longitud de 10 o 20 m según el modelo de hidrolimpiadora",
    "ZY2016": "Modelo ML1; grano 60",
    "ZY2017": "Modelo ML2; grano 120",
    "ZY2018": "Modelo ML3; grano 220",
    "ZY2019": "Modelo ML4; grano 440",
    "ZY2020": "Modelo ML5; grano 800",
    "ZY2021": "Modelo ML6; grano 1500",
    "ZY3019": "Bidón de 5 kg",
    "ZY3029": "Bidón de 1.000 kg",
    "ZY3029D": "Bidón de 5 kg",
    "ZY5011": "Kit de 3 uds.; Ø200 mm",
    "ZY5012": "Kit de 3 uds.; Ø240 mm",
    "AL1026": "Bolsa azul plastificada para medio carro",
    "CX0081": "Fregona de microfibra bicolor blanco/azul, 155 g",
    "CX0083": "Fregona de microfibra bicolor blanco/verde, 155 g",
    "DX1003": "Caja de 20 × 50 vasos de papel de 240 ml",
    "DX1006": "Caja de 20 × 50 vasos de papel de 240 ml",
    "DX1013": "Caja de 100 packs de 100 cucharas de madera de 95 mm",
    "DX1043": "Caja de 500 vasos embolsados de 210 ml",
    "DX1055": "Caja de 50 packs de 100 cucharas de madera de 125 mm",
    "FY0079": "Paquete de 50 platos de postre de 17 cm",
    "PL0252": "Botella de 2 l para prendas blancas",
    "PL0284": "Botella de 1 l para prendas de color",
    "PL0310": "Botella de 2 l para prendas de color",
    "YG9044": "Bolsa gris de 120 l para carros Numatic YG0005/YG0006",
    "ZA1018": "Bote de 1 l para membrana",
    "ZY5110": "Caja de 3 uds.; modelo CD0; 6 segmentos; grano 40",
    "ZY5149": "Caja de 3 uds.; modelo CD1; 6 segmentos; grano 240",
    "ZY5150": "Caja de 3 uds.; modelo CD2; 6 segmentos; grano 240",
}

for _code in ("DL0001", "DL0012", "DL0013", "DL0042", "DL0017", "DL0018", "DL0019", "DL0020", "DL0021", "DL0022", "DL0023", "DL0025", "DL0026", "DL0027", "DL0037", "DL0039", "DL0040", "DL0041"):
    PRESENTATION_FIXES[_code] = "Caja de 10 paquetes de 100 guantes"
for _code in ("DL0001D", "DL0012D", "DL0013D", "DL0042D", "DL0017D", "DL0018D", "DL0019D", "DL0020D", "DL0021D", "DL0022D", "DL0023D", "DL0025D", "DL0026D", "DL0027D", "DL0039D", "DL0040D", "DL0041D"):
    PRESENTATION_FIXES[_code] = "Caja de 100 guantes"
for _code in ("DL0028", "DL0029", "DL0030", "DL0031", "DL0032", "DL0033", "DL0034", "DL0038"):
    PRESENTATION_FIXES[_code] = "Bolsa de 12 pares"
for _code in ("DL0028D", "DL0029D", "DL0030D", "DL0031D", "DL0032D", "DL0033D", "DL0034D"):
    PRESENTATION_FIXES[_code] = "1 par"
PRESENTATION_FIXES.update({
    "DL0016": "Caja de 100 bolsas de 100 guantes",
    "DL0016D": "Bolsa de 100 guantes",
})


def normalize_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKD", value or "").upper())


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFC", (value or "").replace("\u00a0", " "))
    for pattern, replacement in SPLIT_REPLACEMENTS:
        value = re.sub(pattern, replacement, value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.;:)])", r"\1", value)
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"(?<=\d)\s*[xX×]\s*(?=\d)", " × ", value)
    value = re.sub(r"(?i)(?<=\d)\s*l(?:t|ts)\.?\b", " l", value)
    value = re.sub(r"(?i)(?<=\d)\s*m(?:t|ts)\.?\b", " m", value)
    value = re.sub(r"(?i)\bc/\s*", "con ", value)
    value = re.sub(r"(?i)\bp/\s*", "para ", value)
    value = re.sub(r"(?i)\bs/circular\b", "semicircular", value)
    value = re.sub(r"(?i)\bs/escudo\b", "sin escudo", value)
    value = re.sub(r"(?i)\bs/monedero\b", "sin monedero", value)
    value = re.sub(r"(?i)\bs/olor\b", "sin olor", value)
    value = re.sub(r"(?i)\bt/basculante\b", "con tapa basculante", value)
    value = re.sub(r"(?i)\bf/séptica\b", "para fosa séptica", value)
    value = re.sub(r"(?i)\bplastico\b", "plástico", value)
    value = re.sub(r"(?i)\bharagan\b", "haragán", value)
    value = re.sub(r"(?i)\bvaiven\b", "vaivén", value)
    value = re.sub(r"(?i)\bepoxf\b", "epoxi", value)
    value = re.sub(r"(?i)\bbeignerde\b", "beige, tapa verde", value)
    value = re.sub(r"(?i)\bcontenur\b", "Contenur", value)
    value = re.sub(r"(?i)\bbidon\b", "bidón", value)
    value = re.sub(r"(?i)\bjabon\b", "jabón", value)
    value = re.sub(r"(?i)\bbacteriostatico\b", "bacteriostático", value)
    value = re.sub(r"(?i)\bdesinftectante\b", "desinfectante", value)
    value = re.sub(r"(?i)\blitr\s+o\s+s\b", "litros", value)
    value = re.sub(r"(?i)\bguií\b", "guía", value)
    value = re.sub(r"(?i)\bazuublanco\b", "azul/blanco", value)
    value = re.sub(r"(?i)\benc\.-apil\.\b", "encajable y apilable", value)
    value = re.sub(r"(?i)\bplast/pap/vidr\.\b", "plástico/papel/vidrio", value)
    value = re.sub(r"(?i)\bceston\b", "cestón", value)
    value = re.sub(r"(?i)\bovala\b", "ovalada", value)
    value = re.sub(
        r"\b(\d+(?:[.,]\d+)?)\s*(kg|ml|cm|mm|l|w|v|uds)\b",
        r"\1 \2", value, flags=re.I,
    )
    value = re.sub(r"(?i)\b(\d+(?:[.,]\d+)?)\s*cms\b", r"\1 cm", value)
    value = re.sub(r"(?i)\bc[oó]dgo\s*:\s*[A-Z0-9]+\b", "", value)
    value = re.sub(r"\b(\d+(?:[.,]\d+)?)\s+(ml|mm|cm|kg|g|l|w|v)\b", r"\1 \2", value, flags=re.I)
    value = re.sub(r"\b(\d+(?:[.,]\d+)?)\s+w\b", r"\1 W", value, flags=re.I)
    value = re.sub(r"\b(\d+(?:[.,]\d+)?)\s+v\b", r"\1 V", value, flags=re.I)
    value = re.sub(r"(?:\.\s*){2,}", ". ", value)
    return value.strip(" -\t\r\n.;")


def title_case(value: str) -> str:
    value = clean_text(value)
    if not value:
        return value
    letters = [char for char in value if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.72:
        value = value.lower().capitalize()
    for source, target in ACRONYMS.items():
        value = re.sub(rf"\b{re.escape(source)}\b", target, value, flags=re.I)
    value = re.sub(r"\bph\b", "pH", value, flags=re.I)
    value = repair.final_title_cleanup(value)
    # Los nombres se muestran como títulos en las tarjetas. La extracción de
    # varios catálogos dejaba la primera palabra en minúscula aun siendo un
    # nombre correcto (productos químicos y accesorios, sobre todo).
    if value and value[0].isalpha():
        value = value[0].upper() + value[1:]
    return value[:180]


def clean_official_title(value: str, code: str) -> str:
    value = clean_text(value)
    value = re.sub(rf"\s*[-–—]*\s*C[ÓO]DIGO\s*:?[ ]*{re.escape(code)}\s*$", "", value, flags=re.I)
    value = re.sub(rf"\s*[-–—]+\s*{re.escape(code)}\s*$", "", value, flags=re.I)
    return title_case(value)


def content_tokens(value: str) -> set[str]:
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", value.lower())
        if not unicodedata.combining(char)
    )
    aliases = {
        "aspiradora": "aspirador", "aspiradoras": "aspirador", "aspiradores": "aspirador",
        "cubeta": "cubo", "cubetas": "cubo", "cubos": "cubo",
        "recipiente": "contenedor", "recipientes": "contenedor", "contenedores": "contenedor",
        "perchas": "percha", "bayetas": "bayeta", "papeleras": "papelera",
        "fregonas": "mopa", "fregona": "mopa", "mopas": "mopa",
        "lavavidrios": "limpiacristales", "mojador": "limpiacristales",
        "metalica": "metal", "metalico": "metal", "cromada": "cromo", "cromado": "cromo",
        "limpiadora": "limpiador", "secadores": "secador", "guantes": "guante",
    }
    return {
        aliases.get(word, word)
        for word in re.findall(r"[a-z]{3,}", normalized)
        if word not in STOPWORDS
    }


def similarity(left: str, right: str) -> float:
    a, b = content_tokens(left), content_tokens(right)
    return len(a & b) / max(1, min(len(a), len(b)))


def product_tokens() -> set[str]:
    return {
        "".join(char for char in unicodedata.normalize("NFD", word) if not unicodedata.combining(char))
        for word in PRODUCT_WORDS
    }


def is_incomplete_title(value: str) -> bool:
    value = clean_text(value)
    low = value.lower()
    words = content_tokens(value)
    product_tokens = {
        "".join(char for char in unicodedata.normalize("NFD", word) if not unicodedata.combining(char))
        for word in PRODUCT_WORDS
    }
    return (
        not value or len(value) < 7
        or low in GENERIC_TITLES
        or bool(re.search(r"(?i)\b(?:de|del|la|las|el|los|y|con|sin|para|por|en|a|al)$", value))
        or bool(re.search(r"(?i)\b(?:cód|descripci[oó]n)\b", value))
        or bool(re.search(r"(?i)\b(?:c\s+ep\s+illo|p\s+lato|d\s+ep[oó]\s+sito|rec\s+ic\s+lado|c\s+ir\s+cular|skrap+p?\s+er)\b", value))
        or bool(re.search(r"(?i)^(?:con\s+chasis|carro\s+con\s+chasis)\b", value))
        or bool(re.search(r"(?i)\bprec\s+in\s+tos\b", value))
        or bool(re.search(r"(?i)^(.{8,45})\s+\1(?:\s|$)", value))
    )


def clean_section(row: dict[str, Any]) -> str:
    sections = row.get("secciones") or []
    if not sections:
        return ""
    value = repair.repair_fragmented_title(sections[0])
    substitutions = (
        (r"\babrillantador a\b", "abrillantadora"), (r"\bcarro s\b", "carros"),
        (r"\bpapel era s\b", "papeleras"), (r"\bacceso rio s\b", "accesorios"),
        (r"\bcontenedor es\b", "contenedores"), (r"\brecipiente s\b", "recipientes"),
        (r"\bsoporte s\b", "soportes"), (r"\bexterior es\b", "exteriores"),
        (r"\bba y eta s\b", "bayetas"), (r"\bf re gado\b", "fregado"),
    )
    for pattern, replacement in substitutions:
        value = re.sub(pattern, replacement, value, flags=re.I)
    return title_case(value)


def is_suspicious_presentation(value: str) -> bool:
    value = clean_text(value)
    return (
        not value or value.lower() in {"para", "cód", "código", "descripción", "cantidad", "presentación"}
        or len(value) > 130
        or bool(re.search(r"(?i)\b(?:c[oó]\s*d|descripci[oó]n)\b", value))
        or bool(re.search(r"(?:\b[A-ZÁÉÍÓÚÑ]\s+){4,}[A-ZÁÉÍÓÚÑ]\b", value))
        or bool(re.search(r"(?i)\b(?:segm\s+entos|b\s+olsas|prem\s+ium|jab\s+[óo]n)\b", value))
    )


def repair_catalog_title(row: dict[str, Any]) -> str:
    current = title_case(row.get("nombre_propuesto", ""))
    family = clean_section(row)
    presentation = clean_text(row.get("presentacion_propuesta", ""))
    if not is_incomplete_title(current):
        return current
    if family and content_tokens(current) <= content_tokens(family):
        return family
    if family:
        detail = current
        if presentation and not is_suspicious_presentation(presentation):
            detail = f"{detail} {presentation}"
        if detail and content_tokens(detail) - content_tokens(family):
            return title_case(f"{family} - {detail}")
        return family
    return current


def explicit_title_code(value: str) -> str:
    match = re.search(r"C[ÓO]DIGO\s*:?[ ]*([A-Z]{1,6}\d{2,7}[A-Z]?)", value or "", re.I)
    return normalize_code(match.group(1)) if match else ""


def official_is_mismatched(code: str, source: dict[str, Any]) -> bool:
    sku = normalize_code(source.get("sku", ""))
    title_code = explicit_title_code(source.get("title", ""))
    acceptable = {code}
    if code.endswith("C"):
        acceptable.add(code[:-1])
    return bool((sku and sku not in acceptable) or (title_code and title_code not in acceptable))


def should_use_official_title(row: dict[str, Any], source: dict[str, Any], official_title: str) -> bool:
    code = row["codigo"]
    if official_is_mismatched(code, source):
        return False
    sku = normalize_code(source.get("sku", ""))
    current = row.get("nombre_propuesto", "")
    title_code = explicit_title_code(source.get("title", ""))
    if code in PRESERVE_CATALOG_CODES:
        return False
    if code.endswith("C") and title_code == code[:-1]:
        return False
    current_words = content_tokens(current)
    official_words = content_tokens(official_title)
    official_has_product = bool(official_words & product_tokens())
    current_has_product = bool(current_words & product_tokens())
    official_is_fuller = official_has_product and (
        (not current_has_product and len(official_words) >= len(current_words))
        or (len(current_words) <= 2 and len(official_words) >= len(current_words) + 2)
    )
    return (
        sku == code or row.get("titulo_fuente") == "web_oficial" or is_incomplete_title(current)
        or official_is_fuller or similarity(current, official_title) >= 0.34
    )


class PdfContext:
    def __init__(self, codes: set[str]) -> None:
        self.documents: dict[str, fitz.Document] = {}
        self.lines: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self.codes = codes

    def page_lines(self, color: str, number: int) -> list[dict[str, Any]]:
        key = (color, number)
        if key in self.lines:
            return self.lines[key]
        if color not in self.documents:
            self.documents[color] = fitz.open(PDF_DIR / f"meprolim_revista_{color}_2024.pdf")
        page = self.documents[color][number - 1]
        result: list[dict[str, Any]] = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                raw = "".join(span.get("text", "") for span in line.get("spans", []))
                if raw.strip():
                    result.append({"raw": raw.strip(), "bbox": tuple(float(x) for x in line["bbox"])})
        self.lines[key] = result
        return result

    def row_cells(self, row: dict[str, Any]) -> str:
        code = row["codigo"]
        for source in row.get("fuentes", []):
            lines = self.page_lines(source["catalogo"], int(source["pagina"]))
            code_lines = [line for line in lines if normalize_code(line["raw"]) == code]
            if not code_lines:
                continue
            code_line = code_lines[0]
            y0 = code_line["bbox"][1]
            left_table = code_line["bbox"][0] < 290
            candidates = sorted((
                line for line in lines if line is not code_line
                and abs(line["bbox"][1] - y0) <= 4.5
                and line["bbox"][0] > code_line["bbox"][2] + 2
                and (not left_table or line["bbox"][0] < 290)
            ), key=lambda item: item["bbox"][0])
            cells: list[str] = []
            for line in candidates:
                candidate_code = normalize_code(line["raw"])
                if candidate_code in self.codes or candidate_code.startswith(code):
                    break
                text = clean_text(line["raw"])
                if text and text.lower() not in {"código", "descripcion", "descripción"}:
                    cells.append(text)
            return clean_text(" ".join(cells))[:160]
        return ""

    def close(self) -> None:
        for document in self.documents.values():
            document.close()


def derive_presentation(title: str, description: str, current: str, row_cells: str) -> str:
    raw_segments = [clean_text(item) for item in (current or "").split(";")]
    current = next((
        item for item in raw_segments
        if len(item) <= 95 and not is_suspicious_presentation(item)
        and re.search(r"(?i)^(?:caja|pack|paquete|bolsa|bote|botella|bidón|garrafa|aerosol|cubo|color|\d)", item)
    ), "")
    candidates = [current]
    cells = clean_text(row_cells)
    if not current and len(cells) <= 90 and not is_suspicious_presentation(cells) and re.search(r"(?i)\b(?:caja|pack|paquete|bolsa|bote|bid[oó]n|grano|GR\d+|color|\d+\s*(?:ml|l|kg|g|mm|cm))\b", cells):
        candidates.append(cells)
    combined = f"{title}. {description[:260]}"
    patterns = (
        r"\b(?:caja|pack|paquete|bolsa|bote|botella|bidón|garrafa|aerosol|cubo)\s+(?:de\s+)?\d+(?:[.,]\d+)?(?:\s*[×x]\s*\d+(?:[.,]\d+)?)?\s*(?:ml|l|kg|g|uds?\.?|unidades|packs?)?",
        r"\b\d+(?:[.,]\d+)?\s*[×x]\s*\d+(?:[.,]\d+)?(?:\s*[×x]\s*\d+(?:[.,]\d+)?)?\s*(?:mm|cm|m)\b",
        r"\bgrano\s+\d+\b", r"\bcolor\s+(?:amarillo|azul|rojo|verde|negro|blanco|gris|beige|marrón)\b",
    )
    for pattern in patterns:
        candidates.extend(clean_text(match.group(0)) for match in re.finditer(pattern, combined, re.I))
    unique: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if not candidate or is_suspicious_presentation(candidate):
            continue
        if any(key == item.lower() or key in item.lower() for item in unique):
            continue
        if any(item.lower() in key for item in unique):
            continue
        unique.append(candidate)
    return "; ".join(unique[:3])


def fallback_description(row: dict[str, Any]) -> str:
    first = (row.get("fuentes") or [{}])[0]
    location = ""
    if first.get("catalogo") and first.get("pagina"):
        location = f" Localizado en el catálogo {first['catalogo']}, página {first['pagina']}."
    return clean_text(f"{row['nombre_propuesto']}. Código {row['codigo']}.{location}")


def write_csv(rows: list[dict[str, Any]]) -> None:
    with CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow([
            "codigo", "nombre_o_descripcion_propuesta", "estado_validacion", "catalogos",
            "paginas", "imagen_principal", "fuentes_pagina", "observaciones",
        ])
        for row in rows:
            writer.writerow([
                row["codigo"], row["nombre_propuesto"], row.get("estado", ""),
                ", ".join(row.get("catalogos", [])), len(row.get("fuentes", [])),
                row.get("imagen_principal") or "",
                "; ".join(f"{source['catalogo']}:{source['pagina']}" for source in row.get("fuentes", [])),
                row.get("nota_conflicto", "") or "",
            ])


def audit_rows(apply_changes: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = json.loads(DATA.read_text("utf-8"))
    for row in rows:
        row["codigo"] = CODE_RENAMES.get(row["codigo"], row["codigo"])
    rows = [row for row in rows if row["codigo"] not in SPURIOUS_MODEL_CODES]
    official: dict[str, dict[str, Any]] = json.loads(OFFICIAL.read_text("utf-8"))
    repair.build_lexicon(rows)
    pdf = PdfContext({row["codigo"] for row in rows})
    changes: list[dict[str, str]] = []
    counts: Counter[str] = Counter()

    for row in rows:
        code = row["codigo"]
        family_code = code[:-1] if code.endswith("C") else code
        preserved_family = family_code in PRESERVE_CATALOG_CODES
        before = {field: row.get(field, "") for field in (
            "nombre_propuesto", "descripcion", "presentacion_propuesta", "imagen_principal"
        )}
        source = official.get(code) or {}
        official_title = clean_official_title(source.get("title", ""), code)
        use_official = bool(
            source.get("status") == "ok" and official_title
            and should_use_official_title(row, source, official_title)
        )
        incompatible_official = preserved_family or bool(
            source.get("status") == "ok" and official_title and not use_official
            and (official_is_mismatched(code, source) or code in PRESERVE_CATALOG_CODES)
        )

        if use_official:
            row["nombre_propuesto"] = official_title
            row["titulo_fuente"] = "web_oficial"
            row["estado"] = "revisado_fuente_oficial"
            counts["titulos_oficiales"] += 1
        else:
            row["nombre_propuesto"] = repair_catalog_title(row)
            row["titulo_fuente"] = "catalogo_pdf_revisado"
            row["estado"] = "revisado_catalogo"
            counts["titulos_catalogo"] += 1

        if incompatible_official and (
            row.get("imagen_fuente") == "web_oficial"
            or str(row.get("imagen_principal") or "").startswith("assets/official/")
        ):
            row["imagen_principal"] = None
            row["imagenes"] = []
            row["foto_verificada"] = False
            row.pop("imagen_fuente", None)
            counts["imagenes_incompatibles_retiradas"] += 1
        elif use_official:
            image_path = ROOT / "assets" / "official" / f"{code}.webp"
            if image_path.is_file() and not official_is_mismatched(code, source):
                relative = image_path.relative_to(ROOT).as_posix()
                row["imagen_principal"] = relative
                row["foto_verificada"] = True
                row["imagen_fuente"] = "web_oficial"
                row["imagenes"] = [{
                    "ruta": relative, "tipo": "imagen_web_oficial", "confianza": "alta",
                    "fuente": source.get("page_url"), "url_original": source.get("image_url"),
                }]

        existing_description = clean_text(row.get("descripcion", ""))
        existing_official = row.get("descripcion_fuente") == "web_oficial"
        official_description = clean_text(source.get("description", ""))
        cleaned_official_description = re.sub(
            rf"\s*SKU\s*:\s*{re.escape(code)}\s*$", "", official_description, flags=re.I
        ).strip()
        if use_official and cleaned_official_description and not official_is_mismatched(code, source):
            row["descripcion"] = cleaned_official_description
            row["descripcion_fuente"] = "web_oficial"
            counts["descripciones_oficiales"] += 1
        elif existing_description and not (existing_official and incompatible_official):
            row["descripcion"] = existing_description
            counts["descripciones_conservadas"] += 1
        else:
            row["descripcion"] = fallback_description(row)
            row["descripcion_fuente"] = "catalogo_pdf_revisado"
            counts["descripciones_conservadoras"] += 1

        override = MANUAL_OVERRIDES.get(code)
        if override:
            row.update(override)
            counts["correcciones_manuales_contrastadas"] += 1
            if code == "FR0096":
                row["fuentes"] = [
                    item for item in row.get("fuentes", [])
                    if item.get("catalogo") == "verde" and int(item.get("pagina", 0)) == 7
                ]

        fixed_title = (
            TITLE_FIXES.get(code)
            or (repair.TITLE_OVERRIDES.get(code) if code not in MANUAL_OVERRIDES else None)
            or (repair.CATEGORY_OVERRIDES.get(code) if code not in MANUAL_OVERRIDES else None)
        )
        if fixed_title:
            row.update({
                "nombre_propuesto": fixed_title,
                "descripcion": f"{fixed_title}. Código {code}.",
                "estado": "revisado_catalogo",
                "titulo_fuente": "catalogo_pdf_revisado",
                "descripcion_fuente": "catalogo_pdf_revisado",
            })
            counts["correcciones_titulos_contrastadas"] += 1
            if code == "UM530":
                row.update({
                    "descripcion": (
                        "El catálogo marrón, página 145, imprime UM530 para dos artículos: "
                        "fuente Trevi de acero zincado con imprimación epoxi, 42 × 20 × 100 cm; "
                        "y fuente Fonti de hormigón, Ø31 × 29 × 85 cm."
                    ),
                    "estado": "conflicto_catalogo",
                    "nota_conflicto": "El propio catálogo asigna UM530 a dos fuentes distintas en la misma página.",
                })
                counts["conflictos_impresos_documentados"] += 1
            elif code == "DX1050":
                row.update({
                    "descripcion": (
                        "El catálogo imprime DX1050 para dos artículos en la página 141: "
                        "caja de 20 × 50 vasos de helado Kraft de 120 ml y caja de "
                        "50 × 20 vasos de chupito transparentes de 35 ml."
                    ),
                    "estado": "conflicto_catalogo",
                    "nota_conflicto": "El propio catálogo asigna DX1050 a dos vasos distintos en la misma página.",
                })
                counts["conflictos_impresos_documentados"] += 1
            elif code == "BX1126":
                row.update({
                    "descripcion": (
                        "El catálogo verde, página 91, imprime BX1126 para dos diluidores EasyMix: "
                        "uno de 4 l/min y otro de 16 l/min."
                    ),
                    "estado": "conflicto_catalogo",
                    "nota_conflicto": "El propio catálogo asigna BX1126 a dos caudales distintos.",
                })
                counts["conflictos_impresos_documentados"] += 1
            elif code == "BX4177":
                row.update({
                    "descripcion": (
                        "El catálogo verde, página 91, imprime BX4177 para dos artículos: "
                        "un kit de conexión a suministro de agua para dos equipos y un "
                        "diluidor Ecomix Mini-F."
                    ),
                    "estado": "conflicto_catalogo",
                    "nota_conflicto": "El propio catálogo asigna BX4177 a dos artículos distintos.",
                })
                counts["conflictos_impresos_documentados"] += 1

        page_121 = PAGE_121_PRODUCTS.get(code)
        if page_121:
            title, presentation = page_121
            row.update({
                "nombre_propuesto": title,
                "descripcion": f"{title}. Código {code}. Localizado en el catálogo rojo, página 121.",
                "presentacion_propuesta": presentation,
                "estado": "revisado_catalogo",
                "titulo_fuente": "catalogo_pdf_revisado",
                "descripcion_fuente": "catalogo_pdf_revisado",
            })
            counts["correcciones_tabla_pagina_121"] += 1
        elif code == "ZY5044":
            row.update({
                "nombre_propuesto": "Código compartido: diamante metálico Ø100 BT00 / diamante trapezoidal DD00 Skraper",
                "descripcion": (
                    "El catálogo rojo, página 121, imprime ZY5044 para dos artículos: "
                    "diamante metálico Ø100 para resinas/colas/cemento BT00, grano 20, caja de 3 uds.; "
                    "y diamante trapezoidal para cemento duro DD00 Skraper, grano 40, pack de 9 uds."
                ),
                "presentacion_propuesta": "Caja de 3 uds. (BT00, grano 20) / pack de 9 uds. (DD00 Skraper, grano 40)",
                "estado": "conflicto_catalogo",
                "nota_conflicto": "El propio catálogo asigna ZY5044 a dos artículos distintos en la misma página.",
                "titulo_fuente": "catalogo_pdf_revisado",
                "descripcion_fuente": "catalogo_pdf_revisado",
            })
            counts["conflictos_impresos_documentados"] += 1

        page_122 = PAGE_122_PRODUCTS.get(code)
        if page_122:
            title, presentation = page_122
            row.update({
                "nombre_propuesto": title,
                "descripcion": f"{title}. Código {code}. Localizado en el catálogo rojo, página 122.",
                "presentacion_propuesta": presentation,
                "estado": "revisado_catalogo",
                "titulo_fuente": "catalogo_pdf_revisado",
                "descripcion_fuente": "catalogo_pdf_revisado",
            })
            counts["correcciones_tabla_pagina_122"] += 1

        row["nombre_propuesto"] = title_case(row["nombre_propuesto"])
        row["descripcion"] = clean_text(row["descripcion"])
        row["presentacion_propuesta"] = derive_presentation(
            row["nombre_propuesto"], row["descripcion"],
            row.get("presentacion_propuesta", ""), pdf.row_cells(row),
        )
        if code in {"FT1036", "FT1037", "FT1062", "FT1070"}:
            row["presentacion_propuesta"] = "Pack de 5 bayetas; caja de 20 packs"
        elif code == "FR0096":
            row["presentacion_propuesta"] = "Bidón de 5 kg"
        elif page_121:
            row["presentacion_propuesta"] = page_121[1]
        elif code == "ZY5044":
            row["presentacion_propuesta"] = "Caja de 3 uds. (BT00, grano 20) / pack de 9 uds. (DD00 Skraper, grano 40)"
        elif page_122:
            row["presentacion_propuesta"] = page_122[1]
        elif code in PRESENTATION_FIXES:
            row["presentacion_propuesta"] = PRESENTATION_FIXES[code]

        # En los resultados solo se ven el código y el nombre. Incorporar la
        # presentación de caja al título evita confundirla con la referencia
        # individual aunque ambas compartan fotografía.
        presentation = clean_text(row.get("presentacion_propuesta", ""))
        box_detail = re.search(r"(?i)\bcaja\b.*", presentation)
        if (
            box_detail
            and (code.endswith("C") or code.startswith("CU"))
            and not re.search(r"(?i)\b(?:caja|pack)\b", row["nombre_propuesto"])
        ):
            row["nombre_propuesto"] = title_case(
                f"{row['nombre_propuesto']} — {box_detail.group(0)}"
            )
        elif (
            code.startswith("CU") and code.endswith("D")
            and not re.search(r"(?i)\brollo\b", row["nombre_propuesto"])
        ):
            row["nombre_propuesto"] = title_case(f"{row['nombre_propuesto']} — rollo")

        # Las descripciones conservadoras se regeneran desde el título final;
        # así no sobreviven nombres OCR antiguos dentro de la ficha.
        if (
            row.get("descripcion_fuente") == "catalogo_pdf_revisado"
            and re.search(rf"(?i)\bCódigo\s+{re.escape(code)}\b", row.get("descripcion", ""))
        ):
            row["descripcion"] = fallback_description(row)
        row["nombre_propuesto"] = title_case(row["nombre_propuesto"])
        row["descripcion"] = clean_text(row.get("descripcion", ""))
        row["presentacion_propuesta"] = clean_text(row.get("presentacion_propuesta", ""))

        row["texto_busqueda"] = clean_text(
            f"{row['nombre_propuesto']} {code} {row['descripcion']} "
            f"{row['presentacion_propuesta']} {' '.join(row.get('catalogos', []))}"
        )
        for field, old_value in before.items():
            new_value = row.get(field, "")
            if new_value != old_value:
                changes.append({"codigo": code, "campo": field, "antes": old_value, "despues": new_value})

    pdf.close()
    report = {"total": len(rows), "counts": dict(counts), "cambios": changes}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if apply_changes:
        rows.sort(key=lambda item: item["codigo"])
        DATA.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        write_csv(rows)
        stats = json.loads(STATS.read_text("utf-8"))
        image_count = sum(bool(row.get("imagen_principal")) for row in rows)
        stats.update({
            "referencias_unicas": len(rows), "con_imagen": image_count,
            "candidatos_con_imagen": image_count,
            "referencias_espurias_o_duplicadas_corregidas": max(
                0, int(stats.get("referencias_candidatas_originales", len(rows))) - len(rows)
            ),
            "titulos_revisados_fuente_oficial": sum(
                row.get("titulo_fuente") == "web_oficial" for row in rows
            ),
            "titulos_revisados_catalogo_pdf": sum(
                row.get("titulo_fuente") == "catalogo_pdf_revisado" for row in rows
            ),
            "descripciones_fuente_oficial": sum(
                row.get("descripcion_fuente") == "web_oficial" for row in rows
            ),
            "descripciones_conservadoras": sum(
                row.get("descripcion_fuente") == "catalogo_pdf_revisado" for row in rows
            ),
            "titulos_pendientes": 0,
            "conflictos_potenciales": sum(row.get("estado") == "conflicto_catalogo" for row in rows),
            "referencias_con_conflicto_detectado": sum(row.get("estado") == "conflicto_catalogo" for row in rows),
        })
        STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = audit_rows(args.apply)
    print(json.dumps({key: value for key, value in report.items() if key != "cambios"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
