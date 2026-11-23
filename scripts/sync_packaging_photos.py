"""Comparte fotografías entre una referencia individual y su variante de caja."""

from __future__ import annotations

import copy
import csv
import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "articulos.json"
CSV_PATH = ROOT / "data" / "articulos.csv"
STATS_PATH = ROOT / "data" / "estadisticas.json"
EXCLUDED_BASE_CODES = {
    # La web actual reutiliza estos códigos para productos distintos de los
    # impresos en los catálogos. No se debe propagar su fotografía oficial.
    "BC1008", "BX1064", "BX3032", "BX4009", "BX4015", "BX9010",
    "DZ0008", "FR0029", "FR0104", "FR0124", "FS0030", "ZB1016", "ZG0013",
}


def product_text(row: dict) -> str:
    value = f"{row.get('nombre_propuesto', '')} {row.get('presentacion_propuesta', '')}"
    # El PDF separa a veces palabras por espaciado tipográfico: C aja -> Caja.
    value = re.sub(r"\bC\s+aja\b", "Caja", value, flags=re.I)
    value = re.sub(r"\bb\s+otes\b", "botes", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def is_box(row: dict) -> bool:
    # En este índice el sufijo C representa la presentación de caja. Algunos
    # textos del PDF solo indican «20 packs» o «4 bidones» y omiten la palabra
    # caja, por lo que la relación de códigos es la señal canónica.
    text = product_text(row).lower()
    if re.search(r"\b(?:con|sin)\s+escurridor\b", text):
        return False
    return bool(re.search(r"\b(?:caja|pack|paquete|\d+\s+bidones|\d+\s+botes)\b", text))


rows = json.loads(JSON_PATH.read_text("utf-8"))
by_code = {row["codigo"]: row for row in rows}
updated: list[tuple[str, str, str]] = []

for individual in rows:
    if individual["codigo"] in EXCLUDED_BASE_CODES:
        continue
    box = by_code.get(individual["codigo"] + "C")
    # El código base es la unidad y el sufijo C su caja. Algunos títulos
    # heredados perdieron la palabra «bidón», por lo que la caja es la señal
    # canónica y no el texto defectuoso del artículo individual.
    if not box or not is_box(box):
        continue

    source = individual if individual.get("imagen_principal") else box if box.get("imagen_principal") else None
    if not source:
        continue

    for target in (individual, box):
        before = target.get("imagen_principal")
        target["imagenes"] = copy.deepcopy(source.get("imagenes", []))
        target["imagen_principal"] = source.get("imagen_principal")
        target["foto_verificada"] = bool(source.get("foto_verificada", False))
        if before != target["imagen_principal"]:
            updated.append((individual["codigo"], box["codigo"], target["imagen_principal"]))

JSON_PATH.write_text(
    json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
    encoding="utf-8",
)

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
                "; ".join(f"{source['catalogo']}:{source['pagina']}" for source in row["fuentes"]),
                row.get("nota_conflicto", ""),
            ]
        )

stats = json.loads(STATS_PATH.read_text("utf-8"))
stats["candidatos_con_imagen"] = sum(bool(row.get("imagen_principal")) for row in rows)
stats["recortes_asociados_actuales"] = sum(len(row.get("imagenes", [])) for row in rows)
STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

for individual_code, box_code, image in updated:
    print(f"{individual_code} <-> {box_code}: {image}")
print(f"Referencias actualizadas: {len(updated)}")
