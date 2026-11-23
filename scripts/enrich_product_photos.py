#!/usr/bin/env python3
"""Añade fotografías trazables sin asociarlas por parecido visual.

Fuentes admitidas, por orden de preferencia:
1. ficha o biblioteca de medios oficial de meprolim.es con código exacto;
2. archivo oficial cuyo nombre coincide exactamente con el código;
3. imagen raster incrustada en el PDF y situada sobre/junto al marcador del
   código (distancia máxima de 40 puntos, compartida por como máximo 2 SKU).

No genera imágenes ni reutiliza fotografías entre productos distintos. Las
presentaciones unidad/caja del mismo artículo sí comparten foto, tal como se
solicitó para los códigos con sufijo C.
"""

from __future__ import annotations

import argparse
import collections
import csv
import html
import io
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import fitz
from PIL import Image, ImageStat


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "articulos.json"
CSV = ROOT / "data" / "articulos.csv"
STATS = ROOT / "data" / "estadisticas.json"
PDF_DIR = ROOT / "tmp" / "pdfs"
REPORT = PDF_DIR / "photo-enrichment-report.json"
OFFICIAL_ASSETS = ROOT / "assets" / "official"
CATALOG_ASSETS = ROOT / "assets" / "catalogo"
WP_MEDIA_CACHE = PDF_DIR / "wordpress-media.json"
WP_PRODUCTS_CACHE = PDF_DIR / "wordpress-products.json"
DIRECT_CACHE = PDF_DIR / "direct-image-candidates.json"

CATALOGS = ("verde", "gris", "rojo", "marron")
USER_AGENT = "Mozilla/5.0 MeprolimCatalogAudit/1.0"

# La web actual reutiliza estos SKU para productos diferentes de los PDF.
# Sus imágenes actuales no se pueden aplicar a la referencia histórica.
PRESERVE_CATALOG_CODES = {
    "BC1008", "BX1064", "BX3032", "BX4009", "BX4015", "BX9010",
    "DZ0008", "FR0029", "FR0104", "FR0124", "FS0030", "ZB1016", "ZG0013",
}

# El propio catálogo asigna estos códigos a dos productos distintos.
CONFLICT_CODES = {"UM530", "DX1050", "BX1126", "BX4177", "ZY5044"}

# Rechazos confirmados durante la revisión visual del 100 % de los recortes
# candidatos. Son degradados, máscaras de maquetación o fragmentos en los que
# el artículo no queda identificado de forma útil.
CATALOG_IMAGE_EXCLUSIONS = {
    "AF2004", "AF2004C", "AL4002", "BK0044", "BK0069", "CR2072", "DU0015",
    "FC0002", "LE0002", "MOD1551",
    "NKA101P", "NKA102P", "NKA103P", "NKA111U", "NKA120", "NKA130U",
    "NKA140P", "ZY1033",
}

# Fotografías de familia reutilizadas por la web oficial para referencias de
# distinto color, tamaño o incluso componentes diferentes. La fuente es
# auténtica, pero la asociación visual no permite reconocer el SKU concreto.
AMBIGUOUS_OFFICIAL_IMAGE_URLS = {
    "https://meprolim.es/wp-content/uploads/2019/08/AF2001.jpg",
    "https://meprolim.es/wp-content/uploads/2019/08/AF2005.jpg",
    "https://meprolim.es/wp-content/uploads/2019/09/AL4002.jpg",
    "https://meprolim.es/wp-content/uploads/2019/09/CU0016.jpg",
    "https://meprolim.es/wp-content/uploads/2019/09/DU0002.jpg",
    "https://meprolim.es/wp-content/uploads/2019/09/FL0001.jpg",
    "https://meprolim.es/wp-content/uploads/2019/09/FL0007.jpg",
    "https://meprolim.es/wp-content/uploads/2019/09/FL0012.jpg",
}
OFFICIAL_IMAGE_EXCLUSIONS = {"FR0031", "FR0031C"}

# Pareja que no representa unidad/caja, sino dos cubos diferentes.
DISTINCT_BASE_VARIANTS = {"CX0047/CX0047C"}

MANUAL_OFFICIAL_PDF = {
    "FT1070": {
        "url": "https://meprolim.es/wp-content/uploads/2020/08/Meprolim-2020-Revista-Novedades-WEB.pdf",
        "local": PDF_DIR / "meprolim-novedades-2020.pdf",
        "page": 38,
        "crop": (255, 180, 380, 300),
        "source": "Catálogo oficial de novedades Meprolim 2020, página 38",
    },
}


def request_bytes(url: str, timeout: int = 30, method: str = "GET") -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def request_json(url: str) -> Any:
    payload, _headers = request_bytes(url)
    return json.loads(payload.decode("utf-8"))


def fetch_paginated(endpoint: str, cache: pathlib.Path, fields: str, refresh: bool) -> list[dict]:
    if cache.is_file() and not refresh:
        return json.loads(cache.read_text("utf-8"))
    items: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"per_page": 100, "page": page, "_fields": fields})
        try:
            batch = request_json(f"{endpoint}?{query}")
        except urllib.error.HTTPError as error:
            if error.code == 400 and page > 1:
                break
            raise
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100 and page > 20:
            break
        page += 1
        time.sleep(0.08)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def normalize_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", html.unescape(value or "").upper())


def product_codes(title: str, known_codes: set[str]) -> set[str]:
    values = set(re.findall(r"\b[A-Z]{1,6}\d{2,7}[A-Z]?\b", html.unescape(title).upper()))
    return values & known_codes


def load_official_candidates(rows: list[dict], refresh: bool) -> dict[str, dict[str, str]]:
    missing = {row["codigo"] for row in rows if not row.get("imagen_principal")}
    candidates: dict[str, dict[str, str]] = {}
    media = fetch_paginated(
        "https://meprolim.es/wp-json/wp/v2/media", WP_MEDIA_CACHE,
        "id,slug,source_url,alt_text,title,media_type,mime_type", refresh,
    )
    products = fetch_paginated(
        "https://meprolim.es/wp-json/wp/v2/product", WP_PRODUCTS_CACHE,
        "id,link,slug,title,featured_media", refresh,
    )
    media_by_id = {int(item["id"]): item for item in media}

    # Una ficha oficial con el código exacto es la asociación más fuerte. La
    # imagen destacada puede ser compartida intencionadamente por tallas,
    # colores o presentaciones de la misma familia.
    for product in products:
        title = product.get("title", {}).get("rendered", "")
        featured = media_by_id.get(int(product.get("featured_media") or 0))
        if not featured or not featured.get("source_url"):
            continue
        for code in product_codes(title, missing):
            candidates[code] = {
                "url": featured["source_url"],
                "source": product.get("link", "https://meprolim.es/"),
                "kind": "imagen_ficha_web_oficial",
            }

    # Recupera medios huérfanos o de fichas eliminadas mediante título, slug o
    # nombre del archivo, siempre con igualdad exacta tras normalizar.
    for item in media:
        source_url = item.get("source_url", "")
        values = (
            item.get("slug", ""), item.get("alt_text", ""),
            item.get("title", {}).get("rendered", ""),
            pathlib.PurePosixPath(urllib.parse.urlparse(source_url).path).stem,
        )
        for value in values:
            code = normalize_code(value)
            if code in missing and code not in candidates and source_url:
                candidates[code] = {
                    "url": source_url, "source": source_url,
                    "kind": "imagen_biblioteca_web_oficial",
                }

    # Algunos archivos históricos siguen accesibles pero ya no están en el
    # índice de WordPress. Se prueban las tres carpetas que concentran el 98 %
    # de las imágenes originales y se conserva una caché reproducible.
    direct: list[list[Any]] = []
    if DIRECT_CACHE.is_file() and not refresh:
        direct = json.loads(DIRECT_CACHE.read_text("utf-8"))
    else:
        for index, code in enumerate(sorted(missing - set(candidates))):
            for year_month in ("2019/08", "2019/09", "2019/10"):
                url = f"https://meprolim.es/wp-content/uploads/{year_month}/{code}.jpg"
                try:
                    _body, headers = request_bytes(url, timeout=12, method="HEAD")
                    if headers.get("content-type", "").startswith("image/"):
                        direct.append([code, url, int(headers.get("content-length", "0") or 0)])
                        break
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                    continue
            if index and index % 100 == 0:
                time.sleep(0.15)
        DIRECT_CACHE.write_text(json.dumps(direct, ensure_ascii=False, indent=2), encoding="utf-8")
    for code, url, _size in direct:
        if code in missing and code not in candidates:
            candidates[code] = {"url": url, "source": url, "kind": "imagen_archivo_web_oficial"}

    for code in PRESERVE_CATALOG_CODES | CONFLICT_CODES | OFFICIAL_IMAGE_EXCLUSIONS:
        candidates.pop(code, None)
    candidates = {
        code: candidate for code, candidate in candidates.items()
        if candidate.get("url") not in AMBIGUOUS_OFFICIAL_IMAGE_URLS
    }
    return candidates


def decode_image(payload: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(payload))
    image.load()
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image.convert("RGBA"))
        return background.convert("RGB")
    return image.convert("RGB")


def save_webp(image: Image.Image, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if max(image.size) > 900:
        image.thumbnail((900, 900), Image.Resampling.LANCZOS)
    image.save(path, "WEBP", quality=82, method=4)


def attach_image(row: dict, path: pathlib.Path, metadata: dict[str, Any], verified: bool) -> None:
    relative = path.relative_to(ROOT).as_posix()
    entry = {"ruta": relative, **metadata}
    row["imagenes"] = [entry, *[
        image for image in row.get("imagenes", []) if image.get("ruta") != relative
    ]]
    row["imagen_principal"] = relative
    row["imagen_fuente"] = metadata.get("tipo", "")
    row["foto_verificada"] = verified


def purge_rejected_catalog_images(rows: list[dict]) -> list[str]:
    """Retira de los datos cualquier recorte descartado por control visual."""
    removed: list[str] = []
    for row in rows:
        if row["codigo"] not in CATALOG_IMAGE_EXCLUSIONS:
            continue
        if not str(row.get("imagen_principal") or "").startswith("assets/catalogo/"):
            continue
        row["imagen_principal"] = None
        row["imagenes"] = [
            image for image in row.get("imagenes", [])
            if not str(image.get("ruta") or "").startswith("assets/catalogo/")
        ]
        row["imagen_fuente"] = ""
        row["foto_verificada"] = False
        removed.append(row["codigo"])
    return removed


def purge_ambiguous_official_images(rows: list[dict]) -> list[str]:
    """Retira fotos oficiales genéricas que no identifican la variante."""
    removed: list[str] = []
    for row in rows:
        principal = str(row.get("imagen_principal") or "")
        if not principal.startswith("assets/official/"):
            continue
        current = next(
            (image for image in row.get("imagenes", []) if image.get("ruta") == principal),
            {},
        )
        ambiguous = (
            row["codigo"] in OFFICIAL_IMAGE_EXCLUSIONS
            or current.get("url_original") in AMBIGUOUS_OFFICIAL_IMAGE_URLS
        )
        if not ambiguous:
            continue
        row["imagen_principal"] = None
        row["imagenes"] = [
            image for image in row.get("imagenes", [])
            if image.get("ruta") != principal
        ]
        row["imagen_fuente"] = ""
        row["foto_verificada"] = False
        removed.append(row["codigo"])
    return removed


def apply_official_images(rows: list[dict], candidates: dict[str, dict[str, str]]) -> list[str]:
    added: list[str] = []
    by_code = {row["codigo"]: row for row in rows}
    for code, candidate in sorted(candidates.items()):
        row = by_code.get(code)
        if not row or row.get("imagen_principal"):
            continue
        try:
            payload, headers = request_bytes(candidate["url"])
            if not headers.get("content-type", "").startswith("image/") and len(payload) < 1500:
                continue
            image = decode_image(payload)
            if image.width < 80 or image.height < 80:
                continue
            target = OFFICIAL_ASSETS / f"{code}.webp"
            save_webp(image, target)
            attach_image(row, target, {
                "tipo": candidate["kind"], "confianza": "alta",
                "fuente": candidate["source"], "url_original": candidate["url"],
            }, verified=True)
            added.append(code)
        except (OSError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    return added


def apply_manual_pdf_crops(rows: list[dict]) -> list[str]:
    by_code = {row["codigo"]: row for row in rows}
    added: list[str] = []
    for code, spec in MANUAL_OFFICIAL_PDF.items():
        row = by_code.get(code)
        if not row or row.get("imagen_principal"):
            continue
        local: pathlib.Path = spec["local"]
        if not local.is_file():
            payload, _headers = request_bytes(spec["url"], timeout=45)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(payload)
        document = fitz.open(local)
        page = document[int(spec["page"]) - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), clip=fitz.Rect(spec["crop"]), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        target = OFFICIAL_ASSETS / f"{code}.webp"
        save_webp(image, target)
        attach_image(row, target, {
            "tipo": "recorte_catalogo_oficial_contrastado", "confianza": "alta",
            "fuente": spec["url"], "pagina": int(spec["page"]),
        }, verified=True)
        added.append(code)
        document.close()
    return added


def composite_pdf_image(block: dict) -> Image.Image:
    image = decode_image(block["image"])
    if block.get("mask"):
        mask = Image.open(io.BytesIO(block["mask"])).convert("L")
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.Resampling.LANCZOS)
        image = Image.composite(image, Image.new("RGB", image.size, "white"), mask)
    return image


def usable_catalog_image(image: Image.Image) -> bool:
    if image.width < 70 or image.height < 70:
        return False
    sample = image.copy()
    sample.thumbnail((160, 160), Image.Resampling.BILINEAR)
    stat = ImageStat.Stat(sample.convert("L"))
    # Elimina fondos, degradados y máscaras sin contenido fotográfico.
    return stat.stddev[0] >= 8 and sample.entropy() >= 3.2


def catalog_candidates(rows: list[dict]) -> tuple[dict[str, tuple], dict[tuple, set[str]], dict[str, fitz.Document]]:
    documents = {
        color: fitz.open(PDF_DIR / f"meprolim_revista_{color}_2024.pdf") for color in CATALOGS
    }
    picks: dict[str, tuple] = {}
    shared: dict[tuple, set[str]] = collections.defaultdict(set)
    for row in rows:
        code = row["codigo"]
        if row.get("imagen_principal") or code in CONFLICT_CODES | CATALOG_IMAGE_EXCLUSIONS:
            continue
        options: list[tuple] = []
        for source in row.get("fuentes", []):
            color = source["catalogo"]
            page_number = int(source["pagina"])
            page = documents[color][page_number - 1]
            width, height = page.rect.width, page.rect.height
            for block_index, block in enumerate(page.get_text("dict")["blocks"]):
                if block.get("type") != 1 or int(block.get("colorspace", 0)) < 3:
                    continue
                x0, y0, x1, y1 = block["bbox"]
                image_width, image_height = x1 - x0, y1 - y0
                area = image_width * image_height
                if image_width < 45 or image_height < 45 or area > width * height * 0.42:
                    continue
                for marker in source.get("marcadores", []):
                    center_x = (marker["x"] + marker["w"] / 2) / 100 * width
                    center_y = (marker["y"] + marker["h"] / 2) / 100 * height
                    delta_x = max(x0 - center_x, 0, center_x - x1)
                    delta_y = max(y0 - center_y, 0, center_y - y1)
                    distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5
                    if distance <= 40:
                        options.append((distance, area, color, page_number, block_index, block))
        if options:
            pick = min(options, key=lambda item: (item[0], item[1]))
            picks[code] = pick
            shared[(pick[2], pick[3], pick[4])].add(code)
    return picks, shared, documents


def apply_catalog_images(rows: list[dict]) -> tuple[list[str], list[str]]:
    by_code = {row["codigo"]: row for row in rows}
    picks, shared, documents = catalog_candidates(rows)
    added: list[str] = []
    rejected: list[str] = []
    for code, pick in sorted(picks.items()):
        distance, _area, color, page_number, block_index, block = pick
        family = shared[(color, page_number, block_index)]
        if len(family) > 2:
            rejected.append(code)
            continue
        try:
            image = composite_pdf_image(block)
            if not usable_catalog_image(image):
                rejected.append(code)
                continue
            target = CATALOG_ASSETS / f"{code}.webp"
            save_webp(image, target)
            attach_image(by_code[code], target, {
                "tipo": "imagen_incrustada_catalogo_por_codigo",
                "confianza": "alta" if distance == 0 and len(family) == 1 else "media_alta",
                "catalogo": color, "pagina": page_number,
                "distancia_codigo_imagen": round(distance, 2),
            }, verified=True)
            added.append(code)
        except OSError:
            rejected.append(code)
    for document in documents.values():
        document.close()
    return added, rejected


def is_box(row: dict) -> bool:
    text = f"{row.get('nombre_propuesto', '')} {row.get('presentacion_propuesta', '')}".lower()
    if re.search(r"\b(?:con|sin)\s+escurridor\b", text):
        return False
    return bool(re.search(r"\b(?:caja|pack|paquete|\d+\s+bidones|\d+\s+botes)\b", text))


def sync_unit_box_images(rows: list[dict]) -> list[str]:
    by_code = {row["codigo"]: row for row in rows}
    updated: list[str] = []
    for code, base in by_code.items():
        box = by_code.get(code + "C")
        pair = f"{code}/{code}C"
        if (
            not box
            or pair in DISTINCT_BASE_VARIANTS
            or code in CATALOG_IMAGE_EXCLUSIONS
            or box["codigo"] in CATALOG_IMAGE_EXCLUSIONS
        ):
            continue
        source = base if base.get("imagen_principal") else box if box.get("imagen_principal") else None
        if not source:
            continue
        for target in (base, box):
            if target.get("imagen_principal") != source.get("imagen_principal"):
                target["imagen_principal"] = source["imagen_principal"]
                target["imagenes"] = list(source.get("imagenes", []))
                target["imagen_fuente"] = source.get("imagen_fuente", "")
                target["foto_verificada"] = source.get("foto_verificada", False)
                updated.append(target["codigo"])
    return updated


def write_csv(rows: list[dict]) -> None:
    with CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow([
            "codigo", "nombre_o_descripcion_propuesta", "estado_validacion", "catalogos",
            "paginas", "imagen_principal", "fuentes_pagina", "observaciones",
        ])
        for row in rows:
            writer.writerow([
                row["codigo"], row["nombre_propuesto"], row.get("estado", ""),
                ",".join(row.get("catalogos", [])),
                ";".join(str(source["pagina"]) for source in row.get("fuentes", [])),
                row.get("imagen_principal") or "",
                ";".join(f"{source['catalogo']}:{source['pagina']}" for source in row.get("fuentes", [])),
                row.get("nota_conflicto", ""),
            ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Actualiza índices y sondea archivos históricos")
    args = parser.parse_args()

    rows = json.loads(DATA.read_text("utf-8"))
    visually_rejected = purge_rejected_catalog_images(rows)
    ambiguous_official = purge_ambiguous_official_images(rows)
    before = sum(bool(row.get("imagen_principal")) for row in rows)
    official_candidates = load_official_candidates(rows, args.refresh)
    official_added = apply_official_images(rows, official_candidates)
    manual_added = apply_manual_pdf_crops(rows)
    catalog_added, catalog_rejected = apply_catalog_images(rows)
    variants_updated = sync_unit_box_images(rows)
    after = sum(bool(row.get("imagen_principal")) for row in rows)

    report = {
        "referencias": len(rows), "antes_con_imagen": before, "despues_con_imagen": after,
        "cobertura_porcentaje": round(after / len(rows) * 100, 2),
        "imagenes_oficiales_nuevas": len(official_added),
        "recortes_oficiales_manuales": len(manual_added),
        "imagenes_oficiales_ambiguas_retiradas": len(ambiguous_official),
        "imagenes_catalogo_nuevas": len(catalog_added),
        "variantes_unidad_caja_sincronizadas": len(set(variants_updated)),
        "recortes_retirados_por_revision_visual": len(visually_rejected),
        "candidatos_catalogo_rechazados": len(catalog_rejected),
        "codigos_oficiales": official_added,
        "codigos_recorte_oficial": manual_added,
        "codigos_catalogo": catalog_added,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if not key.startswith("codigos_")}, ensure_ascii=False, indent=2))

    if args.apply:
        rows.sort(key=lambda row: row["codigo"])
        DATA.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        write_csv(rows)
        stats = json.loads(STATS.read_text("utf-8"))
        stats.update({
            "con_imagen": after, "candidatos_con_imagen": after,
            "referencias_sin_imagen_individual_disponible": len(rows) - after,
            "cobertura_fotografica_porcentaje": round(after / len(rows) * 100, 2),
            "imagenes_web_oficial": sum(
                str(row.get("imagen_principal") or "").startswith("assets/official/") for row in rows
            ),
            "imagenes_catalogo_asociadas_por_codigo": sum(
                str(row.get("imagen_principal") or "").startswith("assets/catalogo/") for row in rows
            ),
        })
        STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
