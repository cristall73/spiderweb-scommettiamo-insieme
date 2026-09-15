from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

import run_today_safe_sources as safe

ORIGINAL_MAP_RETAIL_EXTRAS = safe.multi.radar_job.map_retail_extras
ORIGINAL_BUILD_CANDIDATES = safe.multi.radar_job.build_candidates
HISTORY_PATH = Path('data/output/live_training.csv')
MIN_TEAM_MATCHES = 8

# Soglia minima gia richiesta dal modello per ciascuna famiglia. Serve per
# confrontare la QUALITA relativa del segnale, non la probabilita grezza.
# Senza normalizzazione 1X/X2 partono strutturalmente da probabilita piu alte
# e monopolizzano la classifica anche quando un O/U o 1X2 e piu informativo.
MARKET_FLOORS = {
    'OU25': 0.55,
    'BTTS': 0.55,
    'OVER15': 0.68,
    'UNDER15': 0.55,
    'OVER35': 0.55,
    'UNDER35': 0.68,
    'HOME': 0.55,
    'DRAW': 0.55,
    'AWAY': 0.55,
    'DC_1X': 0.68,
    'DC_X2': 0.68,
    'DC_12': 0.68,
}


def _country_matches(country: str, league: str) -> bool:
    country = str(country or '').strip().lower()
    league = str(league or '').strip().lower()
    if not country or country in ('world', 'europe'):
        return True
    aliases = {
        'england': ('england',), 'scotland': ('scotland',), 'argentina': ('argentina',),
        'spain': ('spain',), 'italy': ('italy',), 'germany': ('germany',),
        'france': ('france',), 'netherlands': ('netherlands',), 'portugal': ('portugal',),
        'belgium': ('belgium',), 'turkey': ('turkey',), 'denmark': ('denmark',),
        'sweden': ('sweden',), 'norway': ('norway',), 'brazil': ('brazil',),
        'colombia': ('colombia',), 'saudi-arabia': ('saudi arabia', 'saudi-arabia'),
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
        if safe.multi.radar_job.radar.team_match(name, hist_name) and count > best_count:
            best = hist_name
            best_count = count
    return best, best_count


def map_with_local_history(events):
    """Estende solo il mapping usando lo storico locale gia presente."""
    mapped_existing = ORIGINAL_MAP_RETAIL_EXTRAS(events)
    if not HISTORY_PATH.exists():
        print('DIAG mapping locale: live_training.csv assente; nessun mapping aggiuntivo.')
        return mapped_existing
    try:
        hist = pd.read_csv(
            HISTORY_PATH, usecols=['LeagueName', 'HomeTeam', 'AwayTeam'], low_memory=False
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

    local_mapped = ambiguous = unresolved = 0
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
            a_name, a_count = _matching_historical_team(away, counts)
            if h_name and a_name:
                candidates.append((league, min(h_count, a_count), h_name, a_name))
        if len(candidates) == 1:
            league, support, h_name, a_name = candidates[0]
            event['canonical_league'] = league
            event['local_history_map'] = True
            event['local_history_support'] = int(support)
            event['retail_extra'] = False
            local_mapped += 1
            if len(examples) < 8:
                examples.append(f'{home}-{away} -> {league} (supporto>={support})')
        elif len(candidates) > 1:
            ambiguous += 1
        else:
            unresolved += 1

    print('DIAG mapping storico locale: '
          f'mappate_esistenti={mapped_existing}, mappate_locali={local_mapped}, '
          f'ambigue_saltate={ambiguous}, irrisolte={unresolved}, richieste_api_extra=0')
    if examples:
        print('DIAG mapping storico locale esempi: ' + ' | '.join(examples))
    return mapped_existing + local_mapped


def build_candidates_balanced(events, models, hist, teams, rules):
    """Mantiene tutti i filtri originali ma rimuove il vantaggio matematico
    artificiale delle doppie chance nella graduatoria finale.

    Non imponiamo quote di mercato: vince il segnale che supera maggiormente la
    propria soglia minima. Quindi 1X/X2 restano possibili, ma non sono favoriti
    solo perche hanno naturalmente probabilita assolute piu alte.
    """
    rows = ORIGINAL_BUILD_CANDIDATES(events, models, hist, teams, rules)
    for row in rows:
        target = str(row.get('target') or '')
        p = float(row.get('model_probability') or 0.0)
        floor = MARKET_FLOORS.get(target, 0.55)
        relative_strength = max(0.0, min(1.0, (p - floor) / max(1e-9, 1.0 - floor)))
        # 75% forza relativa al proprio mercato, 25% probabilita assoluta.
        # Nessun bonus/penalita per il nome del mercato.
        row['score'] = round(relative_strength * 0.75 + p * 0.25, 5)
        row['market_floor'] = floor
        row['relative_strength'] = round(relative_strength, 5)
    rows.sort(key=lambda r: (-float(r.get('score') or 0), -float(r.get('model_probability') or 0)))
    counts = Counter(str(r.get('market') or r.get('target') or '') for r in rows[:12])
    print('DIAG scoring mercati bilanciato top12: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    return rows


safe.multi.radar_job.map_retail_extras = map_with_local_history
safe.multi.radar_job.build_candidates = build_candidates_balanced


if __name__ == '__main__':
    safe.multi.radar_job.main()
