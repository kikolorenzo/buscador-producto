#!/usr/bin/env python3
"""Audita y mejora el catálogo usando las fuentes oficiales de MEPROLIM.

Prioridades:
1. Nombre e imagen de la ficha web oficial cuando el código coincide exactamente.
2. Encabezado, descripción, fotografía y posición extraídos del PDF oficial.
3. Marcador exacto del código en la página para conservar trazabilidad visual.

Los PDF, sitemaps y la caché web se mantienen en tmp/pdfs y no se versionan.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import fitz
import pdfplumber
from bs4 import BeautifulSoup
from PIL import Image


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "articulos.json"
CSV_PATH = ROOT / "data" / "articulos.csv"
STATS_PATH = ROOT / "data" / "estadisticas.json"
TMP = ROOT / "tmp" / "pdfs"
REPORT_PATH = TMP / "catalog-quality-report.json"
OFFICIAL_CACHE = TMP / "official-products-problematic.json"
COLORS = ("verde", "gris", "rojo", "marron")
PDF_PATHS = {color: TMP / f"meprolim_revista_{color}_2024.pdf" for color in COLORS}

COLOR_WORDS = {
    "azul",
    "rojo",
    "roja",
    "verde",
    "amarillo",
    "amarilla",
    "blanco",
    "blanca",
    "negro",
    "negra",
    "gris",
    "marron",
    "beige",
    "naranja",
    "rosa",
    "transparente",
}
GENERIC_PAGE_HEADINGS = {
    "bayetas",
    "papeleras",
    "quimicos",
    "carros",
    "accesorios",
    "complementos",
    "maquinaria",
    "recambios",
}
PRODUCT_TITLE_TERMS = {
    "accesorio", "alcohol", "alfombra", "ambientador", "aquagen", "aspirador",
    "bandeja", "bayeta", "bidon", "biofresh", "bolsa", "botella", "carro",
    "cepillo", "cesto", "contenedor", "cordon", "corona", "crema", "cubeta",
    "cubo", "degofil", "desengrasante", "desinfectante", "detergente", "diamante",
    "disco", "dispensador", "dosificador", "escobilla", "esponja", "fregadora",
    "funda", "gel", "guante", "jabon", "kit", "limpiador", "maquina", "manguera",
    "papelera", "pavimento", "pinza", "plancha", "plato", "prensa", "protector",
    "recambio", "rollo", "servilleta", "soporte", "xybac",
}
ACRONYMS = {
    "abs": "ABS",
    "appcc": "APPCC",
    "inox": "INOX",
    "pva": "PVA",
    "pvc": "PVC",
    "ph": "pH",
    "uv": "UV",
}
MANUAL_OVERRIDES = {
    "FT1062": {
        "title": "Pack de 5 bayetas PVA Micro Vileda verdes",
        "description": (
            "Bayetas recubiertas de alcohol polivinílico (PVA): limpian sin dejar rastro, "
            "se pueden lavar hasta 100 veces y miden 35 × 38 cm. Presentación: pack de 5 "
            "bayetas; caja de 20 packs."
        ),
        "presentation": "Pack de 5 bayetas",
    }
}


def normalize_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def clean_text(value: str) -> str:
    value = (value or "").replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.;:])", r"\1", value)
    value = re.sub(r"([•])\s*", r"\1 ", value)
    return value.strip(" |-\u2013\u2014")


def is_weak_title(row: dict[str, Any]) -> bool:
    name = clean_text(row.get("nombre_propuesto", ""))
    upper = name.upper()
    return (
        name == "Descripción pendiente de comprobar"
        or len(name) < 8
        or bool(re.search(r"(?:\b[A-ZÁÉÍÓÚÑ]{1,3}\s+){2,}[A-ZÁÉÍÓÚÑ]{1,3}\b", name))
        or bool(
            re.search(
                r"\b(?:AM|BLAN|NEG|NARAN|TAM|CO|LO|CHA|PA|AC|ER|RO|RECAM)\s+"
                r"[A-ZÁÉÍÓÚÑa-záéíóúñ]{1,8}\b",
                name,
            )
        )
        or upper
        in {
            "MEPROLIM",
            "ACCESORIOS",
            "ACCESORIOS OPCIONALES",
            "REC AM BIOS",
            "RECAMBIOS",
            "SOPORTE",
            "CUBETA",
            "CROMADO",
            "PROTECTOR",
            "PLÁSTICA CÓ D",
        }
    )


def format_title(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\s*[–—]\s*", " - ", value)
    if not value:
        return value
    letters = [char for char in value if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.72:
        value = value.lower().capitalize()
    words = []
    for word in value.split():
        key = word.strip(".,:;()-").lower()
        if key in ACRONYMS:
            word = word.replace(word.strip(".,:;()-"), ACRONYMS[key])
        words.append(word)
    value = " ".join(words)
    value = re.sub(r"\bpack\s+(\d+)\s+ud\.?\b", r"Pack de \1 unidades", value, flags=re.I)
    value = re.sub(r"\bpack\s+(\d+)\s+bayetas\b", r"Pack de \1 bayetas", value, flags=re.I)
    return value[:150]


def repair_spaced_ocr(value: str) -> str:
    """Une fragmentos tipográficos sin inventar el producto al que pertenecen."""
    tokens = clean_text(value).split()
    repaired: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        plain = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", token)
        if not plain:
            repaired.append(token)
            index += 1
            continue

        fragments = [token]
        cursor = index + 1
        # Una cadena que empieza por un fragmento de 1-2 letras suele ser una
        # palabra separada por el espaciado del PDF: C EP ILLO -> CEPILLO.
        if len(plain) <= 2:
            while cursor < len(tokens):
                next_token = tokens[cursor]
                next_plain = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", next_token)
                if not next_plain or any(char.isdigit() for char in next_token):
                    break
                same_case = plain.isupper() == next_plain.isupper()
                if not same_case or len(next_plain) > 5:
                    break
                fragments.append(next_token)
                cursor += 1
                if len(next_plain) >= 3:
                    break
        # También repara finales separados: SUPER IO R -> SUPERIOR.
        elif cursor < len(tokens):
            while cursor < len(tokens):
                next_token = tokens[cursor]
                next_plain = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", next_token)
                if not next_plain or len(next_plain) > 2:
                    break
                if plain.isupper() != next_plain.isupper():
                    break
                fragments.append(next_token)
                cursor += 1

        if len(fragments) > 1:
            repaired.append("".join(fragments))
            index = cursor
        else:
            repaired.append(token)
            index += 1
    return format_title(" ".join(repaired))


def explicit_product_codes(entry: dict[str, Any]) -> set[str]:
    text = f"{entry.get('title', '')} {entry.get('description', '')}".upper()
    values = re.findall(
        r"(?:C[ÓO]DIGO|SKU)\s*[:.-]?\s*([A-Z]{1,5}\d{2,6}[A-Z]?)", text
    )
    return {normalize_code(value) for value in values}


def official_is_compatible(code: str, entry: dict[str, Any] | None) -> bool:
    if not entry or entry.get("status") != "ok":
        return False
    explicit = explicit_product_codes(entry)
    allowed = {code}
    if code.endswith("C"):
        allowed.add(code[:-1])
    sku = normalize_code(entry.get("sku", ""))
    if sku:
        return sku in allowed
    return not explicit or bool(explicit & allowed)


def reliable_pdf_heading(value: str, score: float) -> bool:
    value = clean_text(value)
    letters = [char for char in value if char.isalpha()]
    uppercase_ratio = sum(char.isupper() for char in letters) / max(1, len(letters))
    words = value.split()
    translation = str.maketrans("áéíóúüñ", "aeiouun")
    normalized_words = {
        re.sub(r"[^a-z0-9]", "", word.lower().translate(translation)) for word in words
    }
    has_product_term = any(
        word in PRODUCT_TITLE_TERMS or word.rstrip("s") in PRODUCT_TITLE_TERMS
        for word in normalized_words
    )
    return (
        score < 125
        and 5 <= len(value) <= 72
        and 1 <= len(words) <= 10
        and uppercase_ratio >= 0.62
        and value.lower() not in GENERIC_PAGE_HEADINGS
        and value.upper() not in {"ACCESORIOS OPCIONALES", "USAR SIEMPRE ESTOS ANTIESPUMANTES EN EL DEPÓSITO DE RESIDUOS"}
        and not value.endswith(".")
        and not re.search(r"\b[A-Z]{1,5}\d{3,6}[A-Z]?\b", value.upper())
        and has_product_term
    )


def rect_distance(rect: tuple[float, float, float, float], point: tuple[float, float]) -> float:
    x0, y0, x1, y1 = rect
    x, y = point
    dx = max(x0 - x, 0, x - x1)
    dy = max(y0 - y, 0, y - y1)
    return math.hypot(dx * 1.2, dy)


def overlap_ratio(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0 = max(a[0], b[0])
    x1 = min(a[2], b[2])
    return max(0.0, x1 - x0) / max(1.0, min(a[2] - a[0], b[2] - b[0]))


def line_clusters(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        target = next((row for row in reversed(rows[-5:]) if abs(row[0]["top"] - word["top"]) <= 1.6), None)
        if target is None:
            rows.append([word])
        else:
            target.append(word)

    clusters: list[dict[str, Any]] = []
    for row in rows:
        row.sort(key=lambda item: item["x0"])
        parts: list[list[dict[str, Any]]] = [[]]
        for word in row:
            if parts[-1] and word["x0"] - parts[-1][-1]["x1"] > 24:
                parts.append([])
            parts[-1].append(word)
        for part in parts:
            if not part:
                continue
            text = clean_text(" ".join(word["text"] for word in part))
            bold_count = sum("bold" in word.get("fontname", "").lower() for word in part)
            clusters.append(
                {
                    "text": text,
                    "x0": min(word["x0"] for word in part),
                    "x1": max(word["x1"] for word in part),
                    "top": min(word["top"] for word in part),
                    "bottom": max(word["bottom"] for word in part),
                    "size": max(float(word.get("size", 0)) for word in part),
                    "bold": bold_count / len(part) >= 0.6,
                    "words": part,
                }
            )
    return sorted(clusters, key=lambda item: (item["top"], item["x0"]))


def heading_blocks(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headings = [
        dict(line)
        for line in lines
        if line["bold"]
        and line["size"] >= 8
        and line["top"] > 55
        and len(line["text"]) >= 4
        and not line["text"].startswith("•")
    ]
    used: set[int] = set()
    merged: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        if index in used:
            continue
        group = [heading]
        used.add(index)
        changed = True
        while changed:
            changed = False
            box = (
                min(item["x0"] for item in group),
                min(item["top"] for item in group),
                max(item["x1"] for item in group),
                max(item["bottom"] for item in group),
            )
            for other_index, other in enumerate(headings):
                if other_index in used:
                    continue
                other_box = (other["x0"], other["top"], other["x1"], other["bottom"])
                vertical_gap = other["top"] - box[3]
                if -2 <= vertical_gap <= 7 and (
                    overlap_ratio(box, other_box) >= 0.25
                    or abs((box[0] + box[2]) / 2 - (other["x0"] + other["x1"]) / 2) < 42
                ):
                    group.append(other)
                    used.add(other_index)
                    changed = True
        group.sort(key=lambda item: (item["top"], item["x0"]))
        merged.append(
            {
                "text": clean_text(" ".join(item["text"] for item in group)),
                "x0": min(item["x0"] for item in group),
                "x1": max(item["x1"] for item in group),
                "top": min(item["top"] for item in group),
                "bottom": max(item["bottom"] for item in group),
            }
        )
    return merged


def image_blocks(page: fitz.Page) -> list[dict[str, Any]]:
    blocks = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 1:
            continue
        bbox = tuple(float(value) for value in block["bbox"])
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width < 38 or height < 38 or bbox[1] < 80:
            continue
        if width > page.rect.width * 0.85 and height > page.rect.height * 0.8:
            continue
        blocks.append(
            {
                "bbox": bbox,
                "image": block["image"],
                "ext": block.get("ext", "png"),
                "pixel_width": block.get("width", 0),
                "pixel_height": block.get("height", 0),
                "outer": False,
            }
        )
    for block in blocks:
        x0, y0, x1, y1 = block["bbox"]
        for other in blocks:
            if other is block:
                continue
            a0, b0, a1, b1 = other["bbox"]
            if x0 <= a0 + 2 and y0 <= b0 + 2 and x1 >= a1 - 2 and y1 >= b1 - 2:
                area = (x1 - x0) * (y1 - y0)
                other_area = (a1 - a0) * (b1 - b0)
                if other_area < area * 0.86:
                    block["outer"] = True
                    break
    return blocks


def parse_sitemaps(codes: set[str]) -> dict[str, dict[str, str]]:
    namespace = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "im": "http://www.google.com/schemas/sitemap-image/1.1",
    }
    found: dict[str, dict[str, str]] = {}
    for name in ("product-sitemap.xml", "product-sitemap2.xml"):
        path = TMP / name
        if not path.exists():
            continue
        tree = ET.fromstring(path.read_bytes())
        for node in tree.findall("sm:url", namespace):
            page_url = node.findtext("sm:loc", default="", namespaces=namespace)
            for image in node.findall("im:image", namespace):
                image_url = image.findtext("im:loc", default="", namespaces=namespace)
                stem = pathlib.Path(urllib.parse.unquote(urllib.parse.urlparse(image_url).path)).stem.upper()
                if stem in codes:
                    found.setdefault(stem, {"page_url": page_url, "image_url": image_url})
    return found


def fetch_official_metadata(code: str, entry: dict[str, str]) -> tuple[str, dict[str, str]]:
    try:
        request = urllib.request.Request(
            entry["page_url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; MeprolimCatalogAudit/1.0)"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = response.read()
        soup = BeautifulSoup(payload, "html.parser")
        title_node = soup.select_one("h1.product_title")
        description_node = soup.select_one(".woocommerce-product-details__short-description")
        sku_node = soup.select_one(".sku")
        result = {
            "code": code,
            "page_url": entry["page_url"],
            "image_url": entry["image_url"],
            "title": clean_text(title_node.get_text(" ", strip=True) if title_node else ""),
            "description": clean_text(
                description_node.get_text(" ", strip=True) if description_node else ""
            ),
            "sku": normalize_code(sku_node.get_text(" ", strip=True) if sku_node else ""),
            "status": "ok" if title_node else "sin_titulo",
        }
        return code, result
    except Exception as error:
        return code, {
            "code": code,
            "page_url": entry["page_url"],
            "image_url": entry["image_url"],
            "status": "error",
            "error": str(error),
        }


def load_official_metadata(sitemap: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    cached = json.loads(OFFICIAL_CACHE.read_text("utf-8")) if OFFICIAL_CACHE.exists() else {}
    pending = {code: entry for code, entry in sitemap.items() if code not in cached}
    if pending:
        print(f"Completando metadatos oficiales: {len(pending)} fichas", flush=True)
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {
                executor.submit(fetch_official_metadata, code, entry): code
                for code, entry in pending.items()
            }
            for index, future in enumerate(as_completed(futures), start=1):
                code, result = future.result()
                cached[code] = result
                if index % 100 == 0 or index == len(futures):
                    print(f"Metadatos oficiales: {index}/{len(futures)}", flush=True)
        TMP.mkdir(parents=True, exist_ok=True)
        OFFICIAL_CACHE.write_text(
            json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return cached


def official_title(value: str, code: str) -> str:
    value = re.sub(
        r"\s*[–—\-\ufffd]?\s*C[ÓO]DIGO\s*:?\s*" + re.escape(code) + r"\s*$",
        "",
        value or "",
        flags=re.I,
    )
    return format_title(value)


def marker_from_bbox(
    bbox: tuple[float, float, float, float], page_width: float, page_height: float, approximate: bool
) -> dict[str, Any]:
    x0, y0, x1, y1 = bbox
    pad_x = max(3.0, (x1 - x0) * 0.12)
    pad_y = max(2.0, (y1 - y0) * 0.18)
    x0 = max(0.0, x0 - pad_x)
    y0 = max(0.0, y0 - pad_y)
    x1 = min(page_width, x1 + pad_x)
    y1 = min(page_height, y1 + pad_y)
    return {
        "x": round(x0 / page_width * 100, 3),
        "y": round(y0 / page_height * 100, 3),
        "w": round((x1 - x0) / page_width * 100, 3),
        "h": round((y1 - y0) / page_height * 100, 3),
        "aproximado": approximate,
    }


def save_embedded_image(block: dict[str, Any], color: str, page_number: int) -> str:
    digest = hashlib.sha1(block["image"]).hexdigest()[:12]
    relative = pathlib.Path("assets") / "pdf" / color / f"p{page_number}_{digest}.webp"
    target = ROOT / relative
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        image = Image.open(io.BytesIO(block["image"])).convert("RGB")
        if image.width > 800 or image.height > 800:
            image.thumbnail((800, 800), Image.Resampling.LANCZOS)
        image.save(target, "WEBP", quality=82, method=4)
    return relative.as_posix()


def save_official_image(code: str, image_url: str) -> tuple[str, str | None]:
    relative = pathlib.Path("assets") / "official" / f"{code}.webp"
    target = ROOT / relative
    if target.exists() and target.stat().st_size > 500:
        return code, relative.as_posix()
    try:
        request = urllib.request.Request(
            image_url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; MeprolimCatalogAudit/1.0)",
                "Referer": "https://meprolim.es/",
            },
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = response.read()
        image = Image.open(io.BytesIO(payload))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        image.thumbnail((900, 900), Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "WEBP", quality=82, method=4)
        return code, relative.as_posix()
    except Exception as error:  # La referencia se conserva aunque falle una imagen concreta.
        print(f"No se pudo descargar la imagen oficial de {code}: {error}", flush=True)
        return code, None


def download_official_images(sitemap: dict[str, dict[str, str]]) -> dict[str, str]:
    saved: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(save_official_image, code, entry["image_url"]): code
            for code, entry in sitemap.items()
        }
        for index, future in enumerate(as_completed(futures), start=1):
            code, path = future.result()
            if path:
                saved[code] = path
            if index % 100 == 0 or index == len(futures):
                print(f"Imágenes oficiales: {index}/{len(futures)}", flush=True)
    official_dir = ROOT / "assets" / "official"
    if official_dir.exists():
        for path in official_dir.glob("*.webp"):
            if path.stem not in sitemap:
                path.unlink()
    return saved


def write_csv(rows: list[dict[str, Any]]) -> None:
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(
            [
                "codigo",
                "nombre_o_descripcion_propuesta",
                "estado_validacion",
                "catalogos",
                "paginas",
                "imagen_principal",
                "fuentes_pagina",
                "observaciones",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["codigo"],
                    row["nombre_propuesto"],
                    row["estado"],
                    ", ".join(row["catalogos"]),
                    len(row["fuentes"]),
                    row.get("imagen_principal") or "",
                    "; ".join(
                        f"{source['catalogo']}:{source['pagina']}" for source in row["fuentes"]
                    ),
                    row.get("nota_conflicto", ""),
                ]
            )


def analyze(apply_changes: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = json.loads(DATA_PATH.read_text("utf-8"))
    weak_before_count = sum(is_weak_title(row) for row in rows)
    by_code = {row["codigo"]: row for row in rows}
    codes = set(by_code)
    sitemap = parse_sitemaps(codes)
    official = load_official_metadata(sitemap)

    sources_by_page: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in rows:
        for source in row["fuentes"]:
            sources_by_page[(source["catalogo"], source["pagina"])].add(row["codigo"])

    evidence: dict[tuple[str, int, str], dict[str, Any]] = {}
    page_models: dict[tuple[str, int], dict[str, Any]] = {}
    marker_exact = marker_approximate = 0
    pdf_images = 0

    for color in COLORS:
        pdf_path = PDF_PATHS[color]
        if not pdf_path.exists():
            raise FileNotFoundError(f"Falta el PDF oficial: {pdf_path}")
        plumber_doc = pdfplumber.open(pdf_path)
        fitz_doc = fitz.open(pdf_path)
        page_numbers = sorted(page for page_color, page in sources_by_page if page_color == color)
        for page_index, page_number in enumerate(page_numbers, start=1):
            if page_index == 1 or page_index % 40 == 0 or page_index == len(page_numbers):
                print(
                    f"Analizando catálogo {color}: página {page_index}/{len(page_numbers)} ",
                    f"(PDF {page_number})",
                    flush=True,
                )
            plumber_page = plumber_doc.pages[page_number - 1]
            fitz_page = fitz_doc[page_number - 1]
            words = plumber_page.extract_words(extra_attrs=["fontname", "size"])
            lines = line_clusters(words)
            headings = heading_blocks(lines)
            images = image_blocks(fitz_page)
            page_width = float(plumber_page.width)
            page_height = float(plumber_page.height)
            page_models[(color, page_number)] = {
                "width": page_width,
                "height": page_height,
                "lines": lines,
                "headings": headings,
                "images": images,
            }

            codes_here = sources_by_page[(color, page_number)]
            for code in codes_here:
                matches = [word for word in words if normalize_code(word["text"]) == code]
                approximate = False
                if not matches and len(code) > 4 and code[-1].isalpha():
                    base = code[:-1]
                    matches = [word for word in words if normalize_code(word["text"]) == base]
                    approximate = bool(matches)
                if not matches:
                    for line in lines:
                        if code in normalize_code(line["text"]):
                            matches.append(
                                {
                                    "text": code,
                                    "x0": line["x0"],
                                    "x1": line["x1"],
                                    "top": line["top"],
                                    "bottom": line["bottom"],
                                }
                            )
                if not matches:
                    continue

                code_word = matches[0]
                code_bbox = (
                    float(code_word["x0"]),
                    float(code_word["top"]),
                    float(code_word["x1"]),
                    float(code_word["bottom"]),
                )
                code_center = ((code_bbox[0] + code_bbox[2]) / 2, (code_bbox[1] + code_bbox[3]) / 2)

                heading_candidates = []
                for heading in headings:
                    vertical_gap = code_bbox[1] - heading["bottom"]
                    if vertical_gap < -3 or vertical_gap > 250:
                        continue
                    heading_center = (heading["x0"] + heading["x1"]) / 2
                    score = vertical_gap + abs(code_center[0] - heading_center) * 0.48
                    if clean_text(heading["text"]).lower() in GENERIC_PAGE_HEADINGS:
                        score += 85
                    heading_candidates.append((score, heading))
                heading = min(heading_candidates, default=(9999, None), key=lambda item: item[0])[1]

                image_candidates = []
                for image in images:
                    distance = rect_distance(image["bbox"], code_center)
                    x0, y0, x1, y1 = image["bbox"]
                    image_center = ((x0 + x1) / 2, (y0 + y1) / 2)
                    score = distance + math.hypot(code_center[0] - image_center[0], code_center[1] - image_center[1]) * 0.08
                    if image["outer"]:
                        score += 65
                    if score <= 165:
                        image_candidates.append((score, image))
                selected_image = min(image_candidates, default=(9999, None), key=lambda item: item[0])[1]

                color_word = None
                color_candidates = []
                for word in words:
                    normalized = clean_text(word["text"]).lower().replace("ó", "o")
                    if normalized not in COLOR_WORDS:
                        continue
                    word_center_y = (word["top"] + word["bottom"]) / 2
                    if abs(word_center_y - code_center[1]) > 14:
                        continue
                    gap = code_bbox[0] - word["x1"]
                    if -8 <= gap <= 120:
                        color_candidates.append((abs(gap) + abs(word_center_y - code_center[1]), word["text"]))
                if color_candidates:
                    color_word = min(color_candidates)[1]

                description = ""
                if heading:
                    region_x0 = min(heading["x0"], code_bbox[0]) - 24
                    region_x1 = max(heading["x1"], code_bbox[2]) + 24
                    start_y = code_bbox[3] + 8
                    if selected_image:
                        region_x0 = min(region_x0, selected_image["bbox"][0] - 10)
                        region_x1 = max(region_x1, selected_image["bbox"][2] + 10)
                        if selected_image["bbox"][3] > code_bbox[3]:
                            start_y = selected_image["bbox"][3] + 1
                    stop_y = min(
                        [
                            candidate["top"]
                            for candidate in headings
                            if candidate["top"] > start_y + 4
                            and overlap_ratio(
                                (region_x0, 0, region_x1, 1),
                                (candidate["x0"], 0, candidate["x1"], 1),
                            )
                            >= 0.18
                        ]
                        or [min(page_height - 20, start_y + 240)]
                    )
                    description_lines = []
                    for line in lines:
                        if line["bold"] or line["top"] < start_y or line["top"] >= stop_y:
                            continue
                        if overlap_ratio(
                            (region_x0, 0, region_x1, 1), (line["x0"], 0, line["x1"], 1)
                        ) < 0.18:
                            continue
                        text = clean_text(line["text"])
                        normalized = normalize_code(text)
                        if not text or normalized in codes or text.upper() in {"COLOR", "CÓDIGO"}:
                            continue
                        if line["size"] <= 10.5 and ("•" in text or len(text) > 12):
                            description_lines.append(text)
                    description = clean_text(" ".join(description_lines))[:800]

                evidence[(color, page_number, code)] = {
                    "bbox": code_bbox,
                    "approximate": approximate,
                    "markers": [
                        marker_from_bbox(
                            (
                                float(match["x0"]),
                                float(match["top"]),
                                float(match["x1"]),
                                float(match["bottom"]),
                            ),
                            page_width,
                            page_height,
                            approximate,
                        )
                        for match in matches[:4]
                    ],
                    "heading": heading["text"] if heading else "",
                    "heading_score": min((item[0] for item in heading_candidates), default=9999),
                    "color": color_word,
                    "description": description,
                    "image": selected_image,
                }
                if approximate:
                    marker_approximate += 1
                else:
                    marker_exact += 1
                if selected_image:
                    pdf_images += 1
        plumber_doc.close()
        fitz_doc.close()

    title_changes = []
    description_changes = []
    image_changes = []
    marker_sources = 0
    embedded_image_cache: dict[tuple[str, int, str], str] = {}
    approved_sitemap = {
        code: entry
        for code, entry in sitemap.items()
        if official_is_compatible(code, official.get(code)) or code in MANUAL_OVERRIDES
    }
    official_images = (
        download_official_images(approved_sitemap)
        if apply_changes
        else {code: f"assets/official/{code}.webp" for code in approved_sitemap}
    )

    for row in rows:
        code = row["codigo"]
        weak_before = is_weak_title(row)
        official_entry = official.get(code)
        official_compatible = official_is_compatible(code, official_entry)
        new_title = row["nombre_propuesto"]
        title_source = row.get("titulo_fuente")

        if official_compatible and (weak_before or title_source == "web_oficial"):
            candidate = official_title(official_entry.get("title", ""), code)
            if len(candidate) >= 8:
                new_title = candidate
                title_source = "web_oficial"
        elif weak_before:
            candidates = []
            for source in row["fuentes"]:
                item = evidence.get((source["catalogo"], source["pagina"], code))
                if not item or not item["heading"]:
                    continue
                candidate = item["heading"]
                if item["color"] and item["color"].lower() not in candidate.lower():
                    candidate = f"{candidate} - {item['color']}"
                if reliable_pdf_heading(item["heading"], item["heading_score"]):
                    candidates.append((item["heading_score"], format_title(candidate)))
            if candidates:
                score, candidate = min(candidates)
                if len(candidate) >= 8:
                    new_title = candidate
                    title_source = "catalogo_pdf"

        override = MANUAL_OVERRIDES.get(code)
        if override:
            new_title = override["title"]
            title_source = "catalogo_pdf_revisado"

        if new_title != row["nombre_propuesto"]:
            title_changes.append(
                {"codigo": code, "antes": row["nombre_propuesto"], "despues": new_title, "fuente": title_source}
            )
            row["nombre_propuesto"] = new_title
            row["titulo_fuente"] = title_source
            row["texto_busqueda"] = clean_text(f"{new_title} {row.get('texto_busqueda', '')}")

        new_description = row.get("descripcion", "")
        description_source = row.get("descripcion_fuente")
        if official_compatible:
            candidate_description = clean_text(official_entry.get("description", ""))[:800]
            if len(candidate_description) >= 18:
                new_description = candidate_description
                description_source = "web_oficial"
        if override:
            new_description = override["description"]
            description_source = "catalogo_pdf_revisado"
            row["presentacion_propuesta"] = override.get(
                "presentation", row.get("presentacion_propuesta", "")
            )
        if new_description != row.get("descripcion", ""):
            description_changes.append(
                {
                    "codigo": code,
                    "antes": row.get("descripcion", ""),
                    "despues": new_description,
                    "fuente": description_source,
                }
            )
            row["descripcion"] = new_description
            row["descripcion_fuente"] = description_source
            row["texto_busqueda"] = clean_text(
                f"{row.get('texto_busqueda', '')} {new_description}"
            )

        for source in row["fuentes"]:
            item = evidence.get((source["catalogo"], source["pagina"], code))
            if item and item["markers"]:
                source["marcadores"] = item["markers"]
                marker_sources += 1

        old_image = row.get("imagen_principal")
        safe_existing_images = [
            image
            for image in row.get("imagenes", [])
            if image.get("tipo") in {"recorte_comprobado", "imagen_usuario"}
        ]
        if code not in official_images:
            row["imagenes"] = safe_existing_images
            row["imagen_principal"] = (
                safe_existing_images[0]["ruta"] if safe_existing_images else None
            )
            row["foto_verificada"] = bool(safe_existing_images)
            row.pop("imagen_fuente", None)
        if code in official_images:
            image_path = official_images[code]
            row["imagenes"] = [
                {
                    "ruta": image_path,
                    "tipo": "imagen_web_oficial",
                    "confianza": "alta",
                    "fuente": sitemap[code]["page_url"],
                    "url_original": sitemap[code]["image_url"],
                },
                *safe_existing_images,
            ]
            row["imagen_principal"] = image_path
            row["foto_verificada"] = True
            row["imagen_fuente"] = "web_oficial"

        if row.get("imagen_principal") != old_image:
            image_changes.append(
                {"codigo": code, "antes": old_image, "despues": row.get("imagen_principal")}
            )

        if title_source == "web_oficial":
            row["estado"] = "revisado_fuente_oficial"
        elif title_source in {"catalogo_pdf", "catalogo_pdf_revisado"} and not is_weak_title(row):
            row["estado"] = "revisado_catalogo"

    weak_after = sum(is_weak_title(row) for row in rows)
    report = {
        "total_referencias": len(rows),
        "titulos_debiles_antes": weak_before_count,
        "titulos_debiles_despues": weak_after,
        "titulos_corregidos": len(title_changes),
        "descripciones_añadidas_o_corregidas": len(description_changes),
        "imagenes_cambiadas": len(image_changes),
        "codigos_con_imagen_oficial_disponible": len(sitemap),
        "fuentes_con_marcador": marker_sources,
        "marcadores_exactos": marker_exact,
        "marcadores_aproximados": marker_approximate,
        "asociaciones_imagen_pdf_candidatas": pdf_images,
        "cambios_titulos": title_changes,
        "muestras_titulos": title_changes[:100],
        "muestras_descripciones": description_changes[:30],
        "muestras_imagenes": image_changes[:50],
    }
    TMP.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if apply_changes:
        rows.sort(key=lambda row: row["codigo"])
        DATA_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        write_csv(rows)
        stats = json.loads(STATS_PATH.read_text("utf-8"))
        stats.update(
            {
                "con_imagen": sum(bool(row.get("imagen_principal")) for row in rows),
                "candidatos_con_imagen": sum(bool(row.get("imagen_principal")) for row in rows),
                "recortes_asociados_actuales": sum(len(row.get("imagenes", [])) for row in rows),
                "titulos_revisados_fuente_oficial": sum(
                    row.get("titulo_fuente") == "web_oficial" for row in rows
                ),
                "titulos_revisados_catalogo_pdf": sum(
                    row.get("titulo_fuente") == "catalogo_pdf" for row in rows
                ),
                "descripciones_extraidas_catalogo": sum(
                    row.get("descripcion_fuente") == "catalogo_pdf" for row in rows
                ),
                "fuentes_con_marcador": marker_sources,
            }
        )
        STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Escribe los cambios en data/ y assets/")
    args = parser.parse_args()
    report = analyze(args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
