"""Comparte fotografías entre un bidón y su caja de cuatro unidades."""

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


def is_individual(row: dict) -> bool:
    return bool(re.search(r"\bbid[oó]n de 5 l\b", row.get("nombre_propuesto", ""), re.I))


def is_box(row: dict) -> bool:
    return bool(
        re.search(
            r"\bcaja de 4 bidones de 5 l\b",
            row.get("nombre_propuesto", ""),
            re.I,
        )
    )


rows = json.loads(JSON_PATH.read_text("utf-8"))
by_code = {row["codigo"]: row for row in rows}
updated: list[tuple[str, str, str]] = []

for individual in rows:
    box = by_code.get(individual["codigo"] + "C")
    if not box or not is_individual(individual) or not is_box(box):
        continue

    source = individual if individual.get("imagenes") else box if box.get("imagenes") else None
    if not source:
        continue

    for target in (individual, box):
        before = target.get("imagen_principal")
        target["imagenes"] = copy.deepcopy(source["imagenes"])
        target["imagen_principal"] = source.get("imagen_principal") or source["imagenes"][0]["ruta"]
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
