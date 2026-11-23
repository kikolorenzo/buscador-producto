#!/usr/bin/env python3
"""Verificación integral y reproducible del catálogo publicado."""

from __future__ import annotations

import csv
import json
import pathlib
import re
from collections import Counter

import fitz

import audit_catalog_quality as audit
import audit_complete_product_data as complete


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "articulos.json"
CSV = ROOT / "data" / "articulos.csv"
STATS = ROOT / "data" / "estadisticas.json"
REPORT = ROOT / "tmp" / "pdfs" / "final-verification-report.json"
PDF_DIR = ROOT / "tmp" / "pdfs"

OCR_FRAGMENT_PATTERNS = (
    r"\b(?:stru id|bosde|p illo|u eta|pensado r|vi l|cio nal|p ro|sp ira|fre gado|tu rb|rela ire|udalde)\b",
    r"\b(?:po lip|tra ctiv|nam ie|ce p|t ria|it i|p ag g|secado r|plataform a|g asas|d ig|sd i|con ce p|rol lo)\b",
    r"(?:\b[A-Za-zÀ-ÿ]\s+){4,}[A-Za-zÀ-ÿ]\b",
    r"\b(?:G\s+rande|M\s+ediana|P\s+equeña|b\s+otellas|secado\s+ra|PROF\s+ESIO\s+NAL|ta\s+xxi|del\s+ta)\b",
    r"\b(?:pap\s+el|m\s+adera|m\s+icrofibra|em\s+b\s+olsados|p\s+ostre|m\s+edio|N\s+um\s+atic|m\s+em\s+brana)\b",
    r"\b(?:[A-Z]\s+){1,3}\d(?:\s+\d){1,6}\b",
)

GENERIC_TITLE_PATTERNS = (
    r"(^| - )(?:contenedor|dispensador|papelera|aspirador(?:a|es)?|fregadora|barredora|carro de limpieza|cartuchos|recambios|complementos|coronas diamantadas|boquilla de alta presión|kit instalación|plataforma|escurridor)$",
    r"^[0-9]+\s+(?:packs?|bayetas?|papeleras?)$",
    r"^(?:Detergentes|Ambientadores|Limpiadora|Papeleras|Dispensadores|Aspiradores|Carros|Cubos|Gamuzas|Bayetas|Botellas)\b.* - ",
    r"^(?:Aja\b|arrafa\b)",
    r"\b(?:accesorios opcionales|medidas \(cm\)|potencia \(w\)|solicite presupuesto)\s*$",
)

# CX0047 y CX0047C no son unidad/caja: el catálogo muestra dos cubos
# diferentes (sin escurridor y con escurridor), cada uno con su propia foto.
ALLOWED_DISTINCT_VARIANT_IMAGES = {"CX0047/CX0047C"}


def is_spec_only_title(value: str) -> bool:
    ignored = {"negro", "blanco", "verde", "azul", "rojo", "beige", "gris", "inox", "cromo"}
    words = re.findall(r"[A-Za-zÀ-ſ]+", value.lower())
    return not any(len(word) >= 4 and word not in ignored for word in words)


def source_evidence(rows: list[dict]) -> tuple[dict[str, str], list[str]]:
    documents: dict[str, fitz.Document] = {}
    pages: dict[tuple[str, int], str] = {}
    evidence: dict[str, str] = {}
    missing: list[str] = []
    renamed_new_codes = set(complete.CODE_RENAMES.values())
    for row in rows:
        code = row["codigo"]
        result = ""
        for source in row.get("fuentes", []):
            color = source["catalogo"]
            page_number = int(source["pagina"])
            key = (color, page_number)
            if color not in documents:
                documents[color] = fitz.open(PDF_DIR / f"meprolim_revista_{color}_2024.pdf")
            if key not in pages:
                pages[key] = audit.normalize_code(documents[color][page_number - 1].get_text("text"))
            compact = pages[key]
            if code in compact:
                result = "codigo_pdf"
                break
            if code[-1:].isalpha() and code[:-1] in compact:
                result = "variante_de_codigo_base_pdf"
                break
        if not result and code in renamed_new_codes:
            result = "codigo_ocr_corregido"
        if not result and row.get("titulo_fuente") == "web_oficial":
            result = "ficha_web_oficial"
        if not result:
            missing.append(code)
        evidence[code] = result or "sin_evidencia"
    for document in documents.values():
        document.close()
    return evidence, missing


def box_pair(row: dict, base: dict) -> bool:
    box_text = f"{row.get('nombre_propuesto', '')} {row.get('presentacion_propuesta', '')}".lower()
    base_text = f"{base.get('nombre_propuesto', '')} {base.get('presentacion_propuesta', '')}".lower()
    return bool(re.search(r"\bcaja\b", box_text)) and not bool(re.search(r"\bcaja\b", base_text))

def verify() -> dict:
    rows = json.loads(DATA.read_text("utf-8"))
    with CSV.open("r", encoding="utf-8-sig", newline="") as file:
        csv_rows = list(csv.DictReader(file))
    stats = json.loads(STATS.read_text("utf-8"))
    codes = [row["codigo"] for row in rows]
    code_counts = Counter(codes)
    by_code = {row["codigo"]: row for row in rows}

    invalid_codes = sorted(code for code in codes if not re.fullmatch(r"[A-Z]{1,6}\d{2,7}[A-Z]?", code))
    duplicate_codes = sorted(code for code, count in code_counts.items() if count > 1)
    empty_titles = sorted(row["codigo"] for row in rows if not audit.clean_text(row.get("nombre_propuesto", "")))
    empty_descriptions = sorted(row["codigo"] for row in rows if not audit.clean_text(row.get("descripcion", "")))
    weak_titles = sorted(row["codigo"] for row in rows if audit.is_weak_title(row))
    broken_text = sorted(
        row["codigo"] for row in rows
        if any("\ufffd" in str(row.get(field, "")) for field in ("nombre_propuesto", "descripcion", "presentacion_propuesta"))
    )
    fragmented_text = sorted(
        row["codigo"] for row in rows
        if any(
            re.search(pattern, str(row.get(field, "")), re.IGNORECASE)
            for field in ("nombre_propuesto", "descripcion", "presentacion_propuesta")
            for pattern in OCR_FRAGMENT_PATTERNS
        )
    )
    double_spaces = sorted(
        row["codigo"] for row in rows
        if any(re.search(r"\s{2,}", str(row.get(field, ""))) for field in ("nombre_propuesto", "descripcion", "presentacion_propuesta"))
    )
    spec_only_titles = sorted(row["codigo"] for row in rows if is_spec_only_title(row.get("nombre_propuesto", "")))
    generic_titles = sorted(
        row["codigo"] for row in rows
        if any(re.search(pattern, row.get("nombre_propuesto", ""), re.IGNORECASE) for pattern in GENERIC_TITLE_PATTERNS)
    )
    lowercase_titles = sorted(
        row["codigo"] for row in rows
        if row.get("nombre_propuesto", "")[:1].islower()
    )
    incomplete_titles = sorted(
        row["codigo"] for row in rows
        if re.search(r"(?i)\b(?:de|del|la|el|con|sin|para|por|en|y|o|medio)$", row.get("nombre_propuesto", ""))
        or row.get("nombre_propuesto", "").count("(") != row.get("nombre_propuesto", "").count(")")
        or re.search(r"(?i)c[´'`]?\s*[oó]\s*digo\s*:", row.get("nombre_propuesto", ""))
    )
    search_text_mismatches = sorted(
        row["codigo"] for row in rows
        if row["codigo"].lower() not in row.get("texto_busqueda", "").lower()
        or row.get("nombre_propuesto", "").lower() not in row.get("texto_busqueda", "").lower()
    )
    stale_catalog_descriptions = sorted(
        row["codigo"] for row in rows
        if row.get("descripcion_fuente") == "catalogo_pdf_revisado"
        and re.search(rf"(?i)\bCódigo\s+{re.escape(row['codigo'])}\b", row.get("descripcion", ""))
        and not row.get("descripcion", "").startswith(row.get("nombre_propuesto", ""))
    )
    missing_sources = sorted(row["codigo"] for row in rows if not row.get("fuentes"))
    missing_image_files = sorted(
        row["codigo"] for row in rows
        if row.get("imagen_principal") and not (ROOT / row["imagen_principal"]).is_file()
    )

    pair_mismatches: list[str] = []
    pair_counts = Counter()
    for code, box in by_code.items():
        if not code.endswith("C") or code[:-1] not in by_code:
            continue
        base = by_code[code[:-1]]
        pair = f"{code[:-1]}/{code}"
        pair_counts["pareja_unidad_caja" if box_pair(box, base) else "variantes_mismo_codigo_base"] += 1
        base_image = base.get("imagen_principal")
        box_image = box.get("imagen_principal")
        if not base_image and not box_image:
            pair_counts["sin_imagen_disponible"] += 1
        elif base_image == box_image:
            pair_counts["misma_imagen"] += 1
        elif pair in ALLOWED_DISTINCT_VARIANT_IMAGES and base_image and box_image:
            pair_counts["productos_distintos_con_imagen_propia"] += 1
        else:
            pair_counts["imagen_faltante_o_distinta"] += 1
            pair_mismatches.append(pair)

    pva_expected = {
        "FT1036": "Pack de 5 bayetas PVA Micro Vileda azules",
        "FT1037": "Pack de 5 bayetas PVA Micro Vileda rojas",
        "FT1062": "Pack de 5 bayetas PVA Micro Vileda verdes",
        "FT1070": "Pack de 5 bayetas PVA Micro Vileda amarillas",
    }
    exact_title_errors = sorted(
        code for code, title in pva_expected.items()
        if code not in by_code or by_code[code].get("nombre_propuesto") != title
    )
    if by_code.get("FR0096", {}).get("nombre_propuesto") != "Gel de manos DF SAN sin perfume, bidón de 5 kg":
        exact_title_errors.append("FR0096")
    for code, (title, _presentation) in {**complete.PAGE_121_PRODUCTS, **complete.PAGE_122_PRODUCTS}.items():
        if code not in by_code or by_code[code].get("nombre_propuesto") != title:
            exact_title_errors.append(code)

    old_codes_present = sorted((set(complete.SPURIOUS_MODEL_CODES) | set(complete.CODE_RENAMES)) & set(codes))
    renamed_codes_missing = sorted(set(complete.CODE_RENAMES.values()) - set(codes))
    conflicts_incomplete = sorted(
        code for code in {"UM530", "DX1050", "BX1126", "BX4177", "ZY5044"}
        if code not in by_code
        or by_code[code].get("estado") != "conflicto_catalogo"
        or not by_code[code].get("nota_conflicto")
    )
    protected_official_assets = sorted(
        row["codigo"] for row in rows
        if row["codigo"].rstrip("C") in complete.PRESERVE_CATALOG_CODES
        and (
            str(row.get("imagen_principal") or "").startswith("assets/official/")
            or row.get("descripcion_fuente") == "web_oficial"
        )
    )

    csv_by_code = {row["codigo"]: row for row in csv_rows}
    csv_mismatches = sorted(
        code for code in codes
        if code not in csv_by_code
        or csv_by_code[code]["nombre_o_descripcion_propuesta"] != by_code[code]["nombre_propuesto"]
    )
    evidence, codes_without_evidence = source_evidence(rows)
    evidence_counts = Counter(evidence.values())
    image_count = sum(bool(row.get("imagen_principal")) for row in rows)
    failures = {
        "codigos_invalidos": invalid_codes,
        "codigos_duplicados": duplicate_codes,
        "titulos_vacios": empty_titles,
        "descripciones_vacias": empty_descriptions,
        "titulos_debiles": weak_titles,
        "texto_con_caracter_roto": broken_text,
        "texto_con_fragmentos_ocr": fragmented_text,
        "texto_con_espacios_dobles": double_spaces,
        "titulos_solo_con_medida_o_color": spec_only_titles,
        "titulos_genericos_o_ambiguos": generic_titles,
        "titulos_que_empiezan_en_minuscula": lowercase_titles,
        "titulos_truncados_o_con_codigo_incrustado": incomplete_titles,
        "texto_busqueda_sin_nombre_o_codigo": search_text_mismatches,
        "descripciones_con_nombre_ocr_antiguo": stale_catalog_descriptions,
        "referencias_sin_fuente": missing_sources,
        "imagenes_no_encontradas": missing_image_files,
        "pares_unidad_caja_con_imagen_faltante_o_distinta": pair_mismatches,
        "titulos_contrastados_incorrectos": sorted(set(exact_title_errors)),
        "pseudocodigos_o_codigos_ocr_antiguos_presentes": old_codes_present,
        "codigos_ocr_corregidos_ausentes": renamed_codes_missing,
        "conflictos_de_catalogo_sin_documentar": conflicts_incomplete,
        "activos_oficiales_incompatibles_con_codigo_reutilizado": protected_official_assets,
        "diferencia_json_csv": csv_mismatches if codes == [row["codigo"] for row in csv_rows] else ["Orden o códigos distintos", *csv_mismatches],
        "contador_total_incorrecto": [] if stats.get("referencias_unicas") == len(rows) else [stats.get("referencias_unicas"), len(rows)],
        "contador_imagenes_incorrecto": [] if stats.get("candidatos_con_imagen") == image_count else [stats.get("candidatos_con_imagen"), image_count],
        "contador_titulos_oficiales_incorrecto": [] if stats.get("titulos_revisados_fuente_oficial") == sum(row.get("titulo_fuente") == "web_oficial" for row in rows) else [stats.get("titulos_revisados_fuente_oficial")],
        "codigos_sin_evidencia_en_fuente": codes_without_evidence,
    }
    report = {
        "ok": not any(failures.values()),
        "referencias": len(rows),
        "titulos_legibles": len(rows) - len(weak_titles),
        "referencias_con_imagen": image_count,
        "evidencia_codigos": dict(evidence_counts),
        "pares_unidad_caja": dict(pair_counts),
        "fallos": failures,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
