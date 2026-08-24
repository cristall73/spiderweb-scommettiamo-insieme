from __future__ import annotations

from datetime import datetime

import requests

import update_today_min_odds as radar_job

ROME = radar_job.ROME


def thesportsdb_calendar(date_iso, now):
    """Usa TheSportsDB esclusivamente come calendario mondiale di fallback."""
    try:
        response = requests.get(
            'https://www.thesportsdb.com/api/v1/json/123/eventsday.php',
            params={'d': date_iso, 's': 'Soccer'},
            timeout=radar_job.radar.TIMEOUT,
            headers={'User-Agent': 'Mozilla/5.0 SpiderWeb/1.0', 'Accept': 'application/json'},
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


# Sostituisce soltanto la fonte calendario aggiuntiva; modello e filtri restano invariati.
radar_job.sofascore_calendar = thesportsdb_calendar

if __name__ == '__main__':
    radar_job.main()
