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


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "articulos.json"
CSV = ROOT / "data" / "articulos.csv"
STATS = ROOT / "data" / "estadisticas.json"
REPORT = ROOT / "tmp" / "pdfs" / "final-verification-report.json"
PDF_DIR = ROOT / "tmp" / "pdfs"

OCR_FRAGMENT_PATTERNS = (
    r"\b(?:stru id|bosde|p illo|u eta|pensado r|vi l|cio nal|p ro|sp ira|fre gado|tu rb|rela ire|udalde)\b",
    r"\b(?:po lip|tra ctiv|nam ie|ce p|t ria|it i|p ag g|secado r|plataform a|g asas|d ig|sd i|con ce p|rol lo)\b",
)


def is_spec_only_title(value: str) -> bool:
    ignored = {"negro", "blanco", "verde", "azul", "rojo", "beige", "gris", "inox", "cromo"}
    words = re.findall(r"[A-Za-zÀ-ſ]+", value.lower())
    return not any(len(word) >= 4 and word not in ignored for word in words)


def source_evidence(rows: list[dict]) -> tuple[dict[str, str], list[str]]:
    documents: dict[str, fitz.Document] = {}
    pages: dict[tuple[str, int], str] = {}
    evidence: dict[str, str] = {}
    missing: list[str] = []
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
        if not result and row.get("titulo_fuente") == "web_oficial":
            result = "ficha_web_oficial"
        if not result:
            missing.append(code)
        evidence[code] = result or "sin_evidencia"
    for document in documents.values():
        document.close()
    return evidence, missing


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
    weak_titles = sorted(row["codigo"] for row in rows if audit.is_weak_title(row))
    broken_titles = sorted(row["codigo"] for row in rows if "\ufffd" in row.get("nombre_propuesto", ""))
    fragmented_titles = sorted(
        row["codigo"] for row in rows
        if any(re.search(pattern, row.get("nombre_propuesto", ""), re.IGNORECASE) for pattern in OCR_FRAGMENT_PATTERNS)
    )
    spec_only_titles = sorted(
        row["codigo"] for row in rows if is_spec_only_title(row.get("nombre_propuesto", ""))
    )
    wide_text_candidates = sorted(
        row["codigo"] for row in rows
        if (widths := [
            float(marker.get("w", 0))
            for source in row.get("fuentes", [])
            for marker in source.get("marcadores", [])
            if marker.get("w") is not None
        ]) and min(widths) > 18
    )
    missing_sources = sorted(row["codigo"] for row in rows if not row.get("fuentes"))
    missing_image_files = sorted(
        row["codigo"] for row in rows
        if row.get("imagen_principal") and not (ROOT / row["imagen_principal"]).is_file()
    )
    csv_codes = [row["codigo"] for row in csv_rows]

    pair_mismatches: list[str] = []
    pair_counts = Counter()
    for code, box in by_code.items():
        if not code.endswith("C") or code[:-1] not in by_code:
            continue
        base = by_code[code[:-1]]
        base_image = base.get("imagen_principal")
        box_image = box.get("imagen_principal")
        if not base_image and not box_image:
            pair_counts["sin_imagen_en_ambos"] += 1
        elif base_image == box_image:
            pair_counts["misma_imagen"] += 1
        else:
            pair_counts["imagen_distinta"] += 1
            pair_mismatches.append(f"{code[:-1]}/{code}")

    evidence, codes_without_evidence = source_evidence(rows)
    evidence_counts = Counter(evidence.values())
    failures = {
        "codigos_invalidos": invalid_codes,
        "codigos_duplicados": duplicate_codes,
        "titulos_vacios": empty_titles,
        "titulos_debiles": weak_titles,
        "titulos_con_caracter_roto": broken_titles,
        "titulos_con_fragmentos_ocr": fragmented_titles,
        "titulos_solo_con_medida_o_color": spec_only_titles,
        "candidatos_extraidos_de_frases": wide_text_candidates,
        "referencias_sin_fuente": missing_sources,
        "imagenes_no_encontradas": missing_image_files,
        "pares_unidad_caja_con_imagen_distinta": pair_mismatches,
        "diferencia_json_csv": [] if codes == csv_codes else ["Los códigos u orden de JSON y CSV no coinciden"],
        "contador_total_incorrecto": [] if stats.get("referencias_unicas") == len(rows) else [stats.get("referencias_unicas"), len(rows)],
        "contador_imagenes_incorrecto": [] if stats.get("candidatos_con_imagen") == sum(bool(row.get("imagen_principal")) for row in rows) else [stats.get("candidatos_con_imagen"), sum(bool(row.get("imagen_principal")) for row in rows)],
        "codigos_sin_evidencia_en_fuente": codes_without_evidence,
    }
    report = {
        "ok": not any(failures.values()),
        "referencias": len(rows),
        "titulos_legibles": len(rows) - len(weak_titles),
        "referencias_con_imagen": sum(bool(row.get("imagen_principal")) for row in rows),
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
