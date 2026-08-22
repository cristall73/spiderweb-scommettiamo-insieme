from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import update_today_apifootball as radar
import update_today_apifootball_safe  # applica il wrapper safe al modulo radar

ROME = ZoneInfo('Europe/Rome')
OUT = Path('data/output/today.json')
ODDS_KEY = os.getenv('ODDS_API_IO_KEY', '').strip()
ODDS_BASE = 'https://api.odds-api.io/v3'
BOOKMAKERS = os.getenv('ODDS_API_IO_BOOKMAKERS', 'Bet365,Unibet')
MAX_ODDS_CALLS = max(1, min(int(os.getenv('ODDS_API_IO_MAX_CALLS', '24')), 60))


def norm(s):
    return radar.simple(s)


def similarity(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def oddsio_get(path, params):
    p = dict(params)
    p['apiKey'] = ODDS_KEY
    r = requests.get(ODDS_BASE + path, params=p, timeout=30)
    r.raise_for_status()
    return r.json(), r.headers


def market_from_bookmakers(payload):
    books = payload.get('bookmakers') or {}
    markets = []
    ou_choices = []
    btts_choices = []
    if isinstance(books, list):
        books = {str(i): x for i, x in enumerate(books)}
    for book_name, entries in books.items():
        if isinstance(entries, dict):
            entries = entries.get('markets') or entries.get('odds') or [entries]
        if not isinstance(entries, list):
            continue
        for m in entries:
            if not isinstance(m, dict):
                continue
            name = norm(m.get('name') or m.get('market') or m.get('key') or '')
            odds = m.get('odds') or m.get('outcomes') or []
            if isinstance(odds, dict):
                odds = [odds]
            if 'total' in name or 'over under' in name:
                for row in odds:
                    try:
                        hdp = float(row.get('hdp') or row.get('line') or row.get('point'))
                    except Exception:
                        continue
                    if abs(hdp - 2.5) > 0.01:
                        continue
                    try:
                        over = float(row.get('over'))
                        under = float(row.get('under'))
                    except Exception:
                        continue
                    if over > 1 and under > 1:
                        inv = 1/over + 1/under
                        ou_choices.append((abs(inv-1), {'target':'OU25','bookmaker':book_name,'options':[
                            {'selection':'OVER25','label':'Over 2.5','odds':over,'market_probability':(1/over)/inv},
                            {'selection':'UNDER25','label':'Under 2.5','odds':under,'market_probability':(1/under)/inv},
                        ]}))
            if 'btts' in name or ('both teams' in name and 'score' in name):
                yes = no = None
                for row in odds:
                    if not isinstance(row, dict):
                        continue
                    lab = norm(row.get('name') or row.get('label') or row.get('value') or '')
                    try:
                        price = float(row.get('price') or row.get('odd') or row.get('odds'))
                    except Exception:
                        continue
                    if lab in ('yes','both teams score yes'):
                        yes = price
                    elif lab in ('no','both teams score no'):
                        no = price
                if yes and no and yes > 1 and no > 1:
                    inv = 1/yes + 1/no
                    btts_choices.append((abs(inv-1), {'target':'BTTS','bookmaker':book_name,'options':[
                        {'selection':'BTTS_YES','label':'BTTS Sì','odds':yes,'market_probability':(1/yes)/inv},
                        {'selection':'BTTS_NO','label':'BTTS No','odds':no,'market_probability':(1/no)/inv},
                    ]}))
    if ou_choices:
        markets.append(min(ou_choices, key=lambda x:x[0])[1])
    if btts_choices:
        markets.append(min(btts_choices, key=lambda x:x[0])[1])
    return markets


def find_odds_event(event, odds_events):
    best = None
    for oe in odds_events:
        hs = similarity(event['home_team'], oe.get('home',''))
        aw = similarity(event['away_team'], oe.get('away',''))
        direct = (hs + aw) / 2
        swapped = (similarity(event['home_team'], oe.get('away','')) + similarity(event['away_team'], oe.get('home',''))) / 2
        score = max(direct, swapped)
        if score < 0.72:
            continue
        league_score = similarity(event.get('league',''), (oe.get('league') or {}).get('name',''))
        score += 0.15 * league_score
        if best is None or score > best[0]:
            best = (score, oe)
    return best[1] if best else None


def main():
    # Se la nuova chiave non è ancora configurata, manteniamo il radar attuale funzionante.
    if not ODDS_KEY:
        print('WARN ODDS_API_IO_KEY non configurata: uso radar attuale senza Odds-API.io')
        radar.main()
        return

    now = datetime.now(ROME)
    date_iso = now.date().isoformat()
    historical = radar.load_live_training()
    hist, teams = radar.base.latest_histories(historical)
    models = radar.base.train_live_models(historical)
    rules = radar.base.load_live_rules()

    fixtures_data, _ = radar.api_get('/fixtures', {'date': date_iso, 'timezone': 'Europe/Rome'})
    raw = [x for x in (fixtures_data.get('response') or []) if radar.senior_fixture(x)]
    events = [radar.fixture_to_event(x) for x in raw]
    eligible = [e for e in events if e.get('canonical_league')]

    priorities, has_global = radar.active_league_priorities(rules)
    target = [e for e in eligible if has_global or e.get('canonical_league') in priorities]
    target.sort(key=lambda e: priorities.get(e.get('canonical_league'),0), reverse=True)

    start = datetime.combine(now.date(), datetime.min.time(), tzinfo=ROME).astimezone().isoformat()
    end = (datetime.combine(now.date(), datetime.min.time(), tzinfo=ROME) + timedelta(days=1)).astimezone().isoformat()
    odds_events, headers = oddsio_get('/events', {'sport':'football','status':'pending','from':start,'to':end})
    if not isinstance(odds_events, list):
        odds_events = odds_events.get('events') or odds_events.get('response') or []

    matched = 0
    calls = 1
    for event in target:
        if calls >= MAX_ODDS_CALLS:
            break
        oe = find_odds_event(event, odds_events)
        if not oe:
            continue
        try:
            data, headers = oddsio_get('/odds', {'eventId':oe.get('id'),'bookmakers':BOOKMAKERS})
            calls += 1
        except Exception as exc:
            print(f'WARN Odds-API.io {event["home_team"]}-{event["away_team"]}: {exc}')
            continue
        markets = market_from_bookmakers(data if isinstance(data, dict) else {})
        if markets:
            event['markets'] = markets
            event['odds_available'] = True
            event['odds_source'] = 'Odds-API.io'
            matched += 1

    with_odds = [e for e in eligible if e.get('odds_available')]
    rows = radar.base.best_per_event(radar.base.candidate_rows(with_odds, models, hist, teams, rules))
    for row in rows:
        row['source'] = 'Odds-API.io quote pre-match + modello SpiderWeb walk-forward'

    payload = {
        'generated_at': now.isoformat(timespec='seconds'), 'date': date_iso,
        'source': 'API-Football calendario mondiale + Odds-API.io quote pre-match; storico SpiderWeb/Football-Data',
        'fixtures_count': len(events), 'eligible_history_count': len(eligible),
        'target_leagues_today': len(set(e.get('canonical_league') for e in target)),
        'odds_api_events_today': len(odds_events), 'odds_api_calls_used': calls,
        'fixtures_with_odds': len(with_odds), 'odds_api_matches': matched,
        'candidate_count': len(rows), 'active_rules': len(rules),
        'single': rows[0] if rows else None,
        'double': radar.base.pick_combo(rows,2,1.80,3.20) if len(rows)>=2 else None,
        'triple': radar.base.pick_combo(rows,3,2.30,4.50) if len(rows)>=3 else None,
        'shortlist': rows[:30],
        'note':'Calendario API-Football; quote mirate Odds-API.io solo su partite/leghe già validate dal walk-forward.'
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'fixtures':len(events),'con_storico':len(eligible),'odds_events':len(odds_events),'quote_abbinate':matched,'con_quote':len(with_odds),'candidati':len(rows),'calls':calls},ensure_ascii=False))

if __name__ == '__main__':
    main()
