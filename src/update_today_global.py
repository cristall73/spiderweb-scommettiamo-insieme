from __future__ import annotations

from pathlib import Path
import re
import unicodedata
import pandas as pd

import update_today as base
from league_catalog import ALL_LEAGUES

LIVE_HISTORY=Path('data/output/live_training.csv')


def simple(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode('ascii').lower()
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())


def country_equal(a,b):
    aa=simple(a); bb=simple(b)
    synonyms={
        'usa':'united states','united states of america':'united states',
        'turkiye':'turkey','türkiye':'turkey',
        'england':'england','scotland':'scotland',
        'brasil':'brazil','deutschland':'germany','espana':'spain','italia':'italy',
    }
    aa=synonyms.get(aa,aa); bb=synonyms.get(bb,bb)
    return aa==bb or aa in bb or bb in aa


def global_canonical_league(e):
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}; cat=t.get('category') or {}
    country=str(cat.get('name') or '')
    text=simple(' '.join([str(t.get('name','')),str(u.get('name',''))]))
    best=None
    for meta in ALL_LEAGUES.values():
        if not country_equal(country,meta['country']):
            continue
        for alias in meta.get('aliases',[]):
            a=simple(alias)
            if a and (a==text or a in text):
                score=len(a)
                if best is None or score>best[0]:
                    best=(score,meta['name'])
    return best[1] if best else None


def load_live_training():
    if not LIVE_HISTORY.exists():
        raise RuntimeError('Storico live non ancora generato: attendere il completamento del backtest globale')
    df=pd.read_csv(LIVE_HISTORY)
    df['Date']=pd.to_datetime(df['Date'],errors='coerce')
    df['FTHG']=pd.to_numeric(df['FTHG'],errors='coerce')
    df['FTAG']=pd.to_numeric(df['FTAG'],errors='coerce')
    return df.dropna(subset=['Date','LeagueName','HomeTeam','AwayTeam','FTHG','FTAG']).copy()


# Il vecchio limite di 140 privilegiava le partite popolari e tagliava il resto del mondo.
# 700 copre normalmente l'intera giornata senior; se gli eventi sono meno, vengono presi tutti.
base.MAX_EVENTS_WITH_ODDS=700
base.canonical_league=global_canonical_league
base.load_data=load_live_training

# Continuiamo a escludere giovanili/riserve perché lo storico non è ancora omogeneo per quei tornei.
# Non filtriamo invece serie B/C quando presenti nel catalogo storico.
base.BAD_WORDS=('u17','u18','u19','u20','u21','u23','youth','junior','reserve','reserves')

if __name__=='__main__':
    base.main()
