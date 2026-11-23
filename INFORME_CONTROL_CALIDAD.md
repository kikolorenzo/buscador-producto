# Informe de control de calidad — MEPROLIM

Auditoría final ejecutada sobre los cuatro catálogos y el índice publicado:

- 3.713 referencias únicas, sin códigos duplicados ni formatos inválidos.
- 3.713 títulos legibles; no quedan nombres vacíos, genéricos pendientes, fragmentos tipográficos detectables ni caracteres rotos.
- 3.713 códigos localizados en su página de origen y asociados a una etiqueta o celda de código, no a una frase técnica.
- 1.503 referencias con imagen asociada.
- 178 pares de referencia individual y caja: 115 comparten exactamente la misma imagen y 63 carecen de imagen en ambos formatos; no hay pares con fotografías distintas.
- JSON y CSV contienen las mismas referencias y en el mismo orden.
- Todas las imágenes referenciadas existen en el proyecto.

El PDF verde reutiliza el código `FR0096` para **DF SAN** (pág. 7) y **DF BAC** (pág. 23). La ficha muestra ambas denominaciones y mantiene un aviso para confirmar con el proveedor; no se ha inventado una elección que el documento de origen no permite resolver.

El recuento provisional original era de 3.928 candidatos. La auditoría corrigió o eliminó 215 entradas creadas por duplicados, letras pegadas y frases o especificaciones confundidas con códigos. La comprobación reproducible se ejecuta con:

```bash
python scripts/verify_catalog.py
```

El informe detallado se genera en `tmp/pdfs/final-verification-report.json`.

Las imágenes y páginas de los catálogos pertenecen a sus respectivos titulares; su publicación debe contar con los permisos correspondientes.
