#!/usr/bin/env python3
"""Reconstruye títulos desplazados leyendo la columna PRODUCTO de los PDF.

El script solo modifica referencias automáticas o pendientes. Los títulos ya
contrastados con una ficha web o revisados manualmente se conservan.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any

import pdfplumber

import audit_catalog_quality as audit


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "articulos.json"
STATS_PATH = ROOT / "data" / "estadisticas.json"
TMP = ROOT / "tmp" / "pdfs"
REPORT_PATH = TMP / "table-title-repair-report.json"
COLORS = ("verde", "gris", "rojo", "marron")
PDF_PATHS = {color: TMP / f"meprolim_revista_{color}_2024.pdf" for color in COLORS}
PROTECTED_TITLE_SOURCES = {"web_oficial", "catalogo_pdf_revisado", "manual"}
SPURIOUS_CODES = {"BIW1094", "LAX100", "LAX500", "DE100A", "DE2003", "DE250M"}
KNOWN_SPURIOUS_TOTAL = 14 + len(SPURIOUS_CODES)  # 14 falsos códigos AJA + explícitos
PRODUCT_HEADER_KEYS = {"PRODUCTO", "DESCRIPCION", "ARTICULO", "TIPOCOLOR", "MODELO"}
PAGE_PREFIXES = {"BOLSASPARACARROS": "Bolsa para carro"}

# Páginas revisadas visualmente: en ellas el PDF contiene una tabla canónica
# con una fila por código. Otras páginas mezclan fichas, fotografías y varias
# mini-tablas; aunque parezcan tabulares, no son una fuente segura para una
# corrección masiva.
TRUSTED_TABLE_PAGES = {
    ("verde", 93),   # Sucitesa / productos veganos
    ("verde", 97),   # Químicos Diversey 1
    ("verde", 98),   # Químicos Diversey 2
    ("verde", 99),   # Químicos Diversey 3
    ("verde", 137),  # Útiles de limpieza para alimentación
    ("gris", 26),    # Bolsas para carros
    ("rojo", 84),    # Baterías y cargadores
    ("rojo", 140),   # Accesorios de hidrolimpiadoras
    ("rojo", 151),   # Accesorios para limpieza con agua pura
    ("marron", 152), # Taquillas metálicas
}

KNOWN_LAYOUT_PAGES = {
    ("verde", 92),          # Configuración de equipos diluidores
    ("verde", 134),         # Bolsas pequeñas
    ("verde", 135),         # Bolsas medianas
    ("verde", 136),         # Bolsas grandes y compostables
    ("verde", 143),         # Servilletas Airlaid
    ("verde", 144),         # Servilletas punta a punta
    ("verde", 147),         # Discos de fibra sintética
    ("verde", 150),         # Discos de diamante
    ("verde", 153),         # Sistemas de abrillantado
    ("verde", 170),         # Limpiacristales y mojadores
    ("marron", 156),        # Banderas
}

MANUAL_TITLES = {
    # Etiquetas de producto impresas junto a las fotografías (págs. 171-172).
    "ZM3008": ("Terminal para tubo", "verde", 171),
    "ZM3010": ("Cierre de rosca de 25 mm", "verde", 171),
    "ZM3011": ("Cierre de rosca de 30 mm", "verde", 171),
    "ZM3007": ("Codo articulado para tubo", "verde", 172),
    "ZM0016": ("Empuñadura de acero", "verde", 172),
    "ZM1003": ("Empuñadura gris/azul ABS", "verde", 172),
    "ZM1006": ("Paquete de 10 cuchillas para cristales", "verde", 172),
    "ZM1012": ("Escobillón para paredes y techos", "verde", 172),
    "ZM1014": ("Caja de 100 cuchillas para rascador", "verde", 172),
    "ZM1025": ("Cubo multiuso de 22 l", "verde", 172),
    "ZM0012": ("Guía de acero con goma de 30 cm", "verde", 172),
    "ZM0014": ("Guía de acero con goma de 45 cm", "verde", 172),
    "ZM0015": ("Guía de acero con goma de 55 cm", "verde", 172),
    # Los siguientes códigos aparecen como compatibilidades en la tabla de
    # bolsas, pero su ficha propia confirma que son carros completos.
    "AL0011": ("Carro de servicio modelo 70 de acero inoxidable", "gris", 12),
    "AL0040": ("Carro de recogida selectiva de ropa modelo 110/3", "gris", 25),
    "AL0045": ("Carro con chasis de acero inoxidable", "marron", 93),
    "AL0089": ("Carro con tapa amarilla", "marron", 92),
    "AL2056": ("Carro con chasis cromado", "marron", 93),
    "AL7000": ("Carro inoxidable acabado madera de 4 bandejas", "gris", 26),
    "CB0002": ("Carro multiuso con tres lados, bandeja y puertas abatibles", "gris", 53),
    "FT0006": ("Carro de limpieza Vileda Voleo Pro estándar", "gris", 70),
    "YG0005": ("Carro de limpieza Numatic Eco EM1 con cubo y escurridor", "gris", 65),
    "YG0006": ("Carro de limpieza Numatic Eco EM3 con cubo y prensa", "gris", 64),
    "CU0061": ("Precinto para WC", "verde", 134),

    # Página 149: varias tablas pequeñas comparten líneas horizontales. Se
    # transcriben sus filas verificadas para evitar cruces entre columnas.
    "AM0134C": ("Caja de 5 discos brillantes de 457 mm", "verde", 149),
    "AM0134": ("Disco brillante de 457 mm", "verde", 149),
    "AM0135C": ("Caja de 5 discos brillantes de 510 mm", "verde", 149),
    "AM0135": ("Disco brillante de 510 mm", "verde", 149),
    "AM0132C": ("Caja de 5 discos rojos de 457 mm", "verde", 149),
    "AM0132": ("Disco rojo de 457 mm", "verde", 149),
    "AM0133C": ("Caja de 5 discos rojos de 510 mm", "verde", 149),
    "AM0133": ("Disco rojo de 510 mm", "verde", 149),
    "AM0029": ("Disco rojo de 330 mm", "verde", 149),
    "AM0136C": ("Caja de 5 discos negros de 457 mm", "verde", 149),
    "AM0136": ("Disco negro de 457 mm", "verde", 149),
    "AM0137C": ("Caja de 5 discos negros de 510 mm", "verde", 149),
    "AM0137": ("Disco negro de 510 mm", "verde", 149),
    "AM0108": ("Disco negro Hi-Pro de 508 mm", "verde", 149),
    "AM0106C": ("Caja de 5 discos de alta velocidad champán de 508 mm", "verde", 149),
    "AM0106": ("Disco de alta velocidad champán de 508 mm", "verde", 149),
    "AM0113C": ("Caja de 5 discos de alta velocidad rosas de 685 mm", "verde", 149),
    "AM0113": ("Disco de alta velocidad rosa de 685 mm", "verde", 149),
    "HU0001": ("Disco de melamina con abrasivo verde de 508 mm", "verde", 149),
    "HU0002": ("Disco de melamina con abrasivo rojo de 430 mm", "verde", 149),
    "AM0140": ("Disco de melamina 3M de 505 mm", "verde", 149),
    "AM0024": ("Disco decapante SPP de 330 mm", "verde", 148),
    "AM0024C": ("Caja de 10 discos decapantes SPP de 330 mm", "verde", 148),
    "AM0025": ("Disco decapante SPP de 380 mm", "verde", 148),
    "AM0025C": ("Caja de 10 discos decapantes SPP de 380 mm", "verde", 148),
    "AM0026": ("Disco decapante SPP de 406 mm", "verde", 148),
    "AM0026C": ("Caja de 10 discos decapantes SPP de 406 mm", "verde", 148),
    "AM0027": ("Disco decapante SPP de 457 mm", "verde", 148),
    "AM0027C": ("Caja de 10 discos decapantes SPP de 457 mm", "verde", 148),
    "AM0028": ("Disco decapante SPP de 508 mm", "verde", 148),
    "AM0028C": ("Caja de 10 discos decapantes SPP de 508 mm", "verde", 148),
    "BX4023": ("SUCIWAX CS · Cristalizador base", "verde", 43),
    "CR0031": ("Dispensador Mini Jumbo para papel de hasta Ø 25 cm", "marron", 16),
    "FY0033": ("Rodales de 9 cm, paquete de 250 unidades", "verde", 141),
}

TITLE_FIXES = {
    "Trasnsparente": "Transparente",
    "Taquilla metálica 1 puertas inicio 30": "Taquilla metálica 1 puerta inicio 30",
    "Taquilla metálica 1 puertas adicional 30": "Taquilla metálica 1 puerta adicional 30",
    "den -295": "DEN-295",
    "D ia mond": "Diamond",
    "P la stic": "Plastic",
    "d. guante polietileno": "Guante de polietileno",
}

PROPAGATION_EXCLUDE = {"DE100A", "FR0033C"}


def letters(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(
        char for char in decomposed if char.isascii() and char.isalpha()
    ).upper()


def normalize_title(value: str) -> str:
    value = audit.clean_text(value)
    value = re.sub(r"\s*([/,:;])\s*", r"\1 ", value)
    value = re.sub(r"\s+([.)])", r"\1", value)
    value = value.strip()
    for old, new in TITLE_FIXES.items():
        value = value.replace(old, new)
    return value


def comparison_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        "".join(char for char in decomposed if not unicodedata.combining(char)).lower(),
    ).strip()


def title_without_packaging(value: str) -> str:
    """Quita del título base el envase, que ya vive en PRESENTACIÓN."""
    value = normalize_title(value)
    value = re.sub(
        r"^(?:bid[oó]n|bote|botella|caja|paquete|pack)\s+"
        r"(?:de\s+)?(?:\d+[\d.,]*\s*(?:x\s*\d+[\d.,]*)?\s*)?"
        r"(?:kg|l|lt|ml|ud\.?|unidades?|bidones?|botes?)?\b\s*(?:de\b\s*)?",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" -·")
    value = re.sub(
        r"^(?:[.\s]*\d+[\d.,]*\s*(?:kg|l|lt|ml|cc|u|ud|b)\.?\s*)+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" .-·")
    if len(value) < 5 or re.search(r"\b(?:con|de|para|y)$", value, re.IGNORECASE):
        return ""
    if re.fullmatch(r"\d+[\d.,]*\s*(?:kg|l|lt|ml|litros?|unidades?|ud\.?)", value, re.IGNORECASE):
        return ""
    if comparison_key(value) in {
        "bidon", "bote", "botella", "caja", "paquete", "pack", "unidad",
        "caja 4 bidones 5 litros", "caja 4 bidones 5 l",
    }:
        return ""
    return value


def is_valid_product(value: str, code: str) -> bool:
    value = normalize_title(value)
    alpha = sum(char.isalpha() for char in value)
    return (
        len(value) >= 3
        and alpha >= 3
        and audit.normalize_code(value) != code
        and letters(value) not in {"PRODUCTO", "PRESENTACION", "CODIGO"}
    )


def dataset_codes_for_printed(printed_code: str, codes: set[str]) -> list[str]:
    """Incluye los sufijos sintéticos C/D/B creados por el índice anterior."""
    if printed_code in codes:
        return [printed_code]
    return sorted(
        code
        for code in codes
        if len(code) == len(printed_code) + 1
        and code[:-1] == printed_code
        and code[-1].isalpha()
    )


def find_columns(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    code_headers = [word for word in words if letters(word["text"]) == "CODIGO"]
    columns: list[dict[str, Any]] = []
    for code_header in code_headers:
        line_words = sorted(
            [word for word in words if abs(word["top"] - code_header["top"]) <= 2.5],
            key=lambda word: word["x0"],
        )
        groups: list[list[dict[str, Any]]] = []
        for word in line_words:
            if not groups or word["x0"] - groups[-1][-1]["x1"] > 15:
                groups.append([word])
            else:
                groups[-1].append(word)
        group_keys = [letters(" ".join(word["text"] for word in group)) for group in groups]
        code_group_index = next(
            (
                index
                for index, group in enumerate(groups)
                if group[0]["x0"] - 1 <= code_header["x0"] <= group[-1]["x1"] + 1
            ),
            None,
        )
        if code_group_index is None:
            continue
        product_group_index = next(
            (
                index
                for index in range(code_group_index + 1, len(groups))
                if group_keys[index] in PRODUCT_HEADER_KEYS
            ),
            None,
        )
        if product_group_index is None:
            continue
        next_code_group = next(
            (
                index
                for index in range(product_group_index + 1, len(groups))
                if group_keys[index] == "CODIGO"
            ),
            len(groups),
        )
        product_group = groups[product_group_index]
        following_groups = list(range(product_group_index + 1, next_code_group))
        product_end = (
            float(groups[following_groups[0]][0]["x0"])
            if following_groups
            else float(product_group[0]["x0"]) + 180
        )
        presentation_x = None
        presentation_end = None
        if following_groups:
            presentation_index = following_groups[0]
            presentation_x = float(groups[presentation_index][0]["x0"])
            presentation_end = (
                float(groups[following_groups[1]][0]["x0"])
                if len(following_groups) > 1
                else (
                    float(groups[next_code_group][0]["x0"])
                    if next_code_group < len(groups)
                    else presentation_x + 110
                )
            )
        heading_letters = "".join(
            letters(word["text"])
            for word in words
            if word["top"] < code_header["top"] - 3 and float(word.get("size", 0)) >= 11
        )
        prefix = next(
            (value for marker, value in PAGE_PREFIXES.items() if marker in heading_letters),
            "",
        )
        columns.append(
            {
                "header_top": float(code_header["top"]),
                "code_x": float(code_header["x0"]),
                "product_x": float(product_group[0]["x0"]),
                "product_end": product_end,
                "presentation_x": presentation_x,
                "presentation_end": presentation_end,
                "product_header": group_keys[product_group_index],
                "prefix": prefix,
            }
        )
    return columns


def words_in_region(
    words: list[dict[str, Any]], x0: float, x1: float, top: float, bottom: float
) -> list[dict[str, Any]]:
    return sorted(
        [
            word
            for word in words
            if word["x0"] >= x0 - 1.5
            and word["x1"] <= x1 + 1.5
            and word["top"] >= top - 1.5
            and word["top"] < bottom - 0.4
        ],
        key=lambda word: (round(word["top"], 1), word["x0"]),
    )


def join_region_words(words: list[dict[str, Any]]) -> str:
    if not words:
        return ""
    lines: list[list[dict[str, Any]]] = []
    for word in words:
        line = next(
            (candidate for candidate in reversed(lines[-3:]) if abs(candidate[0]["top"] - word["top"]) <= 1.8),
            None,
        )
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    text_lines = []
    for line in lines:
        line.sort(key=lambda word: word["x0"])
        text_lines.append(" ".join(word["text"] for word in line))
    return normalize_title(" ".join(text_lines))


def line_text(
    words: list[dict[str, Any]], code_word: dict[str, Any], x0: float, x1: float
) -> str:
    return normalize_title(
        " ".join(
            word["text"]
            for word in sorted(words, key=lambda item: item["x0"])
            if x0 <= float(word["x0"]) < x1
            and abs(float(word["top"]) - float(code_word["top"])) <= 5
        )
    )


def with_joined_codes(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Une códigos que el PDF separa en dos palabras (p. ej. GO + 0003)."""
    enriched = list(words)
    ordered = sorted(words, key=lambda item: (round(float(item["top"]), 1), float(item["x0"])))
    for left, right in zip(ordered, ordered[1:]):
        if (
            re.fullmatch(r"[A-Z]{1,5}", left["text"])
            and re.fullmatch(r"\d{2,7}[A-Z]?", right["text"])
            and abs(float(left["top"]) - float(right["top"])) <= 1
            and 0 <= float(right["x0"]) - float(left["x1"]) <= 5
        ):
            enriched.append(
                {
                    **left,
                    "text": left["text"] + right["text"],
                    "x1": right["x1"],
                    "bottom": max(float(left["bottom"]), float(right["bottom"])),
                }
            )
    return enriched


def top_page_title(page: pdfplumber.page.Page) -> str:
    """Reconstruye el título superior, que en los PDF viene letra a letra."""
    words = [
        word
        for word in page.extract_words(extra_attrs=["size"])
        if 30 <= float(word["top"]) <= 88
        and 115 <= float(word["x0"]) <= 465
        and float(word.get("size", 0)) >= 9
    ]
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        line = next(
            (candidate for candidate in reversed(lines[-3:]) if abs(float(candidate[0]["top"]) - float(word["top"])) <= 2),
            None,
        )
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    text_lines = []
    for line in lines:
        line.sort(key=lambda item: float(item["x0"]))
        chunks = [line[0]["text"]]
        for previous, word in zip(line, line[1:]):
            separator = " " if float(word["x0"]) - float(previous["x1"]) > 6 else ""
            chunks.append(separator + word["text"])
        text_lines.append("".join(chunks))
    value = " ".join(text_lines)
    replacements = {
        "PL�STICO": "PLÁSTICO",
        "PL�STICAS": "PLÁSTICAS",
        "QU�MICOS": "QUÍMICOS",
        "M�QUINAS": "MÁQUINAS",
        "MEDICI�N": "MEDICIÓN",
        "ASPIRACI�N": "ASPIRACIÓN",
        "RECOGIDA": "RECOGIDA",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = value.replace("�", "")
    value = value.replace("lpara", "l para").replace("productosespecíficos", "productos específicos")
    value = audit.format_title(value)
    value = value.replace("lpara", "l para").replace("productosespecíficos", "productos específicos")
    value = value.replace("Sistemaecomix", "Sistema Ecomix")
    singular_starts = {
        "Contenedores ": "Contenedor ",
        "Fuentes ": "Fuente ",
        "Bobinas ": "Bobina ",
        "Papeleras ": "Papelera ",
        "Dosificadores ": "Dosificador ",
        "Guantes ": "Guante ",
        "Cubos ": "Cubo ",
        "Vasos ": "Vaso ",
        "Bolsas ": "Bolsa ",
        "Discos ": "Disco ",
        "Carros ": "Carro ",
        "Accesorios ": "Accesorio ",
        "Recambios ": "Recambio ",
    }
    for plural, singular in singular_starts.items():
        if value.startswith(plural):
            value = singular + value[len(plural):]
            break
    exact_singular = {
        "Dosificadores": "Dosificador",
        "Papeleras": "Papelera",
        "Accesorios": "Accesorio",
        "Recambios": "Recambio",
    }
    value = exact_singular.get(value, value)
    return value


def category_fallback_title(page_title: str, presentation: str) -> str:
    presentation = audit.repair_spaced_ocr(presentation)
    replacements = {
        "Cuerpob eige": "Cuerpo beige",
        "Com pleto": "Completo",
        "Completomarrón": "Completo marrón",
        "m arrón": "marrón",
        "tapam arrón": "tapa marrón",
        "tapamarrón": "tapa marrón",
        "tapaam arilla": "tapa amarilla",
        "Prem ium": "Premium",
        "Premiumamarillo": "Premium amarillo",
        "A zul": "azul",
        "Am arillo": "amarillo",
        "N egros": "negros",
        "C aja": "Caja",
        "C artucho": "Cartucho",
        "bidonesde": "bidones de",
        "Bidónde": "Bidón de",
        "parde": "par de",
        "packsx": "packs x",
        "m adera": "madera",
        "m m": "mm",
        "m l": "ml",
    }
    for old, new in replacements.items():
        presentation = presentation.replace(old, new)
    presentation = re.sub(r"Completo(?=marrón)", "Completo ", presentation, flags=re.IGNORECASE)
    presentation = re.sub(r"tapa(?=marrón)", "tapa ", presentation, flags=re.IGNORECASE)
    presentation = re.sub(r"Premium(?=amarillo)", "Premium ", presentation, flags=re.IGNORECASE)
    presentation = re.sub(r"^aja\b", "Caja", presentation, flags=re.IGNORECASE)
    presentation = re.sub(r"^C guantes\b", "Caja de guantes", presentation, flags=re.IGNORECASE)
    if not page_title:
        return ""
    if presentation and comparison_key(presentation) not in comparison_key(page_title):
        return normalize_title(f"{page_title} - {presentation}")[:150]
    return normalize_title(page_title)[:150]


def extract_known_layout_rows(
    page: pdfplumber.page.Page,
    color: str,
    page_number: int,
    codes: set[str],
) -> dict[str, dict[str, str]]:
    """Extrae tablas revisadas que no usan la cabecera CÓDIGO/PRODUCTO."""
    words = with_joined_codes(page.extract_words())
    code_words = [
        word
        for word in words
        if re.fullmatch(r"[A-Z]{1,5}\d{2,7}[A-Z]?", audit.normalize_code(word["text"]))
    ]
    result: dict[str, dict[str, str]] = {}

    for code_word in code_words:
        printed_code = audit.normalize_code(code_word["text"])
        target_codes = dataset_codes_for_printed(printed_code, codes)
        if not target_codes:
            continue
        x = float(code_word["x0"])
        top = float(code_word["top"])
        product = ""
        presentation = ""

        if (color, page_number) == ("verde", 92) and x < 60:
            product = line_text(words, code_word, 90, 285)

        elif color == "verde" and page_number in {134, 135, 136} and x < 70:
            size = line_text(words, code_word, 115, 175)
            characteristic = line_text(words, code_word, 175, 260)
            presentation = line_text(words, code_word, 260, 390)
            if size and characteristic:
                kind = "Bolsa"
                descriptor = characteristic
                if "compost" not in comparison_key(characteristic):
                    kind = "Bolsa de plástico"
                product = f"{kind} {descriptor.lower()} de {size} cm"

        elif color == "verde" and page_number in {143, 144}:
            # En estas dos páginas las columnas son: código, embalaje,
            # estilo/color y medidas.
            bounds = None
            if 285 <= x <= 330:
                bounds = (x + 45, 422, 500, 550)
            elif page_number == 143 and x > 330 and top > 700:
                bounds = (x + 45, 456, 500, 550)
            elif page_number == 144 and 150 <= x <= 200 and 550 < top < 650:
                bounds = (x + 45, 269, 317, 360)
            elif page_number == 144 and 225 <= x <= 280 and top > 700:
                bounds = (x + 45, 348, 396, 435)
            if bounds:
                start, packaging_end, style_end, measure_end = bounds
                presentation = line_text(words, code_word, start, packaging_end)
                style = line_text(words, code_word, packaging_end, style_end)
                measure = line_text(words, code_word, style_end, measure_end)
            else:
                style = ""
                measure = ""
            if style:
                product = f"Servilleta {style}"
                if measure:
                    product += f" de {measure} cm"

        elif (color, page_number) == ("verde", 147):
            raw = line_text(words, code_word, float(code_word["x1"]) + 2, 300 if x < 300 else 555)
            raw = raw.replace("Marr�n", "Marrón")
            match = re.fullmatch(r"(Disco|Caja 5 discos)\s+(\d+)\s+(\S+)", raw)
            if match:
                kind, measure, color_name = match.groups()
                if kind == "Disco":
                    product = f"Disco {color_name.lower()} de {measure} mm"
                else:
                    plural = "marrones" if color_name.lower() == "marrón" else f"{color_name.lower()}s"
                    product = f"Caja de 5 discos {plural} de {measure} mm"

        elif (color, page_number) == ("verde", 150):
            raw = line_text(words, code_word, float(code_word["x1"]) + 2, 300 if x < 300 else 555)
            match = re.fullmatch(r"Disco de diamante sint.tico\s+(\d+)", raw, re.IGNORECASE)
            if match:
                product = f"Disco de diamante sintético de {match.group(1)} mm"

        elif (color, page_number) == ("verde", 153):
            raw = line_text(words, code_word, float(code_word["x1"]) + 2, 555)
            raw = raw.replace("N�", "N.º")
            match = re.fullmatch(r"(.+?)\s+(\d+)", raw)
            if match:
                product = f"{match.group(1)} de {match.group(2)} mm"

        elif (color, page_number) == ("marron", 156):
            boundary = 295 if x < 200 else 545
            product = line_text(words, code_word, x + 45, boundary)

        elif (color, page_number) == ("verde", 170):
            if top < 200 and 300 <= x < 400:
                length = line_text(words, code_word, 390, 430)
                product = f"Mojador de {length} cm" if length else "Mojador"
            elif top < 200 and x >= 440:
                length = line_text(words, code_word, 525, 560)
                product = f"Recambio de fibra para mojador de {length} cm" if length else "Recambio de fibra para mojador"
            elif 480 < top < 570 and x < 200:
                length = line_text(words, code_word, 190, 230)
                product = f"Limpiacristales profesional de {length} cm" if length else "Limpiacristales profesional"
            elif top > 740 and 175 <= x < 280:
                length = line_text(words, code_word, 250, 285)
                product = f"Limpiacristales con mango ABS de {length} cm" if length else "Limpiacristales con mango ABS"
            elif top > 740 and 290 <= x < 400:
                product = "Limpiacristales desechable de 30 cm"
            elif top > 740 and x > 440:
                product = "Limpiacristales desechable de 45 cm"

        if is_valid_product(product, printed_code):
            for target_code in target_codes:
                result[target_code] = {"product": product, "presentation": presentation}

    return result


def extract_page_rows(
    page: pdfplumber.page.Page, codes: set[str]
) -> dict[str, dict[str, str]]:
    words = page.extract_words(extra_attrs=["fontname", "size"])
    columns = find_columns(words)
    if not columns:
        return {}

    result: dict[str, dict[str, str]] = {}
    for column in columns:
        code_words = [
            word
            for word in words
            if word["top"] > column["header_top"] + 3
            and abs(word["x0"] - column["code_x"]) <= 13
            and re.fullmatch(
                r"[A-Z]{1,5}\d{2,7}[A-Z]?",
                audit.normalize_code(word["text"]),
            )
        ]
        code_words.sort(key=lambda word: word["top"])
        header_boundaries = sorted(
            float(word["top"])
            for word in words
            if word["top"] > column["header_top"] + 3
            and letters(word["text"]) in {"CODIGO", "PRODUCTO", "PRESENTACION"}
        )
        for index, code_word in enumerate(code_words):
            printed_code = audit.normalize_code(code_word["text"])
            target_codes = dataset_codes_for_printed(printed_code, codes)
            if not target_codes:
                continue
            next_top = (
                float(code_words[index + 1]["top"])
                if index + 1 < len(code_words)
                else min(float(page.height) - 10, float(code_word["top"]) + 18)
            )
            next_header_top = min(
                (top for top in header_boundaries if top > float(code_word["top"]) + 2),
                default=float(page.height) - 10,
            )
            # Una fila puede ocupar dos líneas, pero nunca debe invadir la fila siguiente.
            row_bottom = max(
                float(code_word["bottom"]) + 1,
                min(next_top, next_header_top),
            )
            product_words = words_in_region(
                words,
                column["product_x"],
                column["product_end"] - 3,
                float(code_word["top"]),
                row_bottom,
            )
            presentation_words = (
                words_in_region(
                    words,
                    column["presentation_x"],
                    column["presentation_end"],
                    float(code_word["top"]),
                    row_bottom,
                )
                if column["presentation_x"] is not None
                else []
            )
            product = join_region_words(product_words)
            if column.get("prefix") and comparison_key(column["prefix"]) not in comparison_key(product):
                product = f"{column['prefix']} - {product}"
            presentation = join_region_words(presentation_words)
            if is_valid_product(product, printed_code):
                # Algunas páginas repiten el código bajo una fotografía. La primera
                # aparición tras el encabezado es la fila canónica de la tabla.
                for target_code in target_codes:
                    result.setdefault(
                        target_code,
                        {
                            "product": product,
                            "presentation": presentation,
                        },
                    )
    return result


def choose_candidate(items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool]:
    if not items:
        return None, False
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[comparison_key(item["product"])].append(item)
    ordered = sorted(groups.values(), key=lambda group: (-len(group), -len(group[0]["product"])))
    conflict = len(ordered) > 1 and len(ordered[0]) == len(ordered[1])
    return ordered[0][0], conflict


def analyze(apply_changes: bool) -> dict[str, Any]:
    original_rows: list[dict[str, Any]] = json.loads(DATA_PATH.read_text("utf-8"))
    removed_rows = [
        row
        for row in original_rows
        if row["codigo"].startswith("AJA") or row["codigo"] in SPURIOUS_CODES
    ]
    rows = [row for row in original_rows if row not in removed_rows]
    codes = {row["codigo"] for row in rows}
    rows_by_code = {row["codigo"]: row for row in rows}
    sources_by_page: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in rows:
        for source in row.get("fuentes", []):
            sources_by_page[(source["catalogo"], int(source["pagina"]))].add(row["codigo"])

    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    page_titles: dict[tuple[str, int], str] = {}
    table_pages = 0
    for color in COLORS:
        path = PDF_PATHS[color]
        if not path.exists():
            raise FileNotFoundError(f"Falta el PDF oficial: {path}")
        with pdfplumber.open(path) as document:
            page_numbers = sorted(
                page for page_color, page in sources_by_page if page_color == color
            )
            for page_index, page_number in enumerate(page_numbers, start=1):
                if page_index == 1 or page_index % 40 == 0 or page_index == len(page_numbers):
                    print(
                        f"Leyendo tablas {color}: {page_index}/{len(page_numbers)}",
                        flush=True,
                    )
                page = document.pages[page_number - 1]
                page_titles[(color, page_number)] = top_page_title(page)
                if (color, page_number) not in TRUSTED_TABLE_PAGES | KNOWN_LAYOUT_PAGES:
                    continue
                if (color, page_number) in TRUSTED_TABLE_PAGES:
                    page_rows = extract_page_rows(
                        page,
                        codes,
                    )
                else:
                    page_rows = extract_known_layout_rows(
                        page,
                        color,
                        page_number,
                        codes,
                    )
                if page_rows:
                    table_pages += 1
                for code, item in page_rows.items():
                    evidence[code].append(
                        {
                            **item,
                            "catalogo": color,
                            "pagina": page_number,
                        }
                    )

    for code, (product, catalog, page_number) in MANUAL_TITLES.items():
        if code in codes:
            evidence[code].append(
                {
                    "product": product,
                    "presentation": "",
                    "catalogo": catalog,
                    "pagina": page_number,
                }
            )

    # Las variantes de caja/rollo/envase comparten el producto con el código
    # base. Esta relación evita que la presentación se convierta en el título.
    for row in rows:
        code = row["codigo"]
        if (
            code in MANUAL_TITLES
            or code in PROPAGATION_EXCLUDE
            or not audit.is_weak_title(row)
            or not code[-1:].isalpha()
        ):
            continue
        base = rows_by_code.get(code[:-1])
        if not base or audit.is_weak_title(base):
            continue
        product = title_without_packaging(base.get("nombre_propuesto", ""))
        if not product:
            continue
        source = (base.get("fuentes") or row.get("fuentes") or [{}])[0]
        if source.get("catalogo") and source.get("pagina"):
            evidence[code].append(
                {
                    "product": product,
                    "presentation": row.get("presentacion_propuesta", ""),
                    "catalogo": source["catalogo"],
                    "pagina": int(source["pagina"]),
                }
            )

    # Último recurso honesto: si no existe un nombre de fila fiable, muestra
    # la familia exacta impresa en la cabecera de su página y su variante. Se
    # mantiene el estado pendiente para no presentarlo como validación plena.
    category_fallback_codes: set[str] = set()
    for row in rows:
        if row.get("titulo_fuente") != "categoria_catalogo_pdf":
            continue
        fixed = row.get("nombre_propuesto", "")
        fixed = re.sub(r"Completo(?=marrón)", "Completo ", fixed, flags=re.IGNORECASE)
        fixed = re.sub(r"tapa(?=marrón)", "tapa ", fixed, flags=re.IGNORECASE)
        fixed = re.sub(r"Premium(?=amarillo)", "Premium ", fixed, flags=re.IGNORECASE)
        fixed = fixed.replace("productosespecíficos", "productos específicos")
        if fixed == row.get("nombre_propuesto"):
            continue
        source = (row.get("fuentes") or [{}])[0]
        if source.get("catalogo") and source.get("pagina"):
            category_fallback_codes.add(row["codigo"])
            evidence[row["codigo"]].append(
                {
                    "product": fixed,
                    "presentation": row.get("presentacion_propuesta", ""),
                    "catalogo": source["catalogo"],
                    "pagina": int(source["pagina"]),
                }
            )
    for row in rows:
        if row.get("nombre_propuesto") != "Descripción pendiente de comprobar":
            continue
        if evidence.get(row["codigo"]):
            continue
        source = next(
            (
                item
                for item in row.get("fuentes", [])
                if page_titles.get((item["catalogo"], int(item["pagina"])))
            ),
            None,
        )
        if not source:
            continue
        product = category_fallback_title(
            page_titles[(source["catalogo"], int(source["pagina"]))],
            row.get("presentacion_propuesta", ""),
        )
        if product:
            category_fallback_codes.add(row["codigo"])
            evidence[row["codigo"]].append(
                {
                    "product": product,
                    "presentation": row.get("presentacion_propuesta", ""),
                    "catalogo": source["catalogo"],
                    "pagina": int(source["pagina"]),
                }
            )

    changes: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    protected = 0
    for row in rows:
        candidate, conflict = choose_candidate(evidence.get(row["codigo"], []))
        if not candidate:
            continue
        if row.get("titulo_fuente") in PROTECTED_TITLE_SOURCES:
            protected += 1
            continue
        old_title = normalize_title(row.get("nombre_propuesto", ""))
        new_title = normalize_title(candidate["product"])
        if conflict:
            conflicts.append(
                {
                    "codigo": row["codigo"],
                    "actual": old_title,
                    "candidatos": evidence[row["codigo"]],
                }
            )
            continue
        if comparison_key(old_title) == comparison_key(new_title):
            if candidate.get("presentation") and not row.get("presentacion_propuesta"):
                row["presentacion_propuesta"] = candidate["presentation"]
            continue
        changes.append(
            {
                "codigo": row["codigo"],
                "antes": old_title,
                "despues": new_title,
                "presentacion": candidate.get("presentation", ""),
                "catalogo": candidate["catalogo"],
                "pagina": candidate["pagina"],
            }
        )
        row["nombre_propuesto"] = new_title
        if candidate.get("presentation"):
            row["presentacion_propuesta"] = candidate["presentation"]
        row["titulo_fuente"] = "catalogo_pdf_revisado"
        if row["codigo"] in category_fallback_codes:
            row["titulo_fuente"] = "categoria_catalogo_pdf"
            row["estado"] = "pendiente_revision"
        else:
            row["estado"] = "revisado_catalogo"
        row["texto_busqueda"] = audit.clean_text(
            f"{new_title} {row['codigo']} {candidate.get('presentation', '')} "
            f"{' '.join(row.get('catalogos', []))}"
        )

    report = {
        "total_referencias": len(rows),
        "referencias_espurias_eliminadas": len(removed_rows),
        "codigos_espurios_eliminados": [row["codigo"] for row in removed_rows],
        "paginas_con_tablas_detectadas": table_pages,
        "referencias_con_producto_extraido": len(evidence),
        "titulos_protegidos": protected,
        "titulos_a_corregir": len(changes),
        "conflictos_no_aplicados": len(conflicts),
        "titulos_de_categoria_para_pendientes": len(category_fallback_codes),
        "cambios": changes,
        "conflictos": conflicts,
    }
    TMP.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if apply_changes:
        rows.sort(key=lambda row: row["codigo"])
        DATA_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        audit.write_csv(rows)
        stats = json.loads(STATS_PATH.read_text("utf-8"))
        stats["referencias_unicas"] = len(rows)
        stats["referencias_espurias_eliminadas"] = KNOWN_SPURIOUS_TOTAL
        stats["titulos_pendientes"] = sum(
            row.get("nombre_propuesto") == "Descripción pendiente de comprobar" for row in rows
        )
        stats["titulos_revisados_tabla_catalogo"] = sum(
            row.get("titulo_fuente") == "catalogo_pdf_revisado" for row in rows
        )
        stats["titulos_categoria_catalogo_pdf"] = sum(
            row.get("titulo_fuente") == "categoria_catalogo_pdf" for row in rows
        )
        STATS_PATH.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = analyze(args.apply)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in {"cambios", "conflictos"}},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
