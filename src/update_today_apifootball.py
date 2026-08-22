from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from datetime import datetime
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
MAX_ODDS_PAGES = max(1, min(int(os.getenv('API_FOOTBALL_MAX_ODDS_PAGES', '8')), 20))
TIMEOUT = 35


def simple(value):
    text = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii').lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def country_equal(a, b):
    aa, bb = simple(a), simple(b)
    synonyms = {
        'usa': 'united states', 'united states of america': 'united states',
        'turkiye': 'turkey', 'brasil': 'brazil', 'espana': 'spain',
        'deutschland': 'germany', 'italia': 'italy', 'holland': 'netherlands',
    }
    aa, bb = synonyms.get(aa, aa), synonyms.get(bb, bb)
    return aa == bb or aa in bb or bb in aa


def canonical_league(country, league_name):
    lname = simple(league_name)
    best = None
    for meta in ALL_LEAGUES.values():
        if not country_equal(country, meta['country']):
            continue
        candidates = list(meta.get('aliases', [])) + [meta['name']]
        for alias in candidates:
            a = simple(alias)
            if a and (a == lname or a in lname or lname in a):
                score = len(a)
                if best is None or score > best[0]:
                    best = (score, meta['name'])
    return best[1] if best else None


def api_get(path, params=None):
    if not API_KEY:
        raise RuntimeError('API_FOOTBALL_KEY non configurata nei GitHub Secrets')
    response = requests.get(
        API_BASE + path,
        params=params or {},
        headers={'x-apisports-key': API_KEY, 'Accept': 'application/json'},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    errors = data.get('errors')
    if errors and errors != [] and errors != {}:
        raise RuntimeError(f'API-Football errori: {errors}')
    return data, response.headers


def load_live_training():
    if not LIVE_HISTORY.exists():
        raise RuntimeError('Manca data/output/live_training.csv: eseguire prima il backtest globale')
    df = pd.read_csv(LIVE_HISTORY)
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['FTHG'] = pd.to_numeric(df['FTHG'], errors='coerce')
    df['FTAG'] = pd.to_numeric(df['FTAG'], errors='coerce')
    return df.dropna(subset=['Date', 'LeagueName', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']).copy()


def senior_fixture(item):
    fixture = item.get('fixture') or {}
    league = item.get('league') or {}
    teams = item.get('teams') or {}
    status = (fixture.get('status') or {}).get('short', '')
    if status not in ('NS', 'TBD', ''):
        return False
    text = ' '.join([
        str(league.get('name', '')), str(league.get('round', '')),
        str((teams.get('home') or {}).get('name', '')),
        str((teams.get('away') or {}).get('name', '')),
    ]).lower()
    banned = ('women', 'femmin', ' u17', ' u18', ' u19', ' u20', ' u21', ' u23', 'youth', 'reserve')
    return not any(word in text for word in banned)


def fixture_to_event(item):
    fixture = item.get('fixture') or {}
    league = item.get('league') or {}
    teams = item.get('teams') or {}
    country = league.get('country') or ''
    league_name = league.get('name') or ''
    dt = None
    try:
        dt = datetime.fromisoformat(str(fixture.get('date', '')).replace('Z', '+00:00')).astimezone(ROME)
    except Exception:
        pass
    return {
        'event_id': fixture.get('id'),
        'country': country,
        'league': league_name,
        'canonical_league': canonical_league(country, league_name),
        'home_team': (teams.get('home') or {}).get('name') or '',
        'away_team': (teams.get('away') or {}).get('name') or '',
        'time': dt.strftime('%H:%M') if dt else '',
        'start_timestamp': int(fixture.get('timestamp') or 0),
        'popularity': 0,
        'markets': [],
        'odds_available': False,
    }


def num(v):
    try:
        x = float(v)
        return x if x > 1.0 and math.isfinite(x) else None
    except Exception:
        return None


def pair_market(bookmaker, target):
    candidates = []
    for bet in bookmaker.get('bets') or []:
        name = simple(bet.get('name', ''))
        if target == 'OU25':
            is_market = ('over under' in name or 'goals over under' in name or 'total goals' in name)
        else:
            is_market = ('both teams' in name and ('score' in name or 'to score' in name)) or 'btts' in name
        if not is_market:
            continue
        values = bet.get('values') or []
        sides = {}
        for value in values:
            label = simple(value.get('value', ''))
            odd = num(value.get('odd'))
            if not odd:
                continue
            if target == 'OU25':
                if 'over 2 5' in label or label == 'over 2.5':
                    sides['OVER25'] = odd
                elif 'under 2 5' in label or label == 'under 2.5':
                    sides['UNDER25'] = odd
            else:
                if label in ('yes', 'goal', 'both teams score yes'):
                    sides['BTTS_YES'] = odd
                elif label in ('no', 'no goal', 'both teams score no'):
                    sides['BTTS_NO'] = odd
        if len(sides) == 2:
            inv = sum(1 / o for o in sides.values())
            # Preferiamo la coppia con margine bookmaker piu basso e coerente.
            candidates.append((abs(inv - 1.0), inv, sides, bookmaker.get('name') or 'Bookmaker'))
    if not candidates:
        return None
    _, inv, sides, book = min(candidates, key=lambda x: x[0])
    options = []
    for selection, odd in sides.items():
        options.append({
            'selection': selection,
            'label': selection,
            'odds': round(odd, 3),
            'market_probability': round((1 / odd) / inv, 5),
        })
    return {'target': target, 'options': options, 'bookmaker': book}


def parse_odds_item(item):
    fixture = item.get('fixture') or {}
    markets = []
    all_books = item.get('bookmakers') or []
    for target in ('OU25', 'BTTS'):
        choices = []
        for book in all_books:
            market = pair_market(book, target)
            if market:
                # Ranking della singola coppia: minore overround assoluto.
                inv = sum(1 / float(o['odds']) for o in market['options'])
                choices.append((abs(inv - 1.0), market))
        if choices:
            markets.append(min(choices, key=lambda x: x[0])[1])
    return fixture.get('id'), markets


def choose_odds_pages(total_pages, now):
    if total_pages <= 0:
        return []
    cap = min(MAX_ODDS_PAGES, total_pages)
    if cap == total_pages:
        return list(range(1, total_pages + 1))
    # Pagina 1 sempre inclusa; le altre ruotano durante la giornata per ampliare la copertura
    # senza superare il tetto del piano gratuito.
    pages = [1]
    remaining = total_pages - 1
    start = ((now.hour // 3) * max(1, cap - 1)) % remaining
    for i in range(cap - 1):
        pages.append(2 + ((start + i) % remaining))
    return pages


def load_odds_for_date(date_iso, now):
    first, headers = api_get('/odds', {'date': date_iso, 'page': 1})
    total = int((first.get('paging') or {}).get('total') or 1)
    pages = choose_odds_pages(total, now)
    items = list(first.get('response') or []) if 1 in pages else []
    for page in pages:
        if page == 1:
            continue
        data, headers = api_get('/odds', {'date': date_iso, 'page': page})
        items.extend(data.get('response') or [])
    remaining = headers.get('x-ratelimit-requests-remaining') or headers.get('X-RateLimit-Requests-Remaining')
    return items, pages, total, remaining


def main():
    now = datetime.now(ROME)
    date_iso = now.date().isoformat()

    historical = load_live_training()
    hist, teams = base.latest_histories(historical)
    models = base.train_live_models(historical)
    rules = base.load_live_rules()

    fixtures_data, fixture_headers = api_get('/fixtures', {'date': date_iso, 'timezone': 'Europe/Rome'})
    raw_fixtures = [x for x in (fixtures_data.get('response') or []) if senior_fixture(x)]
    events = [fixture_to_event(x) for x in raw_fixtures]
    event_by_id = {e['event_id']: e for e in events if e.get('event_id') is not None}

    odds_items, pages_used, odds_total_pages, remaining = load_odds_for_date(date_iso, now)
    for item in odds_items:
        fixture_id, markets = parse_odds_item(item)
        event = event_by_id.get(fixture_id)
        if event and markets:
            event['markets'] = markets
            event['odds_available'] = True

    eligible = [e for e in events if e.get('canonical_league')]
    with_odds = [e for e in eligible if e.get('odds_available')]
    rows = base.best_per_event(base.candidate_rows(with_odds, models, hist, teams, rules))
    for row in rows:
        row['source'] = 'API-Football quote pre-match + modello SpiderWeb walk-forward'

    single = rows[0] if rows else None
    double = base.pick_combo(rows, 2, 1.80, 3.20) if len(rows) >= 2 else None
    triple = base.pick_combo(rows, 3, 2.30, 4.50) if len(rows) >= 3 else None

    payload = {
        'generated_at': now.isoformat(timespec='seconds'),
        'date': date_iso,
        'source': 'API-Football calendario mondiale + quote pre-match; storico SpiderWeb/Football-Data',
        'fixtures_count': len(events),
        'eligible_history_count': len(eligible),
        'fixtures_with_odds': len(with_odds),
        'candidate_count': len(rows),
        'active_rules': len(rules),
        'odds_pages_used': pages_used,
        'odds_total_pages': odds_total_pages,
        'api_requests_remaining': remaining,
        'single': single,
        'double': double,
        'triple': triple,
        'shortlist': rows[:30],
        'note': (
            'Il radar scansiona il calendario mondiale API-Football. Le giocate vengono valutate solo quando '
            'esistono storico sufficiente, quota pre-match reale e filtro walk-forward validato. Le pagine quote '
            'ruotano durante la giornata per ampliare la copertura restando entro il limite del piano API.'
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'date': date_iso,
        'fixtures_globali': len(events),
        'con_storico': len(eligible),
        'con_quote': len(with_odds),
        'candidati': len(rows),
        'pagine_quote': pages_used,
        'pagine_quote_totali': odds_total_pages,
        'richieste_rimanenti': remaining,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
