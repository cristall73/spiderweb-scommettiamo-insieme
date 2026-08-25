from __future__ import annotations

import os
from datetime import datetime

import requests

import update_today_min_odds as radar_job

ROME = radar_job.ROME
ORIGINAL_SOFASCORE_CALENDAR = radar_job.sofascore_calendar
FOOTBALL_DATA_ORG_URL = 'https://api.football-data.org/v4/matches'


def thesportsdb_calendar(date_iso, now):
    """Usa TheSportsDB come fonte calendario ufficiale gratuita, senza toccare il modello."""
    try:
        response = requests.get(
            'https://www.thesportsdb.com/api/v1/json/123/eventsday.php',
            params={'d': date_iso, 's': 'Soccer'},
            timeout=radar_job.radar.TIMEOUT,
            headers={'User-Agent': 'SpiderWeb/1.0', 'Accept': 'application/json'},
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f'WARN calendario TheSportsDB non disponibile: {exc}')
        return [], 0

    raw_events = data.get('events') or []
    events = []
    blocked = ('women', 'femmin', ' u17', ' u18', ' u19', ' u20', ' u21', ' u23', 'youth', 'reserve')
    cutoff = int(now.timestamp())

    for item in raw_events:
        home = str(item.get('strHomeTeam') or '').strip()
        away = str(item.get('strAwayTeam') or '').strip()
        league = str(item.get('strLeague') or '').strip()
        country = str(item.get('strCountry') or '').strip()
        status = str(item.get('strStatus') or '').lower()
        if not home or not away or not league:
            continue
        text = f'{league} {home} {away}'.lower()
        if any(word in text for word in blocked):
            continue
        if any(word in status for word in ('finished', 'postpon', 'cancel')):
            continue

        ts = 0
        date_event = str(item.get('dateEvent') or date_iso).strip()
        time_event = str(item.get('strTime') or '00:00:00').strip()
        try:
            dt = datetime.fromisoformat(f'{date_event}T{time_event[:8]}').replace(tzinfo=ROME)
            ts = int(dt.timestamp())
            if ts < cutoff:
                continue
        except Exception:
            dt = None

        canonical = radar_job.radar.canonical_league(country, league) if country else None
        if not canonical:
            canonical = radar_job.retail_canonical(country, league)

        events.append({
            'event_id': f"tsdb-{item.get('idEvent')}",
            'api_league_id': None,
            'api_season': None,
            'country': country,
            'league': league,
            'canonical_league': canonical,
            'home_team': home,
            'away_team': away,
            'time': dt.strftime('%H:%M') if dt else '',
            'start_timestamp': ts,
            'popularity': 0,
            'markets': [],
            'odds_available': False,
            'calendar_source': 'TheSportsDB',
            'retail_extra': bool(canonical in radar_job.RETAIL_EXTRA.values()),
        })

    return events, len(raw_events)


def football_data_org_calendar(date_iso, now):
    """Calendario ufficiale football-data.org.

    Si attiva solo se esiste il secret FOOTBALL_DATA_ORG_TOKEN. In assenza del
    token non genera errori e non cambia il comportamento del radar.
    """
    token = os.getenv('FOOTBALL_DATA_ORG_TOKEN', '').strip()
    if not token:
        print('INFO football-data.org non configurato: secret FOOTBALL_DATA_ORG_TOKEN assente.')
        return [], 0

    try:
        response = requests.get(
            FOOTBALL_DATA_ORG_URL,
            params={'dateFrom': date_iso, 'dateTo': date_iso},
            timeout=radar_job.radar.TIMEOUT,
            headers={
                'X-Auth-Token': token,
                'User-Agent': 'SpiderWeb/1.0',
                'Accept': 'application/json',
            },
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f'WARN calendario football-data.org non disponibile: {exc}')
        return [], 0

    raw_matches = data.get('matches') or []
    events = []
    cutoff = int(now.timestamp())

    for item in raw_matches:
        status = str(item.get('status') or '').upper()
        if status in ('FINISHED', 'POSTPONED', 'SUSPENDED', 'CANCELLED'):
            continue

        home = str((item.get('homeTeam') or {}).get('name') or '').strip()
        away = str((item.get('awayTeam') or {}).get('name') or '').strip()
        competition = item.get('competition') or {}
        area = competition.get('area') or {}
        league = str(competition.get('name') or '').strip()
        country = str(area.get('name') or '').strip()
        if not home or not away or not league:
            continue

        dt = None
        ts = 0
        utc_date = str(item.get('utcDate') or '').strip()
        if utc_date:
            try:
                dt = datetime.fromisoformat(utc_date.replace('Z', '+00:00')).astimezone(ROME)
                ts = int(dt.timestamp())
                if ts < cutoff:
                    continue
            except Exception:
                dt = None

        canonical = radar_job.radar.canonical_league(country, league) if country else None
        if not canonical:
            canonical = radar_job.retail_canonical(country, league)

        events.append({
            'event_id': f"fdo-{item.get('id')}",
            'api_league_id': None,
            'api_season': None,
            'country': country,
            'league': league,
            'canonical_league': canonical,
            'home_team': home,
            'away_team': away,
            'time': dt.strftime('%H:%M') if dt else '',
            'start_timestamp': ts,
            'popularity': 0,
            'markets': [],
            'odds_available': False,
            'calendar_source': 'football-data.org',
            'retail_extra': bool(canonical in radar_job.RETAIL_EXTRA.values()),
        })

    return events, len(raw_matches)


def safe_sofascore_calendar(date_iso, now):
    """Una sola lettura calendario Sofascore per run, senza retry o tentativi di aggirare blocchi."""
    try:
        return ORIGINAL_SOFASCORE_CALENDAR(date_iso, now)
    except Exception as exc:
        print(f'WARN Sofascore saltato senza retry: {exc}')
        return [], 0


def combined_calendar(date_iso, now):
    """Unisce fonti calendario e rimuove i duplicati.

    Le fonti servono solo per trovare le partite di oggi. Probabilita, filtri,
    soglie, edge, ROI e regole walk-forward restano quelli SpiderWeb.
    """
    sofa_events, sofa_raw = safe_sofascore_calendar(date_iso, now)
    tsdb_events, tsdb_raw = thesportsdb_calendar(date_iso, now)
    fdo_events, fdo_raw = football_data_org_calendar(date_iso, now)

    merged = list(sofa_events)
    merged, tsdb_added = radar_job.merge_calendar_sources(merged, tsdb_events)
    merged, fdo_added = radar_job.merge_calendar_sources(merged, fdo_events)

    print(
        'Calendari fallback: '
        f'Sofascore utili={len(sofa_events)} (1 richiesta max/run); '
        f'TheSportsDB utili={len(tsdb_events)}, aggiunte={tsdb_added}; '
        f'football-data.org utili={len(fdo_events)}, aggiunte={fdo_added}'
    )
    return merged, int(sofa_raw or 0) + int(tsdb_raw or 0) + int(fdo_raw or 0)


# Cambia solo il calendario aggiuntivo: il ragionamento delle scommesse non viene modificato.
radar_job.sofascore_calendar = combined_calendar

if __name__ == '__main__':
    radar_job.main()
