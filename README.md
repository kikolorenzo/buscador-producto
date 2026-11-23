# MEPROLIM · Buscador unificado

Proyecto de revisión creado desde los catálogos **verde, gris, rojo y marrón (12.ª edición, 2024)**. Incluye índice normalizado, búsqueda sin mayúsculas/acentos, filtro por catálogo, fotos recortadas automáticamente, vista de página de origen y PWA.

## Precisión de la información

**NO es una base de inventario certificada.** Los códigos son candidatos detectados automáticamente. Se han corregido manualmente algunos ejemplos; la mayoría de nombres, fotos y asociaciones necesitan revisión. `data/estadisticas.json` indica las cifras y `data/conflictos.json` los conflictos candidatos. En el PDF verde, el código **FR0096** está asociado a dos nombres diferentes. No usar como fuente única para realizar pedidos hasta terminar la auditoría.

Las fotos de `assets/` son recortes de las páginas y pueden estar vinculadas al código equivocado. Las imágenes en `paginas/` son **previsualizaciones de páginas completas** y sirven para comprobar visualmente la referencia. Cuando una ficha carece de fotografía, se puede consultar esa página.

## Ejecutar en PC

1. Descomprimir el ZIP completo.
2. Abrir terminal en la carpeta descomprimida.
3. Ejecutar `python -m http.server 8000`.
4. Abrir `http://localhost:8000`.

El navegador no puede leer el JSON desde `file://`. En móvil, una vez desplegado, basta con abrir la URL y usar *Añadir a pantalla de inicio*.

## Publicación futura (no realizada)

El usuario GitHub facilitado es `kikolorenzo`. Crear un repositorio nuevo, por ejemplo `meprolim-buscador`. **Antes de publicar**, confirmar si existen derechos para redistribuir extractos y páginas de los catálogos MEPROLIM. El paquete incluye imágenes y páginas derivadas de obras de terceros; en un repositorio público o GitHub Pages serán accesibles a cualquiera. Si no hay autorización, usar un hosting privado protegido por autenticación y no subir esos materiales a repositorios públicos.

Para GitHub Pages, después de revisar derechos y datos: subir archivos del proyecto a la raíz de `main` y elegir Settings → Pages → Build and deployment → **GitHub Actions**. El workflow ya está incluido.

## Reprocesar PDFs

Colocar originales en `fuentes/` respetando los nombres `meprolim_revista_verde_2024.pdf` etc. Requiere Python con `pymupdf` y `Pillow`:

```bash
pip install pymupdf pillow
python scripts/build_catalog.py
python scripts/refine.py
```

`build_catalog.py` regenera un índice provisional; `refine.py` añade ejemplos contrastados y previsualizaciones. Las correcciones y el control de calidad deben ampliarse antes del uso operativo. Los archivos PDF originales **no están incluidos en el ZIP** para evitar redistribuirlos involuntariamente.

Las fotografías de los ocho ejemplos contrastados se generan mediante `python scripts/sample_photos.py` después de los otros dos scripts; no sustituyen la revisión de todas las referencias.

Cuando una referencia individual de **bidón de 5 l** y su variante `C` de **caja de 4 bidones de 5 l** correspondan al mismo producto, ejecutar `python scripts/sync_packaging_photos.py` para compartir la fotografía disponible entre ambos formatos y actualizar el JSON, el CSV y las estadísticas.

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

El informe detallado se guarda en
`tmp/pdfs/table-title-repair-report.json`. Tras la revisión actual, el índice
contiene 3.908 referencias candidatas; 20 entradas espurias fueron retiradas.
