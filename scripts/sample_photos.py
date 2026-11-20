"""Recorta manualmente una selección de fotos verificadas visualmente en PDF."""
import json,pathlib,fitz
from PIL import Image
R=pathlib.Path(__file__).resolve().parents[1]
items={
 'AL0033':('gris',5,(38,268,564,714)),
 'AL0034':('gris',6,(38,268,564,714)),
 'AL0035':('gris',7,(38,268,564,714)),
 'AL0038':('gris',8,(38,268,564,714)),
 'AL0048':('gris',9,(38,268,564,714)),
 'AL8000':('gris',10,(38,268,564,714)),
 'AL0029':('gris',11,(38,268,564,714)),
 'CR2001':('marron',5,(42,145,191,406)),
}
rows=json.loads((R/'data/articulos.json').read_text('utf-8'))
bycode={r['codigo']:r for r in rows}
for code,(c,p,coords) in items.items():
 if code not in bycode:continue
 page=fitz.open(R/'fuentes'/f'meprolim_revista_{c}_2024.pdf')[p-1]
 pix=page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),clip=fitz.Rect(coords),alpha=False)
 im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
 out=R/'assets'/c/f'{code}_contrastada.webp';out.parent.mkdir(exist_ok=True,parents=True)
 im.save(out,'WEBP',quality=80,method=0)
 r=bycode[code];path=str(out.relative_to(R))
 r['imagenes']=[{'ruta':path,'catalogo':c,'pagina':p,'tipo':'recorte_comprobado','confianza':'alta'},*[im for im in r['imagenes'] if im['ruta']!=path]]
 r['imagen_principal']=path;r['foto_verificada']=True
(R/'data/articulos.json').write_text(json.dumps(rows,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print('Fotos de muestra añadidas',len(items))
