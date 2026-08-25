from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

import run_today_safe_sources as safe

ORIGINAL_MAP_RETAIL_EXTRAS = safe.multi.radar_job.map_retail_extras
HISTORY_PATH = Path('data/output/live_training.csv')
MIN_TEAM_MATCHES = 8


def _country_matches(country: str, league: str) -> bool:
    country = str(country or '').strip().lower()
    league = str(league or '').strip().lower()
    if not country or country in ('world', 'europe'):
        return True
    aliases = {
        'england': ('england',),
        'scotland': ('scotland',),
        'argentina': ('argentina',),
        'spain': ('spain',),
        'italy': ('italy',),
        'germany': ('germany',),
        'france': ('france',),
        'netherlands': ('netherlands',),
        'portugal': ('portugal',),
        'belgium': ('belgium',),
        'turkey': ('turkey',),
        'denmark': ('denmark',),
        'sweden': ('sweden',),
        'norway': ('norway',),
        'brazil': ('brazil',),
        'colombia': ('colombia',),
        'saudi-arabia': ('saudi arabia', 'saudi-arabia'),
        'saudi arabia': ('saudi arabia', 'saudi-arabia'),
    }
    needles = aliases.get(country, (country.replace('-', ' '),))
    return any(n in league for n in needles)


def _matching_historical_team(name: str, team_counts: Counter):
    best = None
    best_count = 0
    for hist_name, count in team_counts.items():
        if count < MIN_TEAM_MATCHES:
            continue
        if safe.multi.radar_job.radar.team_match(name, hist_name):
            if count > best_count:
                best = hist_name
                best_count = count
    return best, best_count


def map_with_local_history(events):
    """Estende solo il mapping, usando esclusivamente lo storico locale gia presente.

    Una fixture senza lega canonica viene mappata solo quando entrambe le squadre
    sono riconosciute nella STESSA lega storica, con almeno MIN_TEAM_MATCHES
    presenze ciascuna, e il risultato e univoco. Nessuna API aggiuntiva.
    """
    mapped_existing = ORIGINAL_MAP_RETAIL_EXTRAS(events)

    if not HISTORY_PATH.exists():
        print('DIAG mapping locale: live_training.csv assente; nessun mapping aggiuntivo.')
        return mapped_existing

    try:
        hist = pd.read_csv(
            HISTORY_PATH,
            usecols=['LeagueName', 'HomeTeam', 'AwayTeam'],
            low_memory=False,
        ).dropna(subset=['LeagueName'])
    except Exception as exc:
        print(f'WARN mapping locale non disponibile: {exc}')
        return mapped_existing

    league_team_counts = defaultdict(Counter)
    for row in hist.itertuples(index=False):
        league = str(row.LeagueName or '').strip()
        home = str(row.HomeTeam or '').strip()
        away = str(row.AwayTeam or '').strip()
        if league and home:
            league_team_counts[league][home] += 1
        if league and away:
            league_team_counts[league][away] += 1

    local_mapped = 0
    ambiguous = 0
    unresolved = 0
    examples = []

    for event in events:
        if event.get('canonical_league'):
            continue

        home = str(event.get('home_team') or '').strip()
        away = str(event.get('away_team') or '').strip()
        country = str(event.get('country') or '').strip()
        if not home or not away:
            unresolved += 1
            continue

        candidates = []
        for league, counts in league_team_counts.items():
            if not _country_matches(country, league):
                continue
            h_name, h_count = _matching_historical_team(home, counts)
            if not h_name:
                continue
            a_name, a_count = _matching_historical_team(away, counts)
            if not a_name:
                continue
            candidates.append((league, min(h_count, a_count), h_name, a_name))

        if len(candidates) == 1:
            league, support, h_name, a_name = candidates[0]
            event['canonical_league'] = league
            event['local_history_map'] = True
            event['local_history_support'] = int(support)
            event['retail_extra'] = False
            local_mapped += 1
            if len(examples) < 8:
                examples.append(
                    f"{home}-{away} -> {league} (supporto>={support})"
                )
        elif len(candidates) > 1:
            # Non scegliamo arbitrariamente fra piu leghe: meglio saltare che
            # cambiare la logica del modello con un mapping dubbio.
            ambiguous += 1
        else:
            unresolved += 1

    print(
        'DIAG mapping storico locale: '
        f'mappate_esistenti={mapped_existing}, '
        f'mappate_locali={local_mapped}, '
        f'ambigue_saltate={ambiguous}, '
        f'irrisolte={unresolved}, '
        'richieste_api_extra=0'
    )
    if examples:
        print('DIAG mapping storico locale esempi: ' + ' | '.join(examples))

    return mapped_existing + local_mapped


safe.multi.radar_job.map_retail_extras = map_with_local_history


if __name__ == '__main__':
    safe.multi.radar_job.main()
