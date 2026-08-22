from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import defaultdict
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
API_BASE = 'https://v3.football.api-sports.io'
API_KEY = os.getenv('API_FOOTBALL_KEY', '').strip()
MAX_ODDS_PAGE = 3
MAX_ODDS_REQUESTS = max(1, min(int(os.getenv('API_FOOTBALL_MAX_ODDS_REQUESTS', '12')), 18))
TIMEOUT = 35
FOOTBALL_DATA_FIXTURES = 'https://www.football-data.co.uk/matches/resources/fixtures.csv'


def simple(value):
    text = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii').lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def country_equal(a, b):
    aa, bb = simple(a), simple(b)
    synonyms = {'usa':'united states','united states of america':'united states','turkiye':'turkey','brasil':'brazil','espana':'spain','deutschland':'germany','italia':'italy','holland':'netherlands'}
    aa, bb = synonyms.get(aa, aa), synonyms.get(bb, bb)
    return aa == bb or aa in bb or bb in aa


def canonical_league(country, league_name):
    lname = simple(league_name); best = None
    for meta in ALL_LEAGUES.values():
        if not country_equal(country, meta['country']): continue
        for alias in list(meta.get('aliases', [])) + [meta['name']]:
            a = simple(alias)
            if a and (a == lname or a in lname or lname in a):
                score = len(a)
                if best is None or score > best[0]: best = (score, meta['name'])
    return best[1] if best else None


def api_get(path, params=None):
    if not API_KEY: raise RuntimeError('API_FOOTBALL_KEY non configurata nei GitHub Secrets')
    response = requests.get(API_BASE + path, params=params or {}, headers={'x-apisports-key':API_KEY,'Accept':'application/json'}, timeout=TIMEOUT)
    response.raise_for_status(); data=response.json(); errors=data.get('errors')
    if errors and errors != [] and errors != {}: raise RuntimeError(f'API-Football errori: {errors}')
    return data, response.headers


def load_live_training():
    if not LIVE_HISTORY.exists(): raise RuntimeError('Manca data/output/live_training.csv: eseguire prima il backtest globale')
    df=pd.read_csv(LIVE_HISTORY); df['Date']=pd.to_datetime(df['Date'],errors='coerce'); df['FTHG']=pd.to_numeric(df['FTHG'],errors='coerce'); df['FTAG']=pd.to_numeric(df['FTAG'],errors='coerce')
    return df.dropna(subset=['Date','LeagueName','HomeTeam','AwayTeam','FTHG','FTAG']).copy()


def senior_fixture(item):
    fixture=item.get('fixture') or {}; league=item.get('league') or {}; teams=item.get('teams') or {}; status=(fixture.get('status') or {}).get('short','')
    if status not in ('NS','TBD',''): return False
    text=' '.join([str(league.get('name','')),str(league.get('round','')),str((teams.get('home') or {}).get('name','')),str((teams.get('away') or {}).get('name',''))]).lower()
    return not any(word in text for word in ('women','femmin',' u17',' u18',' u19',' u20',' u21',' u23','youth','reserve'))


def fixture_to_event(item):
    fixture=item.get('fixture') or {}; league=item.get('league') or {}; teams=item.get('teams') or {}; country=league.get('country') or ''; league_name=league.get('name') or ''; dt=None
    try: dt=datetime.fromisoformat(str(fixture.get('date','')).replace('Z','+00:00')).astimezone(ROME)
    except Exception: pass
    return {'event_id':fixture.get('id'),'api_league_id':league.get('id'),'api_season':league.get('season'),'country':country,'league':league_name,'canonical_league':canonical_league(country,league_name),'home_team':(teams.get('home') or {}).get('name') or '','away_team':(teams.get('away') or {}).get('name') or '','time':dt.strftime('%H:%M') if dt else '','start_timestamp':int(fixture.get('timestamp') or 0),'popularity':0,'markets':[],'odds_available':False}


def num(v):
    try:
        x=float(v); return x if x>1.0 and math.isfinite(x) else None
    except Exception: return None


def market_from_pair(target, a, b, bookmaker):
    a=num(a); b=num(b)
    if not a or not b: return None
    inv=1/a+1/b
    sels=('OVER25','UNDER25') if target=='OU25' else ('BTTS_YES','BTTS_NO')
    return {'target':target,'options':[{'selection':sels[0],'label':sels[0],'odds':round(a,3),'market_probability':round((1/a)/inv,5)},{'selection':sels[1],'label':sels[1],'odds':round(b,3),'market_probability':round((1/b)/inv,5)}],'bookmaker':bookmaker}


def pair_market(bookmaker,target):
    candidates=[]
    for bet in bookmaker.get('bets') or []:
        name=simple(bet.get('name','')); is_market=(('over under' in name or 'goals over under' in name or 'total goals' in name) if target=='OU25' else (('both teams' in name and ('score' in name or 'to score' in name)) or 'btts' in name))
        if not is_market: continue
        sides={}
        for value in bet.get('values') or []:
            label=simple(value.get('value','')); odd=num(value.get('odd'))
            if not odd: continue
            if target=='OU25':
                if 'over 2 5' in label: sides['OVER25']=odd
                elif 'under 2 5' in label: sides['UNDER25']=odd
            else:
                if label in ('yes','goal','both teams score yes'): sides['BTTS_YES']=odd
                elif label in ('no','no goal','both teams score no'): sides['BTTS_NO']=odd
        if len(sides)==2:
            inv=sum(1/o for o in sides.values()); candidates.append((abs(inv-1),inv,sides,bookmaker.get('name') or 'Bookmaker'))
    if not candidates: return None
    _,inv,sides,book=min(candidates,key=lambda x:x[0]); return {'target':target,'options':[{'selection':s,'label':s,'odds':round(o,3),'market_probability':round((1/o)/inv,5)} for s,o in sides.items()],'bookmaker':book}


def parse_odds_item(item):
    fixture=item.get('fixture') or {}; markets=[]; books=item.get('bookmakers') or []
    for target in ('OU25','BTTS'):
        choices=[]
        for book in books:
            market=pair_market(book,target)
            if market: choices.append((abs(sum(1/float(o['odds']) for o in market['options'])-1),market))
        if choices: markets.append(min(choices,key=lambda x:x[0])[1])
    return fixture.get('id'),markets


def active_league_priorities(rules):
    priority=defaultdict(float); has_global=False
    for rule in rules:
        league=str(rule.get('league','')); roi=float(rule.get('roi') or 0)
        if league=='TUTTI': has_global=True
        elif league: priority[league]=max(priority[league],roi)
    return priority,has_global


def targeted_odds(events,rules,date_iso):
    priorities,has_global=active_league_priorities(rules); groups={}
    for event in events:
        canonical=event.get('canonical_league'); lid=event.get('api_league_id'); season=event.get('api_season')
        if not canonical or not lid or not season or (not has_global and canonical not in priorities): continue
        groups.setdefault((canonical,int(lid),int(season)),[]).append(event)
    ordered=sorted(groups.items(),key=lambda kv:(-priorities.get(kv[0][0],0.0),-len(kv[1]),kv[0][0])); requests_used=0; items=[]; leagues_queried=[]; remaining=None; first=[]
    for (canonical,lid,season),league_events in ordered:
        if requests_used>=MAX_ODDS_REQUESTS: break
        data,headers=api_get('/odds',{'date':date_iso,'league':lid,'season':season,'page':1}); requests_used+=1; resp=list(data.get('response') or []); items.extend(resp); total=min(int((data.get('paging') or {}).get('total') or 1),MAX_ODDS_PAGE); first.append((canonical,lid,season,total)); leagues_queried.append({'league':canonical,'api_league_id':lid,'season':season,'fixtures_today':len(league_events),'pages_available_free':total,'page1_items':len(resp),'priority_roi':round(priorities.get(canonical,0.0),4)}); remaining=headers.get('x-ratelimit-requests-remaining') or headers.get('X-RateLimit-Requests-Remaining')
    for page in (2,3):
        for canonical,lid,season,total in first:
            if requests_used>=MAX_ODDS_REQUESTS: break
            if total<page: continue
            data,headers=api_get('/odds',{'date':date_iso,'league':lid,'season':season,'page':page}); requests_used+=1; items.extend(data.get('response') or []); remaining=headers.get('x-ratelimit-requests-remaining') or headers.get('X-RateLimit-Requests-Remaining')
    return items,requests_used,leagues_queried,remaining,len(groups)


def team_match(a,b):
    aa,bb=simple(a),simple(b)
    if not aa or not bb: return False
    if aa==bb or aa in bb or bb in aa: return True
    sa={x for x in aa.split() if len(x)>2 and x not in {'fc','afc','cf','calcio'}}; sb={x for x in bb.split() if len(x)>2 and x not in {'fc','afc','cf','calcio'}}
    return bool(sa and sb and len(sa & sb)>=min(2,len(sa),len(sb)))


def apply_football_data_fallback(events,date_iso):
    try:
        r=requests.get(FOOTBALL_DATA_FIXTURES,timeout=TIMEOUT,headers={'User-Agent':'Mozilla/5.0 SpiderWeb/1.0'}); r.raise_for_status(); df=pd.read_csv(StringIO(r.text))
    except Exception as exc:
        print(f'WARN Football-Data fixtures non disponibile: {exc}'); return 0,0
    if df.empty or 'Date' not in df.columns: return 0,0
    dates=pd.to_datetime(df['Date'],dayfirst=True,errors='coerce').dt.date; target=datetime.fromisoformat(date_iso).date(); df=df.loc[dates==target].copy(); matched=0; markets_added=0
    for event in events:
        if event.get('odds_available'): continue
        candidates=df
        if 'HomeTeam' in candidates.columns: candidates=candidates[candidates['HomeTeam'].map(lambda x: team_match(event.get('home_team',''),x))]
        if 'AwayTeam' in candidates.columns: candidates=candidates[candidates['AwayTeam'].map(lambda x: team_match(event.get('away_team',''),x))]
        if candidates.empty: continue
        row=candidates.iloc[0]; markets=[]
        # Football-Data fixtures espone quote medie/massime Over/Under 2.5 quando disponibili.
        for oc,uc,book in [('Avg>2.5','Avg<2.5','Football-Data media bookmaker'),('Max>2.5','Max<2.5','Football-Data quota massima'),('B365>2.5','B365<2.5','Bet365 via Football-Data')]:
            if oc in row.index and uc in row.index:
                m=market_from_pair('OU25',row.get(oc),row.get(uc),book)
                if m: markets.append(m); break
        # Alcuni feed includono direttamente quote BTTS Yes/No.
        for yc,nc,book in [('AvgBTTSY','AvgBTTSN','Football-Data media bookmaker'),('B365BTTSY','B365BTTSN','Bet365 via Football-Data')]:
            if yc in row.index and nc in row.index:
                m=market_from_pair('BTTS',row.get(yc),row.get(nc),book)
                if m: markets.append(m); break
        if markets:
            event['markets']=markets; event['odds_available']=True; event['odds_source']='Football-Data fixtures.csv'; matched+=1; markets_added+=len(markets)
    print(f'Football-Data fallback: righe oggi={len(df)}, partite abbinate={matched}, mercati={markets_added}')
    return matched,len(df)


def main():
    now=datetime.now(ROME); date_iso=now.date().isoformat(); historical=load_live_training(); hist,teams=base.latest_histories(historical); models=base.train_live_models(historical); rules=base.load_live_rules()
    fixtures_data,fixture_headers=api_get('/fixtures',{'date':date_iso,'timezone':'Europe/Rome'}); raw=[x for x in (fixtures_data.get('response') or []) if senior_fixture(x)]; events=[fixture_to_event(x) for x in raw]; event_by_id={e['event_id']:e for e in events if e.get('event_id') is not None}; eligible=[e for e in events if e.get('canonical_league')]
    odds_items,odds_requests_used,leagues_queried,remaining,target_leagues_today=targeted_odds(eligible,rules,date_iso)
    for item in odds_items:
        fixture_id,markets=parse_odds_item(item); event=event_by_id.get(fixture_id)
        if event and markets: event['markets']=markets; event['odds_available']=True; event['odds_source']='API-Football'
    api_with_odds=sum(1 for e in eligible if e.get('odds_available')); fd_matched,fd_rows=apply_football_data_fallback(eligible,date_iso); with_odds=[e for e in eligible if e.get('odds_available')]
    rows=base.best_per_event(base.candidate_rows(with_odds,models,hist,teams,rules))
    for row in rows: row['source']='Quote live API-Football/Football-Data + modello SpiderWeb walk-forward'
    single=rows[0] if rows else None; double=base.pick_combo(rows,2,1.80,3.20) if len(rows)>=2 else None; triple=base.pick_combo(rows,3,2.30,4.50) if len(rows)>=3 else None
    payload={'generated_at':now.isoformat(timespec='seconds'),'date':date_iso,'source':'API-Football calendario mondiale + quote API-Football con fallback gratuito Football-Data fixtures; storico SpiderWeb/Football-Data','fixtures_count':len(events),'eligible_history_count':len(eligible),'target_leagues_today':target_leagues_today,'leagues_queried':leagues_queried,'fixtures_with_odds':len(with_odds),'api_fixtures_with_odds':api_with_odds,'football_data_fallback_matches':fd_matched,'football_data_rows_today':fd_rows,'candidate_count':len(rows),'active_rules':len(rules),'odds_requests_used':odds_requests_used,'api_requests_remaining':remaining,'single':single,'double':double,'triple':triple,'shortlist':rows[:30],'note':'Il radar usa API-Football per il calendario mondiale. Per le quote tenta API-Football e, quando il piano Free non le rende disponibili, usa automaticamente il feed fixtures gratuito di Football-Data.'}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'date':date_iso,'fixtures_globali':len(events),'con_storico':len(eligible),'leghe_target_oggi':target_leagues_today,'leghe_interrogate':[x['league'] for x in leagues_queried],'richieste_quote_usate':odds_requests_used,'quote_api_football':api_with_odds,'football_data_righe_oggi':fd_rows,'football_data_abbinate':fd_matched,'con_quote_totali':len(with_odds),'candidati':len(rows),'richieste_rimanenti':remaining},ensure_ascii=False))

if __name__=='__main__': main()
