from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TODAY_PATH = Path('data/output/today.json')
RESULTS_PATH = Path('data/output/results.json')
FINAL_STATUSES = {'FT', 'AET', 'PEN'}


def _norm(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value or '').lower())


def _status_from_pick(selection: str, home_goals: int, away_goals: int) -> str | None:
    sel = str(selection or '').strip().upper().replace(' ', '')
    total = home_goals + away_goals
    if sel in {'OVER2.5', 'OVER25'}:
        return 'won' if total > 2.5 else 'lost'
    if sel in {'UNDER2.5', 'UNDER25'}:
        return 'won' if total < 2.5 else 'lost'
    if sel in {'OVER1.5', 'OVER15'}:
        return 'won' if total > 1.5 else 'lost'
    if sel in {'UNDER1.5', 'UNDER15'}:
        return 'won' if total < 1.5 else 'lost'
    if sel in {'OVER3.5', 'OVER35'}:
        return 'won' if total > 3.5 else 'lost'
    if sel in {'UNDER3.5', 'UNDER35'}:
        return 'won' if total < 3.5 else 'lost'
    if sel in {'GOAL', 'BTTSYES', 'BTTS_YES', 'GG'}:
        return 'won' if home_goals > 0 and away_goals > 0 else 'lost'
    if sel in {'NOGOAL', 'BTTSNO', 'BTTS_NO', 'NG'}:
        return 'won' if home_goals == 0 or away_goals == 0 else 'lost'
    if sel in {'1', 'HOME', 'HOMEWIN'}:
        return 'won' if home_goals > away_goals else 'lost'
    if sel in {'X', 'DRAW'}:
        return 'won' if home_goals == away_goals else 'lost'
    if sel in {'2', 'AWAY', 'AWAYWIN'}:
        return 'won' if away_goals > home_goals else 'lost'
    if sel in {'1X', 'HOMEDRAW'}:
        return 'won' if home_goals >= away_goals else 'lost'
    if sel in {'X2', 'DRAWAWAY'}:
        return 'won' if home_goals <= away_goals else 'lost'
    if sel in {'12', 'NODRAW'}:
        return 'won' if home_goals != away_goals else 'lost'
    return None


def _legs_from_previous(previous: dict) -> list[dict]:
    unique: dict[str, dict] = {}
    single = previous.get('single') or {}
    combos = []
    if single:
        combos.append(single)
    for key in ('double', 'triple'):
        for leg in (previous.get(key) or {}).get('legs') or []:
            combos.append(leg)
    for leg in combos:
        event_id = leg.get('event_id')
        key = str(event_id) if event_id is not None else f"{_norm(leg.get('home_team'))}:{_norm(leg.get('away_team'))}"
        unique[key] = leg
    return list(unique.values())


def _find_fixture(leg: dict, by_id: dict[int, dict], fixtures: list[dict]) -> dict | None:
    try:
        event_id = int(leg.get('event_id'))
    except (TypeError, ValueError):
        event_id = None
    if event_id is not None and event_id in by_id:
        return by_id[event_id]
    home = _norm(leg.get('home_team'))
    away = _norm(leg.get('away_team'))
    for item in fixtures:
        teams = item.get('teams') or {}
        if _norm((teams.get('home') or {}).get('name')) == home and _norm((teams.get('away') or {}).get('name')) == away:
            return item
    return None


def _resolved_leg(leg: dict, fixture: dict) -> dict | None:
    status = ((fixture.get('fixture') or {}).get('status') or {}).get('short')
    goals = fixture.get('goals') or {}
    home_goals = goals.get('home')
    away_goals = goals.get('away')
    if status not in FINAL_STATUSES or home_goals is None or away_goals is None:
        return None
    pick_status = _status_from_pick(leg.get('selection'), int(home_goals), int(away_goals))
    if pick_status is None:
        return None
    return {
        'match': f"{leg.get('home_team')} – {leg.get('away_team')}",
        'pick': leg.get('selection'),
        'score': f"{int(home_goals)}-{int(away_goals)}",
        'status': pick_status,
    }


def _make_bet(label: str, source: dict | None, resolved: dict[str, dict]) -> dict | None:
    if not source:
        return None
    legs = source.get('legs') if isinstance(source, dict) and source.get('legs') else [source]
    result_legs = []
    for leg in legs:
        event_id = leg.get('event_id')
        key = str(event_id) if event_id is not None else f"{_norm(leg.get('home_team'))}:{_norm(leg.get('away_team'))}"
        if key not in resolved:
            return None
        result_legs.append(resolved[key])
    minimum_odds = source.get('total_odds') if source.get('legs') else source.get('min_acceptable_odds', source.get('odds'))
    return {
        'type': label,
        'status': 'won' if all(x['status'] == 'won' for x in result_legs) else 'lost',
        'minimum_odds': minimum_odds,
        'legs': result_legs,
    }


def main() -> None:
    if not TODAY_PATH.exists():
        print('Esiti ieri: today.json assente, nessun aggiornamento.')
        return
    try:
        previous = json.loads(TODAY_PATH.read_text(encoding='utf-8'))
    except Exception as exc:
        print(f'Esiti ieri: today.json non leggibile ({exc}), salto senza bloccare il radar.')
        return

    previous_date = str(previous.get('date') or '')
    today = datetime.now(ZoneInfo('Europe/Rome')).date().isoformat()
    if not previous_date or previous_date >= today:
        print(f'Esiti ieri: nessun giorno precedente da verificare (today.json={previous_date or "n/d"}).')
        return

    try:
        results = json.loads(RESULTS_PATH.read_text(encoding='utf-8')) if RESULTS_PATH.exists() else {'days': []}
    except Exception:
        results = {'days': []}
    days = results.setdefault('days', [])
    if any(str(day.get('date')) == previous_date for day in days):
        print(f'Esiti ieri: {previous_date} gia presente in results.json, zero chiamate API aggiuntive.')
        return

    legs = _legs_from_previous(previous)
    if not legs:
        print(f'Esiti ieri: nessuna schedina presente per {previous_date}.')
        return

    api_key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not api_key:
        print('Esiti ieri: API_FOOTBALL_KEY assente, salto senza modificare results.json.')
        return

    try:
        response = requests.get(
            'https://v3.football.api-sports.io/fixtures',
            params={'date': previous_date},
            headers={'x-apisports-key': api_key},
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        fixtures = payload.get('response') or []
    except Exception as exc:
        print(f'Esiti ieri: fonte risultati non disponibile ({exc}), salto senza bloccare il radar.')
        return

    by_id = {}
    for item in fixtures:
        fixture_id = (item.get('fixture') or {}).get('id')
        if fixture_id is not None:
            try:
                by_id[int(fixture_id)] = item
            except (TypeError, ValueError):
                pass

    resolved = {}
    missing = []
    for leg in legs:
        fixture = _find_fixture(leg, by_id, fixtures)
        result_leg = _resolved_leg(leg, fixture) if fixture else None
        key = str(leg.get('event_id')) if leg.get('event_id') is not None else f"{_norm(leg.get('home_team'))}:{_norm(leg.get('away_team'))}"
        if result_leg:
            resolved[key] = result_leg
        else:
            missing.append(f"{leg.get('home_team')} - {leg.get('away_team')}")

    if missing:
        print('Esiti ieri: non tutti gli incontri risultano conclusi/trovati; results.json resta invariato: ' + ' | '.join(missing))
        return

    bets = []
    for label, source in (
        ('Singola', previous.get('single')),
        ('Doppia', previous.get('double')),
        ('Tripla', previous.get('triple')),
    ):
        bet = _make_bet(label, source, resolved)
        if bet:
            bets.append(bet)

    if not bets:
        print(f'Esiti ieri: nessuna schedina ricostruibile per {previous_date}.')
        return

    days.insert(0, {'date': previous_date, 'bets': bets})
    days.sort(key=lambda x: str(x.get('date') or ''), reverse=True)
    results['updated_at'] = datetime.now(ZoneInfo('Europe/Rome')).isoformat(timespec='seconds')
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Esiti ieri: aggiornato {previous_date} con {len(bets)} schedine usando una sola richiesta risultati.')


if __name__ == '__main__':
    main()
