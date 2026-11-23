# MEPROLIM · Buscador unificado

Proyecto de revisión creado desde los catálogos **verde, gris, rojo y marrón (12.ª edición, 2024)**. Incluye índice normalizado, búsqueda sin mayúsculas/acentos, filtro por catálogo, fotos recortadas automáticamente, vista de página de origen y PWA.

## Precisión de la información

El índice contiene 3.644 referencias únicas revisadas contra sus páginas de origen. No quedan códigos duplicados, nombres pendientes, títulos débiles ni candidatos extraídos de frases técnicas. El recuento provisional de 3.928 incluía 284 falsos positivos, duplicados o códigos OCR mal formados que ya se han corregido. `data/estadisticas.json` y `INFORME_CONTROL_CALIDAD.md` recogen las cifras actuales.

Las imágenes en `paginas/` son previsualizaciones de las páginas completas y permiten comprobar visualmente cada referencia. Cuando no existe una fotografía individual asociada, la ficha conserva el acceso a esa página.

## Ejecutar en PC

1. Descomprimir el ZIP completo.
2. Abrir terminal en la carpeta descomprimida.
3. Ejecutar `python -m http.server 8000`.
4. Abrir `http://localhost:8000`.

El navegador no puede leer el JSON desde `file://`. En móvil, una vez desplegado, basta con abrir la URL y usar *Añadir a pantalla de inicio*.

## Publicación

El proyecto se publica mediante GitHub Pages desde la rama `main` y el workflow incluido. Las imágenes y páginas derivan de catálogos de terceros; su publicación debe contar con los permisos correspondientes.

## Reprocesar PDFs

Colocar originales en `fuentes/` respetando los nombres `meprolim_revista_verde_2024.pdf` etc. Requiere Python con `pymupdf` y `Pillow`:

```bash
pip install pymupdf pillow
python scripts/build_catalog.py
python scripts/refine.py
```

`build_catalog.py` regenera un índice provisional; `refine.py` añade ejemplos contrastados y previsualizaciones. Las correcciones y el control de calidad deben ampliarse antes del uso operativo. Los archivos PDF originales **no están incluidos en el ZIP** para evitar redistribuirlos involuntariamente.

`scripts/enrich_product_photos.py` amplía la cobertura con asociaciones trazables: ficha o archivo oficial con coincidencia exacta de SKU, imagen incrustada junto al código en el PDF y recortes oficiales revisados manualmente. Rechaza fotografías genéricas de familia, códigos reutilizados, degradados, máscaras y recortes ambiguos. También comparte la foto entre una referencia individual y su variante `C` cuando son el mismo artículo en distinta presentación.

```bash
python scripts/enrich_product_photos.py --apply
python scripts/verify_catalog.py
```

La cobertura actual es de 2.182 referencias (59,88 %). Las 1.462 restantes conservan la página de origen marcada, pero no reciben una fotografía individual si las fuentes no permiten identificarla con seguridad.

## Auditoría de calidad del catálogo

`scripts/audit_catalog_quality.py` contrasta las referencias con los cuatro PDF oficiales y las fichas web oficiales almacenadas temporalmente en `tmp/pdfs/`. En modo normal genera `tmp/pdfs/catalog-quality-report.json` sin modificar la aplicación. Con `--apply` corrige títulos débiles, incorpora descripciones, descarga y optimiza las imágenes cuyo SKU coincide y añade marcadores exactos sobre las páginas de origen. Si una imagen no puede asociarse con seguridad, se omite y se conserva la página marcada.

```bash
python scripts/audit_catalog_quality.py
python scripts/audit_catalog_quality.py --apply
```

`scripts/repair_table_titles.py` reconstruye los títulos de las tablas que se
han revisado visualmente, propaga el nombre del producto a sus variantes de
envase y elimina falsos códigos creados al unir palabras como «CAJA 700» o
«Clax 500». Primero puede ejecutarse en modo informe y después aplicar los
cambios:

```bash
python scripts/repair_table_titles.py
python scripts/repair_table_titles.py --apply
```

`scripts/repair_all_catalog_names.py` completa la auditoría de nombres y
códigos, repara el espaciado tipográfico de los PDF y fusiona referencias OCR
con su código real. `scripts/verify_catalog.py` comprueba después la totalidad
del JSON, CSV, fuentes, imágenes y variantes de caja.
