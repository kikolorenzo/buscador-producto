#!/usr/bin/env python3
"""Genera un índice deduplicado y material gráfico con trazabilidad desde 4 PDF.
La asociación automática de descripciones/fotos NO es una validación humana.
"""
from __future__ import annotations
import collections,csv,hashlib,json,math,pathlib,re,sys,unicodedata
import fitz
ROOT=pathlib.Path(__file__).resolve().parents[1]
ROOT.joinpath('data').mkdir(exist_ok=True)
ASSETS=ROOT/'assets';ASSETS.mkdir(exist_ok=True)
SOURCE=ROOT/'fuentes'
SOURCE.mkdir(exist_ok=True)
FILES={c:SOURCE/f'meprolim_revista_{c}_2024.pdf' for c in ('verde','gris','rojo','marron')}
PAT=re.compile(r'(?<![A-Za-z0-9])((?:[A-Z][ \t]*){1,3}(?:(?:\d[ \t\-]*){3,6})(?:[A-Z])?)(?![A-Za-z0-9])',re.I)
BAD=re.compile(r'\b(?:c[oó]\s*d\s*i\s*g\s*o|producto|presentaci[oó]n|caracter[ií]sticas|tensi[oó]n|potencia|di[aá]metro|capacidad|frecuencia|dimensiones|peso|caudal|medidas|tel[eé]fono|www\.|correo|@|p\s*h|color|perfume|metros cuadrados)\b',re.I)
BULLET=re.compile(r'^[\s•\-]+')
def norm(s): return re.sub(r'[^A-Z0-9]','',s.upper())
def clean(s):
 s=unicodedata.normalize('NFKC',s)
 s=re.sub(r'(?<=\w)\s{2,}(?=\w)',' ',s)
 s=re.sub(r'\s+',' ',s).strip(' •|-–,.:')
 return s
# OCR-like wide tracking: reconstruct only long runs of single-letter separated characters,
# but avoid crushing ordinary phrases.
def untrack(s):
 s=re.sub(r'(?<!\w)(?:[A-Za-zÁÉÍÓÚÑÜ0-9][ \t]){2,}[A-Za-zÁÉÍÓÚÑÜ0-9](?!\w)',lambda m:re.sub(r'[ \t]+','',m.group()),s)
 return clean(s)
def plausible(code):
 m=re.fullmatch(r'([A-Z]{1,3})(\d{3,6})([A-Z]?)',code)
 return bool(m and (len(m.group(1))>=2 or m.group(1)=='G') and len(code)<=11)
def bbox_distance(a,b):
 ax=(a[0]+a[2])/2;ay=(a[1]+a[3])/2
 bx=(b[0]+b[2])/2;by=(b[1]+b[3])/2
 return math.hypot(ax-bx,(ay-by)*1.1)
def names_from_block(text,code):
 lines=[untrack(x) for x in text.splitlines()]
 lines=[x for x in lines if x and not BAD.search(x) and not BULLET.match(x) and not re.fullmatch(r'\d+(?:[,.-]\d+)*',x) and not re.search(r'^(?:C\s*[ÓO]\s*D\s*I\s*G\s*O|P\s*R\s*O\s*D\s*U\s*C\s*T\s*O|C\s*O\s*D\s*I\s*G\s*O)$',x,re.I)]
 lines=[x for x in lines if len(x)>4 and norm(x)!=code and not PAT.fullmatch(x) and len(x)<115]
 # Remove codes in long descriptions while preserving adjacent wording
 lines=[clean(PAT.sub('',x)) for x in lines]
 return [x for x in lines if len(x)>5 and not BAD.search(x) and norm(x) not in {'PRODUCTO','CODIGO','CODIGOS','PRESENTACION','CARACTERISTICAS','RECAMBIOS','ACCESORIOSINCLUIDOS','HASTAAGOTAREXISTENCIAS'}]
def image_candidates(page):
 imgs=[]
 for b in page.get_text('dict')['blocks']:
  if b['type']!=1:continue
  x0,y0,x1,y1=b['bbox'];w=x1-x0;h=y1-y0
  if w<70 or h<70 or y0<105 or x1>page.rect.width+5:continue
  # Skip full-page background artwork
  if w>page.rect.width*.94 and h>page.rect.height*.87:continue
  imgs.append(tuple(round(v,1) for v in b['bbox']))
 # keep one per near-identical center, smaller frame is usually the real photo (outer is decorative shadow)
 unique=[]
 for rect in sorted(imgs,key=lambda z:(z[2]-z[0])*(z[3]-z[1])):
  if any(abs((rect[0]+rect[2])-(a[0]+a[2]))<20 and abs((rect[1]+rect[3])-(a[1]+a[3]))<20 for a in unique):continue
  unique.append(rect)
 return unique

def get_label(blocks,idx,code):
 cur=blocks[idx];text=cur['text'];box=cur['bbox'];x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
 # Direct label in same text block: product heading + code
 options=[]
 candidates=names_from_block(text,code)
 if len(candidates)>=2 and len(candidates[0])<60 and len(candidates[1])<45 and not re.search(r'^(?:caja|bid[oó]n|pack|bolsa|bote|rollo|transparente|blanco|gris|color)\b',candidates[0],re.I) and not re.search(r'^(?:caja|bid[oó]n|pack|bolsa|bote|rollo)\b',candidates[1],re.I):
  options.append((-10, clean(candidates[0]+' '+candidates[1]),'mismo_bloque'))
 for s in candidates:
  if len(s)<80:options.append(((105 if re.match(r'^(?:caja|bid[oó]n|pack|bolsa|bote|rollo|transparente|blanco|gris|color)\b',s,re.I) else 0),s,'mismo_bloque'))
 for j,b in enumerate(blocks):
  if idx==j:continue
  t=b['text'];rect=b['bbox'];by=(rect[1]+rect[3])/2;bx=(rect[0]+rect[2])/2
  dx=abs(x-bx);dy=by-y
  if dx>265 or abs(dy)>165:continue
  if t.startswith('•') or len(t)>170:continue
  for line in names_from_block(t,code)[:2]:
   if re.match(r'^(?:pack|caja|bid[oó]n|bolsa|bote|rollo)\b',line,re.I):continue
   if re.search(r'\b(?:accesorios incluidos|recambios|c[oó]digo|opcional)\b',line,re.I):continue
   score=math.hypot(dx*.8,dy*1.0)+(30 if dy>25 else 0)+(75 if dx>145 else 0)
   if dy>=-175 and dy<=20:score-=15
   options.append((score,line,'proximidad'))
 if not options:return '', 'sin_nombre'
 options.sort(key=lambda x:x[0])
 return options[0][1],options[0][2]

def get_pack_info(block,code):
 text=block['text']
 text=re.sub(r'(?i)c\s*[oó]\s*d\s*i\s*g\s*o',' ',text)
 candidates=[]
 for line in text.splitlines():
  if code in norm(line):
   s=clean(PAT.sub(' ',line))
   if len(s)>3 and not BAD.search(s): candidates.append(s[:90])
 return candidates[-1] if candidates else ''

rows={};counter=0;stat=collections.Counter();missing=[]
for color,path in FILES.items():
 if not path.exists(): raise FileNotFoundError(f'Falta PDF en {path}')
 doc=fitz.open(path);print(color,'páginas',len(doc),flush=True)
 for pn in range(5,len(doc)+1):
  page=doc[pn-1];stat['paginas']+=1
  raw=[]
  for b in page.get_text('blocks'):
   x0,y0,x1,y1,t,*_=b
   if not isinstance(t,str) or not t.strip():continue
   if y0<18 or y0>page.rect.height-15:continue
   raw.append({'bbox':[x0,y0,x1,y1],'text':t})
  imgs=image_candidates(page)
  occurrences=[]
  for i,b in enumerate(raw):
   for hit in PAT.finditer(b['text']):
    code=norm(hit.group(1))
    if not plausible(code):continue
    # skip a very low frequency false positive that is part of a measurement/URL
    counter+=1
    name,quality=get_label(raw,i,code)
    pack=get_pack_info(b,code)
    r=rows.setdefault(code,{'codigo':code,'fuentes':[],'opciones':[],'imagenes':[],'coincidencias':0})
    r['coincidencias']+=1
    src={'catalogo':color,'pagina':pn}
    if src not in r['fuentes']:r['fuentes'].append(src)
    if name:
     # association is heuristic, not verified
     if not any(o['texto']==name and o['catalogo']==color for o in r['opciones']):
      r['opciones'].append({'texto':name,'catalogo':color,'pagina':pn,'tipo':quality,'formato':pack})
    occurrences.append((code,b,i,name,quality))
  if not occurrences:continue
  # product-image detection: permit only images very close to an explicit code,
  # or a large hero image for a single page title near its top.
  picks=[]
  for img in imgs:
   ix=(img[0]+img[2])/2;iy=(img[1]+img[3])/2
   iw=img[2]-img[0];ih=img[3]-img[1]
   if iw<78 or ih<77:continue
   ranked=[]
   for code,b,i,name,q in occurrences:
    bx=(b['bbox'][0]+b['bbox'][2])/2;by=(b['bbox'][1]+b['bbox'][3])/2
    dist=math.hypot((ix-bx)*1.25,(iy-by)*.8)
    # image below title at top of page (for machinery hero)
    hero=(iw>=180 and ih>=170 and by<190 and 100<iy<700)
    if dist<185 or hero:
     if not hero and abs(ix-bx)>170:continue
     ranked.append((dist-(80 if hero and by<150 else 0),code,b,q,hero))
   ranked.sort(key=lambda z:z[0])
   if ranked:
    score,code,b,q,hero=ranked[0]
    if score<165 or (hero and score<350):
     # eliminate accessory image assignments when many code labels crowd same page
     confidence='media' if score<95 else 'baja'
     if hero and score>140:confidence='baja'
     picks.append((code,img,confidence,score))
  # bound images per item per page; emit crops, not the underlying PDF unlicensed binaries
  per_code=collections.defaultdict(list)
  for code,img,conf,score in sorted(picks,key=lambda t:t[3]):
   if len(per_code[code])<2:per_code[code].append((img,conf))
  for code,items in per_code.items():
   r=rows[code]
   if len(r['imagenes'])>=2:continue
   for bbox,confidence in items[:2-len(r['imagenes'])]:
    rect=fitz.Rect(bbox);rect=rect+(-2,-2,2,2);rect=rect & page.rect
    try:
     pix=page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),clip=rect,alpha=False)
     from PIL import Image
     im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
     if im.width>530:im.thumbnail((530,530),Image.Resampling.LANCZOS)
     sub=ASSETS/color;sub.mkdir(exist_ok=True)
     pathimg=sub/f'{code}_{pn}_{len(r["imagenes"])}.webp'
     im.save(pathimg,'WEBP',quality=68,method=0)
     r['imagenes'].append({'ruta':str(pathimg.relative_to(ROOT)),'catalogo':color,'pagina':pn,'confianza':confidence,'tipo':'recorte_pdf'})
     stat['imagenes']+=1
    except Exception as e: print('image issue',code,e,file=sys.stderr)
 if color=='verde':pass

def rank_option(o):
 s=o['texto'];q=o['tipo']
 return (2 if q=='mismo_bloque' else 1)*50 + min(len(s),60)*.1 - (85 if re.match(r'^(pack|caja|bid[oó]n|bolsa|bote|rollo|transparente|blanco|gris|color)\b',s,re.I) else 0)
output=[];conflicts=[]
for code,r in sorted(rows.items()):
 opts=sorted(r.pop('opciones'),key=rank_option,reverse=True)
 # prevent displaying a made-up product name from a random neighbor
 best=opts[0] if opts else None
 label=best['texto'] if best else ''
 if label and len(label)>105:label=label[:105]
 alternatives=[]
 for o in opts:
  t=o['texto']
  if t.casefold()!=label.casefold() and t.casefold() not in [a.casefold() for a in alternatives] and len(alternatives)<4:
   alternatives.append(t)
 if len(alternatives)>=2:conflicts.append({'codigo':code,'propuesto':label,'alternativas':alternatives,'fuentes':r['fuentes'][:6]})
 r['nombre_propuesto']=label or 'Referencia sin descripción confirmada'
 r['descripcion']='' # don't invent verified description
 r['presentacion_propuesta']=best.get('formato','') if best else ''
 r['catalogos']=list(dict.fromkeys(f['catalogo'] for f in r['fuentes']))
 r['imagenes']=sorted(r['imagenes'],key=lambda im: im['confianza']!='media')
 r['estado']='asociacion_automatica' if label else 'pendiente_revision'
 r['alternativas']=alternatives[:3]
 r['texto_busqueda']=' '.join([label,r['presentacion_propuesta'],*alternatives,*r['catalogos']])
 output.append(r)
stat.update({'referencias_unicas':len(output),'coincidencias':counter,'multiples_catalogos':sum(len(r['catalogos'])>1 for r in output),'con_imagen':sum(bool(r['imagenes']) for r in output),'sin_nombre':sum(not r['descripcion'] and r['nombre_propuesto']=='Referencia sin descripción confirmada' for r in output),'conflictos_potenciales':len(conflicts)})
(ROOT/'data/articulos.json').write_text(json.dumps(output,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
(ROOT/'data/estadisticas.json').write_text(json.dumps(dict(stat),ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'data/conflictos.json').write_text(json.dumps(conflicts,ensure_ascii=False,indent=2),encoding='utf-8')
with (ROOT/'data/articulos.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f);w.writerow(['codigo','nombre_propuesto_NO_VALIDADO','presentacion_propuesta','catalogos','paginas','imagenes','estado'])
 for r in output:w.writerow([r['codigo'],r['nombre_propuesto'],r['presentacion_propuesta'],','.join(r['catalogos']),';'.join(x['catalogo']+':'+str(x['pagina']) for x in r['fuentes']),';'.join(x['ruta'] for x in r['imagenes']),r['estado']])
print(json.dumps(dict(stat),ensure_ascii=False,indent=2),flush=True)
