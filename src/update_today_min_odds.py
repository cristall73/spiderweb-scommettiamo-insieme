from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import update_today as base
import update_today_apifootball_safe as safe

radar = safe.radar
ROME = ZoneInfo('Europe/Rome')
OUT = Path('data/output/today.json')


def ceil2(x: float) -> float:
    return math.ceil((x - 1e-12) * 100) / 100.0


def rules_for(rules, target, league, selection):
    out = []
    for r in rules:
        if str(r.get('target')) != target:
            continue
        if str(r.get('league')) not in ('TUTTI', league):
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
                    'needs_bookmaker_check': True,
                    'source': 'Quota minima calcolata dal modello SpiderWeb + sistema walk-forward',
                })
    return rows


def main():
    now = datetime.now(ROME)
    date_iso = now.date().isoformat()
    historical = radar.load_live_training()
    hist, teams = base.latest_histories(historical)
    models = base.train_live_models(historical)
    rules = base.load_live_rules()

    fixtures_data, headers = radar.api_get('/fixtures', {'date': date_iso, 'timezone': 'Europe/Rome'})
    raw = [x for x in (fixtures_data.get('response') or []) if radar.senior_fixture(x)]
    events = [radar.fixture_to_event(x) for x in raw]
    eligible = [e for e in events if e.get('canonical_league')]

    rows = build_candidates(eligible, models, hist, teams, rules)
    rows = base.best_per_event(rows)
    single = rows[0] if rows else None
    double = base.pick_combo(rows, 2, 1.80, 4.50) if len(rows) >= 2 else None
    triple = base.pick_combo(rows, 3, 2.30, 7.50) if len(rows) >= 3 else None

    remaining = headers.get('x-ratelimit-requests-remaining') or headers.get('X-RateLimit-Requests-Remaining')
    payload = {
        'generated_at': now.isoformat(timespec='seconds'),
        'date': date_iso,
        'source': 'API-Football calendario mondiale + probabilita SpiderWeb; quota minima da verificare sul bookmaker',
        'mode': 'min_acceptable_odds',
        'fixtures_count': len(events),
        'eligible_history_count': len(eligible),
        'fixtures_with_odds': 0,
        'candidate_count': len(rows),
        'active_rules': len(rules),
        'api_requests_remaining': remaining,
        'single': single,
        'double': double,
        'triple': triple,
        'shortlist': rows[:40],
        'note': ('Le quote live non sono necessarie per generare la shortlist. SpiderWeb calcola la quota minima '
                 'accettabile per rispettare l edge del sistema walk-forward. La giocata diventa valida solo se '
                 'il bookmaker offre una quota uguale o superiore a quella indicata.'),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'date': date_iso,
        'fixtures_globali': len(events),
        'con_storico': len(eligible),
        'candidati_quota_minima': len(rows),
        'migliore': None if not single else f"{single['home_team']} - {single['away_team']} / {single['selection']} >= {single['min_acceptable_odds']}",
        'richieste_api_rimanenti': remaining,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
