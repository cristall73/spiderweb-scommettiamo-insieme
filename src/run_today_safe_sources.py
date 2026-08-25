from __future__ import annotations

import os
from datetime import datetime

import requests

import update_today_multisource as multi

ORIGINAL_FOOTBALL_DATA_ORG_CALENDAR = multi.football_data_org_calendar
ORIGINAL_COMBINED_CALENDAR = multi.combined_calendar
FOOTBALLDATA_IO_URL = 'https://footballdata.io/api/v1/fixtures/today'


def disabled_legacy_football_data_calendar(date_iso):
    """Disabilita il vecchio feed CSV Football-Data difettoso."""
    print('INFO vecchio feed CSV Football-Data disabilitato; uso API moderne con token.')
    return [], 0


def diagnostic_football_data_org_calendar(date_iso, now):
    """Aggiunge diagnostica a football-data.org senza richieste extra."""
    events, raw_count = ORIGINAL_FOOTBALL_DATA_ORG_CALENDAR(date_iso, now)
    print(
        'DIAG football-data.org: '
        f'righe_api={int(raw_count or 0)}, '
        f'utili_dopo_controlli={len(events)}, '
        'richieste_extra=0'
    )
    return events, raw_count


def footballdata_io_calendar(date_iso, now):
    """Calendario Footballdata.io con una sola richiesta per run.

    La fonte serve solo a trovare le partite. Modello, probabilita, filtri,
    soglie ed edge restano quelli SpiderWeb.
    """
    token = os.getenv('FOOTBALLDATA_IO_KEY', '').strip()
    if not token:
        print('INFO Footballdata.io non configurato: secret FOOTBALLDATA_IO_KEY assente.')
        return [], 0

    try:
        response = requests.get(
            FOOTBALLDATA_IO_URL,
            params={'limit': 100},
            timeout=multi.radar_job.radar.TIMEOUT,
            headers={
                'Authorization': f'Bearer {token}',
                'User-Agent': 'SpiderWeb/1.0',
                'Accept': 'application/json',
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f'WARN calendario Footballdata.io non disponibile: {exc}')
        return [], 0

    raw = payload.get('data') or []
    raw_matches = (raw.get('matches') or []) if isinstance(raw, dict) else raw
    meta = payload.get('meta') or {}
    pagination = meta.get('pagination') or {}
    print(
        'DIAG Footballdata.io: '
        f'righe_api={len(raw_matches)}, '
        f'piano={meta.get("plan")}, '
        f'richieste_usate={meta.get("requests_used")}, '
        f'limite={meta.get("requests_limit")}, '
        f'pagine={pagination.get("total_pages")}, '
        'richieste_extra=0'
    )

    events = []
    cutoff = int(now.timestamp())
    blocked = ('women', 'femmin', ' u17', ' u18', ' u19', ' u20', ' u21', ' u23', 'youth', 'reserve')

    for item in raw_matches:
        status = str(item.get('status') or '').lower()
        if status in ('complete', 'finished', 'postponed', 'suspended', 'cancelled', 'canceled', 'live', 'in_progress'):
            continue

        home_obj = item.get('home_team') or {}
        away_obj = item.get('away_team') or {}
        league_obj = item.get('league') or {}
        home = str(home_obj.get('team_name') or home_obj.get('name') or '').strip()
        away = str(away_obj.get('team_name') or away_obj.get('name') or '').strip()
        league = str(league_obj.get('competition_name') or league_obj.get('name') or '').strip()
        country = str(league_obj.get('country') or '').strip()
        if not home or not away or not league:
            continue

        text = f'{league} {home} {away}'.lower()
        if any(word in text for word in blocked):
            continue

        dt = None
        ts = int(item.get('date_unix') or 0)
        if ts:
            try:
                dt = datetime.fromtimestamp(ts, multi.ROME)
                if dt.date().isoformat() != date_iso or ts < cutoff:
                    continue
            except Exception:
                dt = None
        else:
            match_date = str(item.get('match_date') or '').strip()
            if match_date and match_date != date_iso:
                continue

        canonical = multi.radar_job.radar.canonical_league(country, league) if country else None
        if not canonical:
            canonical = multi.radar_job.retail_canonical(country, league)

        events.append({
            'event_id': f"fdio-{item.get('match_id')}",
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
            'calendar_source': 'Footballdata.io',
            'retail_extra': bool(canonical in multi.radar_job.RETAIL_EXTRA.values()),
        })

    print(f'DIAG Footballdata.io: utili_dopo_controlli={len(events)}')
    return events, len(raw_matches)


def enhanced_combined_calendar(date_iso, now):
    base_events, base_raw = ORIGINAL_COMBINED_CALENDAR(date_iso, now)
    fdio_events, fdio_raw = footballdata_io_calendar(date_iso, now)
    merged, fdio_added = multi.radar_job.merge_calendar_sources(base_events, fdio_events)
    print(f'Footballdata.io aggiunte al calendario={fdio_added}')
    return merged, int(base_raw or 0) + int(fdio_raw or 0)


multi.radar_job.football_data_calendar = disabled_legacy_football_data_calendar
multi.football_data_org_calendar = diagnostic_football_data_org_calendar
multi.radar_job.sofascore_calendar = enhanced_combined_calendar


if __name__ == '__main__':
    multi.radar_job.main()
