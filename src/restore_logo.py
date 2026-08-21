from pathlib import Path
from io import BytesIO
import base64,re,requests
from PIL import Image

URL='https://raw.githubusercontent.com/cristall73/spiderweb-scommettiamo-insieme/ebe522a2570f630b9fe5d6ea7de1f90f4f937441/index.html'
OUT=Path('assets/spiderweb-logo.jpg')
r=requests.get(URL,timeout=30,headers={'User-Agent':'Mozilla/5.0 SpiderWeb/1.0'})
r.raise_for_status()
m=re.search(r'data:image/(?:webp|png|jpeg);base64,([A-Za-z0-9+/=]+)',r.text)
if not m:
    raise SystemExit('Logo originale non trovato nel commit storico')
raw=base64.b64decode(m.group(1))
img=Image.open(BytesIO(raw)).convert('RGB')
OUT.parent.mkdir(parents=True,exist_ok=True)
img.save(OUT,'JPEG',quality=94,optimize=True)
print(f'Logo ripristinato: {OUT} ({OUT.stat().st_size} byte)')
