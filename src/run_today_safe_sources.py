from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
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


def safe_supplemental_retail_history(events, now):
    """Storico retail con una sola stagione gratuita per lega.

    API-Football Free consente lo storico 2022-2024 ma non 2025/2026.
    Per evitare richieste sprecate usiamo direttamente il 2024: nella pratica
    fornisce gia centinaia di match per le leghe retail aggiuntive. Una sola
    chiamata per lega mappata, nessun tentativo 2025/2026 e nessun retry.
    """
    groups = {}
    for e in events:
        if not e.get('retail_extra'):
            continue
        lid = e.get('api_league_id')
        canonical = e.get('canonical_league')
        if lid and canonical:
            key = (canonical, int(lid))
            groups[key] = groups.get(key, 0) + 1

    ordered = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0][0]))
    rows = []
    requests_used = 0
    covered = []
    cutoff = int(now.timestamp())
    max_calls = min(8, multi.radar_job.MAX_RETAIL_HISTORY_REQUESTS)

    for (canonical, lid), fixtures_today in ordered:
        if requests_used >= max_calls:
            break

        try:
            data, _ = multi.radar_job.radar.api_get(
                '/fixtures',
                {'league': lid, 'season': 2024, 'timezone': 'Europe/Rome'},
            )
            requests_used += 1
        except Exception as exc:
            requests_used += 1
            print(f'WARN storico retail 2024 non accessibile {canonical}: {exc}')
            continue

        league_rows = []
        for item in data.get('response') or []:
            fixture = item.get('fixture') or {}
            status = (fixture.get('status') or {}).get('short', '')
            ts = int(fixture.get('timestamp') or 0)
            if status not in ('FT', 'AET', 'PEN') or not ts or ts >= cutoff:
                continue
            goals = item.get('goals') or {}
            hg, ag = goals.get('home'), goals.get('away')
            if hg is None or ag is None:
                continue
            teams = item.get('teams') or {}
            home = (teams.get('home') or {}).get('name') or ''
            away = (teams.get('away') or {}).get('name') or ''
            if not home or not away:
                continue
            dt = datetime.fromtimestamp(ts, multi.ROME)
            league_rows.append({
                'Date': dt.date().isoformat(),
                'LeagueName': canonical,
                'HomeTeam': home,
                'AwayTeam': away,
                'FTHG': int(hg),
                'FTAG': int(ag),
            })

        if league_rows:
            df = pd.DataFrame(league_rows).drop_duplicates(
                subset=['Date', 'LeagueName', 'HomeTeam', 'AwayTeam']
            )
            rows.extend(df.to_dict('records'))
            covered.append({
                'league': canonical,
                'fixtures_today': fixtures_today,
                'history_matches': len(df),
                'seasons_tried': [2024],
            })

    print(
        'DIAG storico retail sicuro: '
        f'leghe_mappate={len(groups)}, '
        f'richieste_effettive={requests_used}, '
        f'limite_run={max_calls}, '
        'stagioni_provate=2024_only'
    )
    return pd.DataFrame(rows), requests_used, covered


multi.radar_job.football_data_calendar = disabled_legacy_football_data_calendar
multi.football_data_org_calendar = diagnostic_football_data_org_calendar
multi.radar_job.sofascore_calendar = enhanced_combined_calendar
multi.radar_job.supplemental_retail_history = safe_supplemental_retail_history


if __name__ == '__main__':
    multi.radar_job.main()
