from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

OUT = Path('data/output/today.json')
ROME = ZoneInfo('Europe/Rome')
BASES = ['https://api.sofascore.com/api/v1', 'https://www.sofascore.com/api/v1']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.sofascore.com/'
}
MAX_EVENTS_WITH_ODDS = 140

BAD_WORDS = ('women','femmin','u17','u18','u19','u20','u21','u23','youth','junior','reserve','reserves')


def get_json(path: str, timeout: int = 12):
    last = None
    for base in BASES:
        try:
            r = requests.get(base + path, headers=HEADERS, timeout=timeout)
            if r.ok:
                return r.json()
            last = f'{r.status_code} {r.text[:120]}'
        except Exception as exc:
            last = str(exc)
    raise RuntimeError(last or 'richiesta fallita')


def frac_to_decimal(v):
    if v is None:
        return None
    if isinstance(v, (int,float)):
        x = float(v)
        return x if x > 1 else None
    s = str(v).strip()
    try:
        if '/' in s:
            a,b = s.split('/',1)
            return 1 + float(a)/float(b)
        x = float(s)
        return x if x > 1 else None
    except Exception:
        return None


def choice_odds(c):
    for k in ('decimalValue','decimalOdds','value'):
        x = frac_to_decimal(c.get(k))
        if x: return x
    return frac_to_decimal(c.get('fractionalValue'))


def fair_probs(choices):
    vals=[]
    for c in choices:
        o=choice_odds(c)
        if o and o>1: vals.append((c,o,1/o))
    s=sum(x[2] for x in vals)
    if s<=0: return []
    return [(c,o,inv/s) for c,o,inv in vals]


def norm(s):
    return ''.join(ch.lower() for ch in str(s) if ch.isalnum() or ch in ' .+-/').strip()


def market_kind(name):
    n=norm(name)
    if n in ('full time','fulltime','1x2','match result','winner') or 'full time result' in n:
        return '1X2'
    if 'double chance' in n:
        return 'DOPPIA CHANCE'
    if 'both teams to score' in n or 'btts' in n or 'both teams score' in n:
        return 'GOAL/NO GOAL'
    if ('total goals' in n or 'over/under' in n or 'over under' in n) and ('2.5' in n or '2,5' in n):
        return 'OVER/UNDER 2.5'
    return None


def parse_markets(data):
    out=[]
    for m in data.get('markets',[]) if isinstance(data,dict) else []:
        kind=market_kind(m.get('marketName') or m.get('name') or '')
        if not kind: continue
        fp=fair_probs(m.get('choices') or [])
        if len(fp)<2: continue
        opts=[]
        for c,o,p in fp:
            name=str(c.get('name') or c.get('choiceName') or '').strip()
            opts.append({'selection':name,'odds':round(o,2),'probability':round(p,4)})
        out.append({'market':kind,'options':opts})
    return out


def senior_event(e):
    status=(e.get('status') or {}).get('type','')
    if status not in ('notstarted','scheduled',''): return False
    h=e.get('homeTeam') or {}; a=e.get('awayTeam') or {}
    if h.get('gender')=='F' or a.get('gender')=='F': return False
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}; c=t.get('category') or {}
    text=' '.join([str(t.get('name','')),str(u.get('name','')),str(c.get('name',''))]).lower()
    return not any(w in text for w in BAD_WORDS)


def event_popularity(e):
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}
    return int(u.get('userCount') or t.get('userCount') or 0)


def event_base(e):
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}; cat=t.get('category') or {}
    ts=int(e.get('startTimestamp') or 0)
    dt=datetime.fromtimestamp(ts,ROME) if ts else None
    return {
        'event_id':e.get('id'),
        'country':cat.get('name') or '',
        'league':u.get('name') or t.get('name') or '',
        'home_team':(e.get('homeTeam') or {}).get('name') or '',
        'away_team':(e.get('awayTeam') or {}).get('name') or '',
        'time':dt.strftime('%H:%M') if dt else '',
        'start_timestamp':ts,
        'popularity':event_popularity(e),
    }


def fetch_odds(e):
    b=event_base(e)
    try:
        data=get_json(f"/event/{e.get('id')}/odds/1/all",10)
        b['markets']=parse_markets(data)
        b['odds_available']=bool(b['markets'])
    except Exception:
        b['markets']=[]; b['odds_available']=False
    return b


def candidate_rows(events):
    rows=[]
    for e in events:
        for m in e.get('markets',[]):
            for o in m['options']:
                odd=float(o['odds']); p=float(o['probability'])
                if odd < 1.18 or odd > 2.20 or p < 0.48: continue
                kind=m['market']; sel=o['selection']
                # penalità per mercati più volatili, bonus per copertura prudente
                bonus={'DOPPIA CHANCE':0.035,'OVER/UNDER 2.5':0.012,'GOAL/NO GOAL':0.008,'1X2':0.0}.get(kind,0)
                score=p+bonus+min(math.log10(max(e.get('popularity',1),1)),6)*0.002
                rows.append({**{k:e[k] for k in ('event_id','country','league','home_team','away_team','time')},
                             'market':kind,'selection':sel,'odds':round(odd,2),'probability':round(p,4),'score':round(score,4),
                             'source':'SofaScore quote mercato'})
    return rows


def best_per_event(rows):
    best={}
    for r in rows:
        eid=r['event_id']
        if eid not in best or r['score']>best[eid]['score']:
            best[eid]=r
    return sorted(best.values(),key=lambda x:(-x['score'],-x['probability'],x['odds']))


def pick_combo(rows,n,min_total,max_total):
    top=rows[:24]
    best=None
    import itertools
    for combo in itertools.combinations(top,n):
        if len({x['event_id'] for x in combo})<n: continue
        q=math.prod(x['odds'] for x in combo)
        if not (min_total<=q<=max_total): continue
        prob=math.prod(x['probability'] for x in combo)
        floor=min(x['probability'] for x in combo)
        value=(prob*0.75)+(floor*0.25)
        if best is None or value>best[0]: best=(value,combo,q,prob)
    if not best: return None
    _,combo,q,prob=best
    return {'legs':list(combo),'total_odds':round(q,2),'combined_probability':round(prob,4)}


def main():
    now=datetime.now(ROME); date=now.date().isoformat()
    schedule=get_json(f'/sport/football/scheduled-events/{date}',20)
    raw=[e for e in schedule.get('events',[]) if senior_event(e)]
    # Preferiamo le partite più seguite ma manteniamo copertura ampia.
    raw=sorted(raw,key=lambda e:(-event_popularity(e),int(e.get('startTimestamp') or 0)))[:MAX_EVENTS_WITH_ODDS]
    enriched=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs=[ex.submit(fetch_odds,e) for e in raw]
        for f in as_completed(futs):
            try: enriched.append(f.result())
            except Exception: pass
    enriched.sort(key=lambda x:(x['start_timestamp'],x['league']))
    rows=best_per_event(candidate_rows(enriched))

    # Singola: non una quota ridicola; deve essere abbastanza probabile e avere quota sensata.
    single=next((r for r in rows if r['probability']>=0.58 and 1.35<=r['odds']<=1.95),None)
    double=pick_combo([r for r in rows if r['probability']>=0.58 and 1.22<=r['odds']<=1.80],2,1.75,2.70)
    triple=pick_combo([r for r in rows if r['probability']>=0.60 and 1.18<=r['odds']<=1.65],3,2.10,3.60)

    shortlist=rows[:12]
    payload={
        'generated_at':now.isoformat(timespec='seconds'),'date':date,
        'source':'SofaScore calendario globale + quote pre-match; Football-Data resta la base dei backtest',
        'fixtures_count':len(raw),'fixtures_with_odds':sum(1 for x in enriched if x.get('odds_available')),
        'candidate_count':len(rows),'single':single,'double':double,'triple':triple,'shortlist':shortlist,
        'note':'Singola, doppia e tripla sono selezioni probabilistiche basate sulle quote di mercato depurate dal margine, non garanzie di vincita. I sistemi value validati restano separati dai pronostici probabilistici.'
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'date':date,'fixtures':len(raw),'with_odds':payload['fixtures_with_odds'],'candidates':len(rows),'single':bool(single),'double':bool(double),'triple':bool(triple)},ensure_ascii=False))

if __name__=='__main__': main()
