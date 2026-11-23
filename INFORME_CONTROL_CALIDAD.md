# Informe de control de calidad — MEPROLIM

Auditoría final ejecutada sobre los cuatro catálogos y el índice publicado:

- 3.644 referencias únicas, sin códigos duplicados ni formatos inválidos.
- 3.644 títulos legibles; no quedan nombres vacíos, genéricos pendientes, fragmentos tipográficos detectables ni caracteres rotos.
- 3.644 códigos localizados en su página de origen y asociados a una etiqueta o celda de código, no a una frase técnica.
- 2.182 referencias con fotografía asociada (59,88 %): 1.698 usan un activo web oficial y 484 una imagen incrustada en el catálogo vinculada al código.
- 175 pares de referencia individual y variante `C`: 125 comparten exactamente la misma imagen, 49 carecen de imagen en ambos formatos y una pareja corresponde a productos distintos con fotografía propia.
- Se revisó visualmente el 100 % de las 489 nuevas imágenes candidatas extraídas de los PDF y las 310 candidatas procedentes de la web oficial. Se descartaron degradados, máscaras, recortes parciales y fotografías genéricas que no identificaban la variante.
- Se reconstruyeron 77 presentaciones afectadas por letras o cifras separadas, códigos técnicos fragmentados y texto arrastrado desde filas contiguas. La misma revisión corrigió 13 títulos relacionados; el verificador no detecta ya fragmentos OCR en ninguna presentación.
- JSON y CSV contienen las mismas referencias y en el mismo orden.
- Todas las imágenes referenciadas existen en el proyecto.

Los cinco códigos que el propio catálogo reutiliza para artículos distintos (`BX1126`, `BX4177`, `DX1050`, `UM530` y `ZY5044`) conservan el estado de conflicto y no reciben una fotografía automática que pudiera inducir a error.

El recuento provisional original era de 3.928 candidatos. La auditoría corrigió o eliminó 284 entradas creadas por duplicados, letras pegadas y frases o especificaciones confundidas con códigos. La comprobación reproducible se ejecuta con:

```bash
python scripts/verify_catalog.py
```

El informe detallado se genera en `tmp/pdfs/final-verification-report.json`.

Las imágenes y páginas de los catálogos pertenecen a sus respectivos titulares; su publicación debe contar con los permisos correspondientes.
