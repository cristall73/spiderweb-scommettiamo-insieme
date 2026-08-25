from __future__ import annotations

from datetime import datetime

import requests

import update_today_min_odds as radar_job

ROME = radar_job.ROME
ORIGINAL_SOFASCORE_CALENDAR = radar_job.sofascore_calendar


def thesportsdb_calendar(date_iso, now):
    """Usa TheSportsDB come seconda fonte calendario, senza toccare il modello."""
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


def combined_calendar(date_iso, now):
    """Somma Sofascore + TheSportsDB e rimuove i duplicati.

    Queste fonti servono solo per trovare le partite di oggi. Probabilita,
    filtri, soglie, edge, ROI e regole walk-forward restano quelli SpiderWeb.
    """
    sofa_events, sofa_raw = ORIGINAL_SOFASCORE_CALENDAR(date_iso, now)
    tsdb_events, tsdb_raw = thesportsdb_calendar(date_iso, now)
    merged, added = radar_job.merge_calendar_sources(sofa_events, tsdb_events)
    print(f'Calendari fallback: Sofascore utili={len(sofa_events)}; TheSportsDB utili={len(tsdb_events)}; TheSportsDB aggiunte={added}')
    return merged, int(sofa_raw or 0) + int(tsdb_raw or 0)


# Cambia solo il calendario aggiuntivo: il ragionamento delle scommesse non viene modificato.
radar_job.sofascore_calendar = combined_calendar

if __name__ == '__main__':
    radar_job.main()
