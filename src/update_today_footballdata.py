from __future__ import annotations

import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import update_today as base
from league_catalog import ALL_LEAGUES

ROME = ZoneInfo('Europe/Rome')
OUT = Path('data/output/today.json')
LIVE_HISTORY = Path('data/output/live_training.csv')
FIXTURES_URL = 'https://www.football-data.co.uk/matches/resources/fixtures.csv'
HEADERS = {'User-Agent':'Mozilla/5.0 SpiderWeb/1.0'}


def load_live_training():
    if not LIVE_HISTORY.exists():
        raise RuntimeError('Manca data/output/live_training.csv: eseguire prima il backtest globale')
    df = pd.read_csv(LIVE_HISTORY)
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['FTHG'] = pd.to_numeric(df['FTHG'], errors='coerce')
    df['FTAG'] = pd.to_numeric(df['FTAG'], errors='coerce')
    return df.dropna(subset=['Date','LeagueName','HomeTeam','AwayTeam','FTHG','FTAG']).copy()


def first_numeric(row, names):
    for name in names:
        if name in row.index:
            value = pd.to_numeric(pd.Series([row[name]]), errors='coerce').iloc[0]
            if pd.notna(value) and float(value) > 1:
                return float(value), name
    return None, None


def ou_market(row):
    over, over_src = first_numeric(row, ['Avg>2.5','Max>2.5','B365>2.5','P>2.5','BW>2.5'])
    under, under_src = first_numeric(row, ['Avg<2.5','Max<2.5','B365<2.5','P<2.5','BW<2.5'])
    if not over or not under:
        return None
    inv_o, inv_u = 1/over, 1/under
    total = inv_o + inv_u
    return {
        'target':'OU25',
        'options':[
            {'selection':'OVER25','label':'Over 2.5','odds':round(over,3),'market_probability':round(inv_o/total,5)},
            {'selection':'UNDER25','label':'Under 2.5','odds':round(under,3),'market_probability':round(inv_u/total,5)},
        ],
        'odds_columns':f'{over_src}/{under_src}'
    }


def load_fixtures(today):
    r = requests.get(FIXTURES_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    if 'Date' not in df.columns:
        raise RuntimeError('fixtures.csv senza colonna Date')
    dates = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df = df[dates.dt.date == today].copy()
    df['_date'] = dates[dates.dt.date == today]
    return df


def to_events(df):
    events=[]
    for i,row in df.reset_index(drop=True).iterrows():
        code=str(row.get('Div','')).strip()
        meta=ALL_LEAGUES.get(code)
        if not meta:
            continue
        home=str(row.get('HomeTeam','')).strip(); away=str(row.get('AwayTeam','')).strip()
        if not home or not away or home.lower()=='nan' or away.lower()=='nan':
            continue
        market=ou_market(row)
        time=str(row.get('Time','')).strip()
        if time.lower()=='nan': time=''
        events.append({
            'event_id':f'fd-{code}-{i}-{home}-{away}',
            'country':meta['country'],
            'league':meta['name'],
            'canonical_league':meta['name'],
            'home_team':home,
            'away_team':away,
            'time':time,
            'start_timestamp':0,
            'popularity':0,
            'markets':[market] if market else [],
            'odds_available':bool(market),
        })
    return events


def main():
    now=datetime.now(ROME); today=now.date()
    historical=load_live_training()
    hist,teams=base.latest_histories(historical)
    models=base.train_live_models(historical)
    rules=base.load_live_rules()

    fixtures=load_fixtures(today)
    events=to_events(fixtures)
    rows=base.best_per_event(base.candidate_rows(events,models,hist,teams,rules))
    for r in rows:
        r['source']='Football-Data fixtures + modello SpiderWeb walk-forward'

    single=rows[0] if rows else None
    double=base.pick_combo(rows,2,1.80,3.20) if len(rows)>=2 else None
    triple=base.pick_combo(rows,3,2.30,4.50) if len(rows)>=3 else None

    payload={
        'generated_at':now.isoformat(timespec='seconds'),
        'date':today.isoformat(),
        'source':'Football-Data.co.uk fixtures.csv + storico globale SpiderWeb',
        'fixtures_count':len(events),
        'fixtures_with_odds':sum(1 for x in events if x['odds_available']),
        'candidate_count':len(rows),
        'active_rules':len(rules),
        'single':single,
        'double':double,
        'triple':triple,
        'shortlist':rows[:20],
        'note':(
            'Radar live basato sul file ufficiale fixtures.csv di Football-Data, usato per evitare i blocchi 403 '
            'che SofaScore applica ai runner GitHub. Le quote sono raccolte da Football-Data per le prossime gare; '
            'il radar applica solo filtri walk-forward già validati sullo storico.'
        )
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({
        'date':payload['date'],'fixtures':payload['fixtures_count'],
        'with_odds':payload['fixtures_with_odds'],'candidates':payload['candidate_count'],
        'active_rules':payload['active_rules']
    },ensure_ascii=False))


if __name__=='__main__':
    main()
