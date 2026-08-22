from __future__ import annotations

from pathlib import Path
import pandas as pd
import requests

from league_catalog import EUROPE_LEAGUES, WORLD_LEAGUES, EUROPE_SEASONS, EUROPE_URL, WORLD_URL

RAW_DIR = Path('data/raw')
HEADERS = {'User-Agent':'Mozilla/5.0 SpiderWeb/1.0'}


def download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    r=requests.get(url,headers=HEADERS,timeout=40)
    r.raise_for_status()
    # Alcune pagine di errore restituiscono HTML con status 200: scartiamole.
    if b'<html' in r.content[:300].lower():
        raise RuntimeError('risposta HTML invece di CSV')
    destination.write_bytes(r.content)
    return destination


def validate(path: Path) -> tuple[int,int]:
    df=pd.read_csv(path)
    if len(df)<20:
        raise RuntimeError(f'CSV troppo corto: {len(df)} righe')
    return df.shape


def main() -> None:
    total=0; ok=0; failed=0

    # 22 divisioni europee, sei stagioni concluse.
    for season in EUROPE_SEASONS:
        for code,meta in EUROPE_LEAGUES.items():
            try:
                p=download(EUROPE_URL.format(season=season,code=code),RAW_DIR/f'eu_{season}_{code}.csv')
                rows,cols=validate(p); total+=rows; ok+=1
                print(f"OK EU | {season} | {meta['name']:<30} | {rows:>4} partite | {cols:>3} colonne")
            except Exception as exc:
                failed+=1
                print(f"SKIP EU | {season} | {meta['name']} | {exc}")

    # 16 archivi extra-europei. Football-Data li pubblica come CSV per paese/lega.
    for code,meta in WORLD_LEAGUES.items():
        try:
            p=download(WORLD_URL.format(code=code),RAW_DIR/f'world_{code}.csv')
            rows,cols=validate(p); total+=rows; ok+=1
            print(f"OK WORLD | {meta['name']:<30} | {rows:>5} righe | {cols:>3} colonne")
        except Exception as exc:
            failed+=1
            print(f"SKIP WORLD | {meta['name']} | {exc}")

    print(f'\nFile validi: {ok} | file saltati: {failed} | righe storiche scaricate: {total}')


if __name__=='__main__':
    main()
