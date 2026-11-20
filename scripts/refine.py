import json,re,unicodedata,pathlib,fitz,collections
from PIL import Image
R=pathlib.Path(__file__).resolve().parents[1]
P={c:R/'fuentes'/f'meprolim_revista_{c}_2024.pdf' for c in ['verde','gris','rojo','marron']}
rows=json.loads((R/'data/articulos.json').read_text('utf-8'))
# Validated manually against the displayed source pages, with each packaging kept distinct.
VERIFIED={
 'FR0051':('DF FRESA MEPROLIM — Bidón de 5 l','verde',6),
 'FR0051C':('DF FRESA MEPROLIM — Caja de 4 bidones de 5 l','verde',6),
 'FR0008':('DF MELOCOTÓN MEPROLIM — Bidón de 5 l','verde',6),
 'FR0008C':('DF MELOCOTÓN MEPROLIM — Caja de 4 bidones de 5 l','verde',6),
 'FR0050':('DF ALOE VERA MEPROLIM — Bidón de 5 l','verde',6),
 'FR0050C':('DF ALOE VERA MEPROLIM — Caja de 4 bidones de 5 l','verde',6),
 'FR0102':('GEL DERMO CLEANING — Bidón de 5 l','verde',6),
 'BX5009':('TENSOGEN LB ANACARADO — Bidón de 5 l','verde',6),
 'BX5009C':('TENSOGEN LB ANACARADO — Caja de 4 bidones de 5 l','verde',6),
 'BX5012':('TENSOGEN LBR ROSA — Bidón de 5 l','verde',6),
 'BX5012C':('TENSOGEN LBR ROSA — Caja de 4 bidones de 5 l','verde',6),
 'FB0001':('Jabón de manos en pastillas — Pack de 3 × 125 g','verde',6),
 'FG0002':('Jabón de Lagarto en pastillas — Pack de 2 × 150 g','verde',6),
 'AL0033':('Carro de servicio modelo 10','gris',5),
 'AL0034':('Carro de servicio modelo 20','gris',6),
 'AL0035':('Carro de servicio modelo 30','gris',7),
 'AL0038':('Carro de servicio con ruedas elásticas modelo 20','gris',8),
 'AL0048':('Carro de servicio modelo 1400','gris',9),
 'AL8000':('Carro de servicio — bandeja de 80 cm','gris',10),
 'AL0029':('Carro de servicio modelo 1500','gris',11),
 'ZC1001':('Aspirador de polvo CA15 PLUS','rojo',5),
 'YG0009':('Aspirador Henry EPR-170','rojo',6),
 'YG0020':('Aspirador PRP-180 BASIC','rojo',7),
 'ZB0022':('Aspirador de polvo PICCOLO BLU','rojo',8),
 'ZC2005':('Aspirador de polvo PICCOLO GREEN','rojo',9),
 'YG0013':('Aspirador Numatic NBV 190 con batería de litio','rojo',10),
 'YG0041':('Aspirador sin cables HENRY QUICK','rojo',11),
 'CR2001':('Dispensador de papel en rollo para manos — ABS blanco','marron',5),
 'CR7030':('Dispensador de papel en rollo para manos — ABS grafito','marron',5),
 'CR2046':('Dispensador de papel en rollo para manos — ABS transparente','marron',5),
 'ZP0017':('Dispensador de papel en rollo para manos — ABS transparente','marron',5),
 'CR1036':('Papel en rollo para manos — Pack 12 bobinas, 2 capas','marron',5),
 'CR1094':('Papel en rollo para manos — Pack 11 bobinas, 1 capa','marron',5),
 'CR1030':('Papel en rollo para manos — Caja 6 unidades, Universal, 2 capas','marron',6),
 'CR1034':('Papel en rollo para manos — Caja 6 unidades, Advanced, 1 capa','marron',6),
}
# Conflict identified in original green catalog: FR0096 is DF SAN (page 7) vs DF BAC (page 23).
CONFLICTS={'FR0096':'El PDF verde atribuye el mismo código a DF SAN (pág. 7) y DF BAC (pág. 23). Confirmar con proveedor.'}
bycode={r['codigo']:r for r in rows}
for code,(name,c,p) in VERIFIED.items():
 if code in bycode:
  r=bycode[code]
  r['nombre_propuesto']=name;r['estado']='verificado_muestra';r['descripcion']=name;r['presentacion_propuesta']=''
  r['texto_busqueda']=' '.join([name,r['texto_busqueda']])
for r in rows:
 if r['codigo'] in CONFLICTS:
  r['estado']='conflicto';r['nota_conflicto']=CONFLICTS[r['codigo']];r['nombre_propuesto']='Referencia con descripciones contradictorias'
  r['texto_busqueda']+=' DF SAN DF BAC higienizante sin perfume gel manos'
 elif r['estado']!='verificado_muestra':
  name=r['nombre_propuesto']
  weak=not name or name=='Referencia sin descripción confirmada' or re.match(r'(?i)^(?:presentaci[oó]n|presen|c[oó]digo|producto|pro d|c aja|caja|bid[oó]n|pack|bolsa|bote|rollo|tama[oñ]o|cod|p h|recambios|detergentes|dimensiones)',name)
  if weak:
   r['nombre_propuesto']='Descripción pendiente de comprobar'
   r['estado']='pendiente_revision'
# Associate page-based source thumbnail with every candidate; it's a faithful visual locator, never an asserted item photo.
previews=R/'paginas';previews.mkdir(exist_ok=True)
for col,path in P.items():
 doc=fitz.open(path);folder=previews/col;folder.mkdir(exist_ok=True)
 for page_idx in range(4,len(doc)):
  page=doc[page_idx]
  pix=page.get_pixmap(matrix=fitz.Matrix(.68,.68),alpha=False)
  im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
  im.save(folder/f'{page_idx+1}.webp','WEBP',quality=63,method=0)
 print('Vista previa de',col,'finalizada',flush=True)
# Attach page-section headings (useful when a product name could not be extracted).
headings={}
for col,path in P.items():
 doc=fitz.open(path)
 for i in range(4,len(doc)):
  page=doc[i]; lines=[]
  for b in page.get_text('blocks'):
   if 20 < b[1] < 95 and b[0]>170 and b[2]<445 and isinstance(b[4],str):
    txt=re.sub(r'\s+',' ',b[4]).strip()
    if 3<len(txt)<100 and not re.search(r'(?:C\s*[oó]\s*d\s*i\s*g\s*o|www\.|@)',txt,re.I):lines.append(txt)
  headings[(col,i+1)]=' '.join(lines[:2])
for r in rows:
 secs=list(dict.fromkeys(headings.get((f['catalogo'],f['pagina']),'') for f in r['fuentes']))
 secs=[t for t in secs if t]
 r['secciones']=secs[:6]
 r['texto_busqueda']+=' '+' '.join(secs)
 r['vistaprevia']=(f"paginas/{r['fuentes'][0]['catalogo']}/{r['fuentes'][0]['pagina']}.webp" if r['fuentes'] else None)
 # Main photo is automated; never claim certainty solely by geometrical proximity
 r['imagen_principal']=(r['imagenes'][0]['ruta'] if r['imagenes'] else None)
 r['foto_verificada']=False
rows.sort(key=lambda r:r['codigo'])
(R/'data/articulos.json').write_text(json.dumps(rows,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
with (R/'data/articulos.csv').open('w',encoding='utf-8-sig',newline='') as file:
 import csv
 w=csv.writer(file);w.writerow(['codigo','nombre','estado','catalogos','paginas','imagen','observaciones'])
 for r in rows:w.writerow([r['codigo'],r['nombre_propuesto'],r['estado'],','.join(r['catalogos']),';'.join(f"{s['catalogo']}:{s['pagina']}" for s in r['fuentes']),r['imagen_principal'] or '',r.get('nota_conflicto','')])
stat=json.loads((R/'data/estadisticas.json').read_text('utf-8'))
stat.update({'ejemplos_verificados':sum(r['estado']=='verificado_muestra' for r in rows),'referencias_con_conflicto_detectado':sum(r['estado']=='conflicto' for r in rows),'paginas_con_vista_previa':sum(len(fitz.open(p))-4 for p in P.values())})
(R/'data/estadisticas.json').write_text(json.dumps(stat,ensure_ascii=False,indent=2),encoding='utf-8')
print(stat)
