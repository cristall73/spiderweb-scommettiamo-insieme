from __future__ import annotations

import itertools
import json
import math
import re
import unicodedata
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from backtest_multisource_real import FEATURES, add_features, load_data, make_model, no_vig_prob

OUT = Path('data/output/today.json')
STABLE_FILE = Path('data/output/backtest_multisource_stable.csv')
ROME = ZoneInfo('Europe/Rome')
BASES = ['https://api.sofascore.com/api/v1', 'https://www.sofascore.com/api/v1']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.sofascore.com/'
}
MAX_EVENTS_WITH_ODDS = 140
BAD_WORDS = ('women','femmin','u17','u18','u19','u20','u21','u23','youth','junior','reserve','reserves')

# Non basta essere positivi in backtest: per il live usiamo solo filtri con
# campione decente, almeno 3 stagioni testate e ROI walk-forward >= 3%.
MIN_LIVE_SYSTEM_ROI = 0.03
MIN_LIVE_SYSTEM_BETS = 120


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
        if x:
            return x
    return frac_to_decimal(c.get('fractionalValue'))


def fair_probs(choices):
    vals=[]
    for c in choices:
        o=choice_odds(c)
        if o and o>1:
            vals.append((c,o,1/o))
    s=sum(x[2] for x in vals)
    if s<=0:
        return []
    return [(c,o,inv/s) for c,o,inv in vals]


def norm(s):
    return ''.join(ch.lower() for ch in str(s) if ch.isalnum() or ch in ' .+-/').strip()


def team_norm(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode('ascii').lower()
    s=re.sub(r'\b(fc|cf|afc|ssc|ac|calcio|football club|futbol club)\b',' ',s)
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())


def market_kind(name):
    n=norm(name)
    if 'both teams to score' in n or 'btts' in n or 'both teams score' in n:
        return 'BTTS'
    if ('total goals' in n or 'over/under' in n or 'over under' in n) and ('2.5' in n or '2,5' in n):
        return 'OU25'
    return None


def standard_selection(target, raw_name):
    n=norm(raw_name)
    if target=='OU25':
        if 'over' in n and ('2.5' in n or '2,5' in n or n=='over'):
            return 'OVER25'
        if 'under' in n and ('2.5' in n or '2,5' in n or n=='under'):
            return 'UNDER25'
    if target=='BTTS':
        if n in ('yes','si','sì') or 'yes' in n:
            return 'BTTS_YES'
        if n in ('no','no goal') or n.endswith(' no'):
            return 'BTTS_NO'
    return None


def parse_markets(data):
    out=[]
    for m in data.get('markets',[]) if isinstance(data,dict) else []:
        target=market_kind(m.get('marketName') or m.get('name') or '')
        if not target:
            continue
        fp=fair_probs(m.get('choices') or [])
        if len(fp)<2:
            continue
        opts=[]
        for c,o,p in fp:
            raw=str(c.get('name') or c.get('choiceName') or '').strip()
            sel=standard_selection(target,raw)
            if sel:
                opts.append({'selection':sel,'label':raw,'odds':round(o,3),'market_probability':round(p,5)})
        if len(opts)>=2:
            out.append({'target':target,'options':opts})
    return out


def senior_event(e):
    status=(e.get('status') or {}).get('type','')
    if status not in ('notstarted','scheduled',''):
        return False
    h=e.get('homeTeam') or {}; a=e.get('awayTeam') or {}
    if h.get('gender')=='F' or a.get('gender')=='F':
        return False
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}; c=t.get('category') or {}
    text=' '.join([str(t.get('name','')),str(u.get('name','')),str(c.get('name',''))]).lower()
    return not any(w in text for w in BAD_WORDS)


def event_popularity(e):
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}
    return int(u.get('userCount') or t.get('userCount') or 0)


def canonical_league(e):
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}; cat=t.get('category') or {}
    text=' '.join([str(t.get('name','')),str(u.get('name','')),str(cat.get('name',''))]).lower()
    if 'premier league' in text and 'england' in text:
        return 'Premier League'
    if 'serie a' in text and 'ital' in text:
        return 'Serie A'
    if 'bundesliga' in text and 'german' in text:
        return 'Bundesliga'
    if ('laliga' in text or 'la liga' in text) and 'spain' in text:
        return 'La Liga'
    if 'ligue 1' in text and 'france' in text:
        return 'Ligue 1'
    return None


def event_base(e):
    t=e.get('tournament') or {}; u=t.get('uniqueTournament') or {}; cat=t.get('category') or {}
    ts=int(e.get('startTimestamp') or 0)
    dt=datetime.fromtimestamp(ts,ROME) if ts else None
    return {
        'event_id':e.get('id'),
        'country':cat.get('name') or '',
        'league':u.get('name') or t.get('name') or '',
        'canonical_league':canonical_league(e),
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
        b['markets']=[]
        b['odds_available']=False
    return b


def latest_histories(df):
    hist=defaultdict(lambda:deque(maxlen=10))
    teams=defaultdict(set)
    for _,r in df.sort_values('Date').iterrows():
        league=str(r.LeagueName); h=str(r.HomeTeam); a=str(r.AwayTeam)
        teams[league].update([h,a])
        hg=int(r.FTHG); ag=int(r.FTAG)
        hp,ap=(3,0) if hg>ag else ((0,3) if hg<ag else (1,1))
        over=int(hg+ag>2.5); btts=int(hg>0 and ag>0)
        hist[(league,h)].append({'pts':hp,'gf':hg,'ga':ag,'over':over,'btts':btts})
        hist[(league,a)].append({'pts':ap,'gf':ag,'ga':hg,'over':over,'btts':btts})
    return hist,teams


def resolve_team(name, league, teams):
    candidates=list(teams.get(league,[]))
    if not candidates:
        return None
    n=team_norm(name)
    exact={team_norm(x):x for x in candidates}
    if n in exact:
        return exact[n]
    scored=[]
    nt=set(n.split())
    for x in candidates:
        xn=team_norm(x); xt=set(xn.split())
        ratio=SequenceMatcher(None,n,xn).ratio()
        if nt & xt:
            ratio+=0.08
        scored.append((ratio,x))
    score,best=max(scored,default=(0,None))
    return best if score>=0.68 else None


def snap(hist,n):
    x=list(hist)[-n:]
    if len(x)<5:
        return [np.nan]*5
    return [
        np.mean([r['pts'] for r in x]),np.mean([r['gf'] for r in x]),np.mean([r['ga'] for r in x]),
        np.mean([r['over'] for r in x]),np.mean([r['btts'] for r in x]),
    ]


def feature_row(hist,league,home,away):
    h5=snap(hist[(league,home)],5); a5=snap(hist[(league,away)],5)
    h10=snap(hist[(league,home)],10); a10=snap(hist[(league,away)],10)
    vals=h5[:3]+a5[:3]+[h5[3],a5[3],h5[4],a5[4]]+h10[:3]+a10[:3]+[h10[3],a10[3],h10[4],a10[4]]
    return pd.DataFrame([dict(zip(FEATURES,vals))])


def train_live_models(df):
    featured=add_features(df).dropna(subset=FEATURES).copy()
    models={}
    for target in ('OU25','BTTS'):
        y=((featured.FTHG+featured.FTAG)>2.5).astype(int) if target=='OU25' else ((featured.FTHG>0)&(featured.FTAG>0)).astype(int)
        model=make_model()
        model.fit(featured[FEATURES],y)
        models[target]=model
    return models


def load_live_rules():
    if not STABLE_FILE.exists():
        return []
    df=pd.read_csv(STABLE_FILE)
    df=df[(df['roi']>=MIN_LIVE_SYSTEM_ROI)&(df['bets']>=MIN_LIVE_SYSTEM_BETS)&
          (df['tested_seasons']>=3)&(df['positive_seasons']>=df['tested_seasons']-1)].copy()
    df=df.sort_values(['roi','bets'],ascending=[False,False])
    return df.to_dict('records')


def rule_match(rule,target,league,selection,edge,odds):
    if str(rule['target'])!=target:
        return False
    if str(rule['league']) not in ('TUTTI',league):
        return False
    if str(rule['selection']) not in ('TUTTI',selection):
        return False
    if edge < float(rule['min_edge']):
        return False
    if odds < float(rule['min_odds']):
        return False
    mx=rule.get('max_odds')
    if pd.notna(mx) and odds > float(mx):
        return False
    return True


def friendly_market(target):
    return 'OVER/UNDER 2.5' if target=='OU25' else 'GOAL/NO GOAL'


def friendly_selection(sel):
    return {'OVER25':'OVER 2.5','UNDER25':'UNDER 2.5','BTTS_YES':'GOAL','BTTS_NO':'NO GOAL'}.get(sel,sel)


def candidate_rows(events,models,hist,teams,rules):
    rows=[]
    for e in events:
        league=e.get('canonical_league')
        if not league:
            continue
        home=resolve_team(e['home_team'],league,teams)
        away=resolve_team(e['away_team'],league,teams)
        if not home or not away:
            continue
        x=feature_row(hist,league,home,away)
        for m in e.get('markets',[]):
            target=m['target']
            if target not in models:
                continue
            p_yes=float(models[target].predict_proba(x)[0,1])
            model_probs={
                'OVER25':p_yes,'UNDER25':1-p_yes,
                'BTTS_YES':p_yes,'BTTS_NO':1-p_yes,
            }
            for o in m['options']:
                sel=o['selection']; odd=float(o['odds']); mp=float(o['market_probability'])
                p=float(model_probs[sel]); edge=p-mp; ev=p*odd-1
                matched=[r for r in rules if rule_match(r,target,league,sel,edge,odd)]
                if not matched:
                    continue
                best_rule=max(matched,key=lambda r:(float(r['roi']),int(r['bets'])))
                if ev<=0:
                    continue
                score=(edge*0.55)+(float(best_rule['roi'])*0.30)+(min(int(best_rule['bets']),400)/400*0.15)
                rows.append({
                    **{k:e[k] for k in ('event_id','country','league','home_team','away_team','time')},
                    'canonical_league':league,'market':friendly_market(target),'selection':friendly_selection(sel),
                    'target':target,'selection_code':sel,'odds':round(odd,2),
                    'model_probability':round(p,4),'market_probability':round(mp,4),'edge':round(edge,4),
                    'expected_value':round(ev,4),'system_roi':round(float(best_rule['roi']),4),
                    'system_bets':int(best_rule['bets']),'score':round(score,5),
                    'source':'SofaScore quote corrente + modello SpiderWeb walk-forward'
                })
    return rows


def best_per_event(rows):
    best={}
    for r in rows:
        eid=r['event_id']
        if eid not in best or r['score']>best[eid]['score']:
            best[eid]=r
    return sorted(best.values(),key=lambda x:(-x['score'],-x['edge'],-x['system_roi']))


def pick_combo(rows,n,min_total,max_total):
    top=rows[:12]
    best=None
    for combo in itertools.combinations(top,n):
        if len({x['event_id'] for x in combo})<n:
            continue
        q=math.prod(x['odds'] for x in combo)
        if not (min_total<=q<=max_total):
            continue
        prob=math.prod(x['model_probability'] for x in combo)
        edge_floor=min(x['edge'] for x in combo)
        value=prob+(edge_floor*0.5)
        if best is None or value>best[0]:
            best=(value,combo,q,prob)
    if not best:
        return None
    _,combo,q,prob=best
    return {'legs':list(combo),'total_odds':round(q,2),'combined_probability':round(prob,4)}


def main():
    now=datetime.now(ROME); date=now.date().isoformat()
    historical=load_data()
    hist,teams=latest_histories(historical)
    models=train_live_models(historical)
    rules=load_live_rules()

    schedule=get_json(f'/sport/football/scheduled-events/{date}',20)
    raw=[e for e in schedule.get('events',[]) if senior_event(e)]
    raw=sorted(raw,key=lambda e:(-event_popularity(e),int(e.get('startTimestamp') or 0)))[:MAX_EVENTS_WITH_ODDS]

    enriched=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs=[ex.submit(fetch_odds,e) for e in raw]
        for f in as_completed(futs):
            try:
                enriched.append(f.result())
            except Exception:
                pass
    enriched.sort(key=lambda x:(x['start_timestamp'],x['league']))

    rows=best_per_event(candidate_rows(enriched,models,hist,teams,rules))
    single=rows[0] if rows else None
    double=pick_combo(rows,2,1.80,3.20) if len(rows)>=2 else None
    triple=pick_combo(rows,3,2.30,4.50) if len(rows)>=3 else None
    shortlist=rows[:12]

    payload={
        'generated_at':now.isoformat(timespec='seconds'),'date':date,
        'source':'SofaScore quote pre-match + storico nm2890/football-data + modello SpiderWeb',
        'fixtures_count':len(raw),'fixtures_with_odds':sum(1 for x in enriched if x.get('odds_available')),
        'candidate_count':len(rows),'active_rules':len(rules),
        'single':single,'double':double,'triple':triple,'shortlist':shortlist,
        'note':(
            'Mostriamo una giocata solo quando la probabilità del modello supera quella implicita nella quota '
            'e la partita rientra in un filtro che ha superato il walk-forward. Se non esiste un vantaggio '
            'statistico sufficiente, il risultato corretto è NO BET.'
        )
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({
        'date':date,'fixtures':len(raw),'with_odds':payload['fixtures_with_odds'],
        'active_rules':len(rules),'value_candidates':len(rows),'single':bool(single),
        'double':bool(double),'triple':bool(triple)
    },ensure_ascii=False))


if __name__=='__main__':
    main()
