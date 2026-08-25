from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import update_today as base
import update_today_apifootball_safe as safe

radar = safe.radar
ROME = ZoneInfo('Europe/Rome')
OUT = Path('data/output/today.json')
# Usa il dominio API dedicato di Sofascore: ieri forniva il calendario completo.
# Rimane UNA sola richiesta calendario per run: nessun retry aggressivo o bypass.
SOFASCORE_SCHEDULE = 'https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date}'

# Leghe aggiuntive abbastanza comuni sui bookmaker italiani. Evitiamo volutamente
# campionati regionali/amatoriali, giovanili, femminili e coppe minori: aumentare
# la copertura non deve produrre partite che poi sono difficili da trovare su Sisal.
# Le soglie, il modello e le regole walk-forward restano invariati.
RETAIL_EXTRA = {
    ('italy', 'serie c - girone a'): 'Italy Serie C - Girone A',
    ('italy', 'serie c - girone b'): 'Italy Serie C - Girone B',
    ('italy', 'serie c - girone c'): 'Italy Serie C - Girone C',
    ('netherlands', 'eerste divisie'): 'Netherlands Eerste Divisie',
    ('sweden', 'superettan'): 'Sweden Superettan',
    ('poland', 'i liga'): 'Poland I Liga',
    ('turkey', '1. lig'): 'Turkey 1. Lig',
    ('portugal', 'segunda liga'): 'Portugal Segunda Liga',
    ('russia', 'first league'): 'Russia First League',
    ('saudi-arabia', 'pro league'): 'Saudi Arabia Pro League',
    ('argentina', 'primera nacional'): 'Argentina Primera Nacional',
    ('colombia', 'primera b'): 'Colombia Primera B',
    ('iran', 'persian gulf pro league'): 'Iran Persian Gulf Pro League',
    ('serbia', 'prva liga'): 'Serbia Prva Liga',
    ('israel', 'liga leumit'): 'Israel Liga Leumit',
    ('israel', "ligat ha'al"): 'Israel Ligat Haal',
    ('belarus', 'premier league'): 'Belarus Premier League',
    ('macedonia', 'first league'): 'Macedonia First League',
    ('bulgaria', 'first league'): 'Bulgaria First League',
    ('paraguay', 'division profesional - clausura'): 'Paraguay Division Profesional',
    ('malaysia', 'super league'): 'Malaysia Super League',
    ('uzbekistan', 'super league'): 'Uzbekistan Super League',
    ('lithuania', 'a lyga'): 'Lithuania A Lyga',
    ('iceland', 'úrvalsdeild'): 'Iceland Urvalsdeild',
    ('peru', 'segunda división'): 'Peru Segunda Division',
}
MAX_RETAIL_HISTORY_REQUESTS = 20


def ceil2(x: float) -> float:
    return math.ceil((x - 1e-12) * 100) / 100.0


def retail_canonical(country: str, league: str):
    return RETAIL_EXTRA.get((str(country).strip().lower(), str(league).strip().lower()))


def map_retail_extras(events):
    mapped = 0
    for e in events:
        if e.get('canonical_league'):
            continue
        canonical = retail_canonical(e.get('country', ''), e.get('league', ''))
        if canonical:
            e['canonical_league'] = canonical
            e['retail_extra'] = True
            mapped += 1
    return mapped


def same_fixture(a, b):
    if a.get('canonical_league') and b.get('canonical_league') and a.get('canonical_league') != b.get('canonical_league'):
        return False
    return radar.team_match(a.get('home_team', ''), b.get('home_team', '')) and radar.team_match(a.get('away_team', ''), b.get('away_team', ''))


def football_data_calendar(date_iso):
    try:
        response = requests.get(
            radar.FOOTBALL_DATA_FIXTURES,
            timeout=radar.TIMEOUT,
            headers={'User-Agent': 'Mozilla/5.0 SpiderWeb/1.0'},
        )
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text))
    except Exception as exc:
        print(f'WARN calendario Football-Data non disponibile: {exc}')
        return [], 0

    if df.empty or 'Date' not in df.columns:
        return [], 0

    target = datetime.fromisoformat(date_iso).date()
    dates = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce').dt.date
    today = df.loc[dates == target].copy()
    events = []

    for idx, row in today.iterrows():
        home = str(row.get('HomeTeam') or '').strip()
        away = str(row.get('AwayTeam') or '').strip()
        div = str(row.get('Div') or '').strip()
        if not home or not away or not div:
            continue
        meta = radar.ALL_LEAGUES.get(div)
        if not meta:
            continue
        events.append({
            'event_id': f'fd-{date_iso}-{div}-{idx}',
            'api_league_id': None,
            'api_season': None,
            'country': meta['country'],
            'league': meta['name'],
            'canonical_league': meta['name'],
            'home_team': home,
            'away_team': away,
            'time': str(row.get('Time') or '').strip(),
            'start_timestamp': 0,
            'popularity': 0,
            'markets': [],
            'odds_available': False,
            'calendar_source': 'Football-Data',
            'retail_extra': False,
        })

    return events, len(today)


def sofascore_calendar(date_iso, now):
    """Calendario mondiale aggiuntivo. Viene usato solo come fonte fixture.

    Nessuna probabilita, quota o statistica Sofascore entra nel modello: per un
    candidato continuano a servire storico compatibile e regole SpiderWeb.
    """
    try:
        response = requests.get(
            SOFASCORE_SCHEDULE.format(date=date_iso),
            timeout=radar.TIMEOUT,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
                'Accept': 'application/json,text/plain,*/*',
                'Referer': 'https://www.sofascore.com/',
            },
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f'WARN calendario Sofascore non disponibile: {exc}')
        return [], 0

    raw_events = data.get('events') or []
    events = []
    cutoff = int(now.timestamp())
    blocked = ('women', 'femmin', ' u17', ' u18', ' u19', ' u20', ' u21', ' u23', 'youth', 'reserve')

    for item in raw_events:
        home = str((item.get('homeTeam') or {}).get('name') or '').strip()
        away = str((item.get('awayTeam') or {}).get('name') or '').strip()
        tournament = item.get('tournament') or {}
        unique = tournament.get('uniqueTournament') or {}
        category = tournament.get('category') or unique.get('category') or {}
        country = str(category.get('name') or '').strip()
        league = str(unique.get('name') or tournament.get('name') or '').strip()
        ts = int(item.get('startTimestamp') or 0)
        status_type = str((item.get('status') or {}).get('type') or '').lower()

        if not home or not away or not league:
            continue
        text = f'{league} {home} {away}'.lower()
        if any(word in text for word in blocked):
            continue
        if status_type in ('finished', 'inprogress', 'canceled', 'cancelled', 'postponed', 'afterextra', 'afterpenalties'):
            continue
        if ts and ts < cutoff:
            continue

        canonical = radar.canonical_league(country, league) if country else None
        if not canonical:
            canonical = retail_canonical(country, league)
        dt = datetime.fromtimestamp(ts, ROME) if ts else None
        events.append({
            'event_id': f"sofa-{item.get('id')}",
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
            'calendar_source': 'Sofascore',
            'retail_extra': bool(canonical in RETAIL_EXTRA.values()),
        })

    return events, len(raw_events)


def merge_calendar_sources(base_events, extra_events):
    merged = list(base_events)
    added = 0
    for event in extra_events:
        if any(same_fixture(event, existing) for existing in merged):
            continue
        merged.append(event)
        added += 1
    return merged, added


def supplemental_retail_history(events, now):
    groups = {}
    for e in events:
        if not e.get('retail_extra'):
            continue
        lid = e.get('api_league_id')
        season = e.get('api_season')
        canonical = e.get('canonical_league')
        if lid and season and canonical:
            groups.setdefault((canonical, int(lid), int(season)), 0)
            groups[(canonical, int(lid), int(season))] += 1

    ordered = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0][0]))
    rows = []
    requests_used = 0
    covered = []
    cutoff = int(now.timestamp())

    for (canonical, lid, season), fixtures_today in ordered:
        league_rows = []
        seasons_tried = []
        season_candidates = []
        for s in (season, season - 1, 2024, 2023, 2022):
            if s > 0 and s not in season_candidates:
                season_candidates.append(s)
        for target_season in season_candidates:
            if requests_used >= MAX_RETAIL_HISTORY_REQUESTS:
                break
            try:
                data, _ = radar.api_get('/fixtures', {'league': lid, 'season': target_season, 'timezone': 'Europe/Rome'})
                requests_used += 1
                seasons_tried.append(target_season)
            except Exception as exc:
                requests_used += 1
                seasons_tried.append(target_season)
                print(f'WARN storico retail non accessibile {canonical} {target_season}: {exc}')
                continue

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
                dt = datetime.fromtimestamp(ts, ROME)
                league_rows.append({
                    'Date': dt.date().isoformat(),
                    'LeagueName': canonical,
                    'HomeTeam': home,
                    'AwayTeam': away,
                    'FTHG': int(hg),
                    'FTAG': int(ag),
                })

            if len(league_rows) >= 120:
                break

        if league_rows:
            df = pd.DataFrame(league_rows).drop_duplicates(subset=['Date', 'LeagueName', 'HomeTeam', 'AwayTeam'])
            rows.extend(df.to_dict('records'))
            covered.append({
                'league': canonical,
                'fixtures_today': fixtures_today,
                'history_matches': len(df),
                'seasons_tried': seasons_tried,
            })
        if requests_used >= MAX_RETAIL_HISTORY_REQUESTS:
            break

    return pd.DataFrame(rows), requests_used, covered


def rules_for(rules, target, league, selection):
    out = []
    for r in rules:
        if str(r.get('target')) != target:
            continue
        if league in RETAIL_EXTRA.values():
            if str(r.get('league')) != 'TUTTI':
                continue
        elif str(r.get('league')) not in ('TUTTI', league):
            continue
        if str(r.get('selection')) not in ('TUTTI', selection):
            continue
        out.append(r)
    return out


def build_candidates(events, models, hist, teams, rules):
    rows = []
    for e in events:
        league = e.get('canonical_league')
        if not league:
            continue
        home = base.resolve_team(e.get('home_team',''), league, teams)
        away = base.resolve_team(e.get('away_team',''), league, teams)
        if not home or not away:
            continue
        x = base.feature_row(hist, league, home, away)
        if x.isna().any(axis=None):
            continue
        for target in ('OU25','BTTS'):
            if target not in models:
                continue
            p_yes = float(models[target].predict_proba(x)[0,1])
            probs = {
                'OVER25': p_yes,
                'UNDER25': 1-p_yes,
                'BTTS_YES': p_yes,
                'BTTS_NO': 1-p_yes,
            }
            sels = ('OVER25','UNDER25') if target == 'OU25' else ('BTTS_YES','BTTS_NO')
            for sel in sels:
                p = float(probs[sel])
                best = None
                for rule in rules_for(rules, target, league, sel):
                    min_edge = float(rule.get('min_edge') or 0)
                    if p <= min_edge:
                        continue
                    min_rule_odds = float(rule.get('min_odds') or 1.01)
                    threshold = max(min_rule_odds, 1.0 / (p - min_edge))
                    mx = rule.get('max_odds')
                    if pd.notna(mx) and threshold > float(mx):
                        continue
                    threshold = ceil2(threshold)
                    if pd.notna(mx) and threshold > float(mx):
                        continue
                    roi = float(rule.get('roi') or 0)
                    bets = int(rule.get('bets') or 0)
                    score = roi*0.50 + p*0.25 + min_edge*0.15 + min(bets,400)/400*0.10
                    candidate = (score, threshold, min_edge, roi, bets, rule)
                    if best is None or candidate[0] > best[0]:
                        best = candidate
                if best is None:
                    continue
                score, threshold, min_edge, roi, bets, rule = best
                fair_odds = 1.0 / p if p > 0 else 999
                ev_at_threshold = p * threshold - 1
                rows.append({
                    **{k:e.get(k) for k in ('event_id','country','league','home_team','away_team','time')},
                    'canonical_league': league,
                    'market': base.friendly_market(target),
                    'selection': base.friendly_selection(sel),
                    'target': target,
                    'selection_code': sel,
                    'odds': round(threshold,2),
                    'min_acceptable_odds': round(threshold,2),
                    'fair_odds': round(fair_odds,2),
                    'model_probability': round(p,4),
                    'required_edge': round(min_edge,4),
                    'edge': round(min_edge,4),
                    'expected_value_at_min_odds': round(ev_at_threshold,4),
                    'expected_value': round(ev_at_threshold,4),
                    'system_roi': round(roi,4),
                    'system_bets': bets,
                    'score': round(score,5),
                    'retail_extra': bool(e.get('retail_extra')),
                    'calendar_source': e.get('calendar_source', 'API-Football'),
                    'needs_bookmaker_check': True,
                    'source': 'Quota minima calcolata dal modello SpiderWeb + sistema walk-forward',
                })
    return rows


def main():
    now = datetime.now(ROME)
    date_iso = now.date().isoformat()
    historical = radar.load_live_training()

    models = base.train_live_models(historical)
    rules = base.load_live_rules()

    fixtures_data, headers = radar.api_get('/fixtures', {'date': date_iso, 'timezone': 'Europe/Rome'})
    raw = [x for x in (fixtures_data.get('response') or []) if radar.senior_fixture(x)]
    api_events = [radar.fixture_to_event(x) for x in raw]
    for event in api_events:
        event['calendar_source'] = 'API-Football'

    fd_events, fd_rows_today = football_data_calendar(date_iso)
    events, fd_added = merge_calendar_sources(api_events, fd_events)

    sofa_events, sofa_rows_today = sofascore_calendar(date_iso, now)
    events, sofa_added = merge_calendar_sources(events, sofa_events)

    retail_mapped = map_retail_extras(events)

    supplemental, history_requests, retail_history = supplemental_retail_history(events, now)
    history_for_form = historical
    if not supplemental.empty:
        history_for_form = pd.concat([historical, supplemental], ignore_index=True, sort=False)
    hist, teams = base.latest_histories(history_for_form)

    eligible = [e for e in events if e.get('canonical_league')]
    unmapped = [e for e in events if not e.get('canonical_league')]
    unmapped_counter = Counter((e.get('country') or 'Sconosciuto', e.get('league') or 'Sconosciuto') for e in unmapped)
    unmapped_leagues = [
        {'country': country, 'league': league, 'fixtures': count}
        for (country, league), count in unmapped_counter.most_common(50)
    ]

    rows = build_candidates(eligible, models, hist, teams, rules)
    rows = base.best_per_event(rows)
    single = rows[0] if rows else None
    double = base.pick_combo(rows, 2, 1.80, 4.50) if len(rows) >= 2 else None
    triple = base.pick_combo(rows, 3, 2.30, 7.50) if len(rows) >= 3 else None

    remaining = headers.get('x-ratelimit-requests-remaining') or headers.get('X-RateLimit-Requests-Remaining')
    payload = {
        'generated_at': now.isoformat(timespec='seconds'),
        'date': date_iso,
        'source': 'API-Football + Football-Data + Sofascore calendario; probabilita SpiderWeb; quota minima da verificare sul bookmaker',
        'mode': 'min_acceptable_odds',
        'fixtures_count': len(events),
        'api_football_fixtures_count': len(api_events),
        'football_data_rows_today': fd_rows_today,
        'football_data_calendar_added': fd_added,
        'sofascore_rows_today': sofa_rows_today,
        'sofascore_calendar_added': sofa_added,
        'eligible_history_count': len(eligible),
        'retail_extra_mapped_count': retail_mapped,
        'retail_history_requests_used': history_requests,
        'retail_history_coverage': retail_history,
        'unmapped_history_count': len(unmapped),
        'unmapped_leagues': unmapped_leagues,
        'fixtures_with_odds': 0,
        'candidate_count': len(rows),
        'active_rules': len(rules),
        'api_requests_remaining': remaining,
        'single': single,
        'double': double,
        'triple': triple,
        'shortlist': rows[:40],
        'note': ('Il calendario viene unito da API-Football, Football-Data e Sofascore, eliminando i duplicati. '
                 'Sofascore viene usato solo come calendario: non modifica probabilita, modello, soglie, edge, ROI '
                 'o regole walk-forward. La giocata e valida solo se il bookmaker offre una quota uguale o superiore '
                 'alla quota minima indicata.'),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'date': date_iso,
        'api_football_fixtures': len(api_events),
        'football_data_righe_oggi': fd_rows_today,
        'football_data_aggiunte': fd_added,
        'sofascore_righe_oggi': sofa_rows_today,
        'sofascore_aggiunte': sofa_added,
        'fixtures_globali_unici': len(events),
        'con_storico_o_retail': len(eligible),
        'retail_extra_mappate': retail_mapped,
        'richieste_storico_retail': history_requests,
        'copertura_storico_retail': retail_history,
        'senza_mapping_storico': len(unmapped),
        'top_leghe_senza_mapping': unmapped_leagues[:15],
        'candidati_quota_minima': len(rows),
        'migliore': None if not single else f"{single['home_team']} - {single['away_team']} / {single['selection']} >= {single['min_acceptable_odds']}",
        'richieste_api_rimanenti': remaining,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
