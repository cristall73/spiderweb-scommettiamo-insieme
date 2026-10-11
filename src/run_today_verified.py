"""Calendar, model analyses and observed odds; no fabricated market prices."""
import json
from datetime import datetime
import pandas as pd
import run_today_local_mapping as local
from publication import POPULAR, priced_rows, tickets
from odds_feed import FootballClient, FeedError, collect_odds
from refresh_live_history import refresh

job = local.safe.multi.radar_job


def identity_safe(event):
    # Never infer a first-team league solely from similar team names.
    import re
    texts = [str(event.get(k) or '') for k in ('home_team','away_team','league')]
    return not any(re.search(r'\b(ii|iii|u\s?-?\d{2}|reserves?|youth|women)\b|\s+B$',text,re.I) for text in texts)


def main():
    now = datetime.now(job.ROME)
    date_iso = now.date().isoformat()
    client = FootballClient()
    diagnostics = []
    previous_offers = {}
    if job.OUT.exists():
        old = json.loads(job.OUT.read_text())
        if old.get('date') == date_iso:previous_offers=old.get('observed_offers') or {}
        archive = job.OUT.parent / 'daily_snapshots'
        archive.mkdir(exist_ok=True)
        stamp = str(old.get('generated_at') or 'unknown').replace(':','-').replace('+','_')
        (archive / (stamp + '.json')).write_text(json.dumps(old,ensure_ascii=False))
    try:
        data = client.get('/fixtures',{'date':date_iso,'timezone':'Europe/Rome'})
        raw = [x for x in data.get('response') or [] if job.radar.senior_fixture(x)]
    except FeedError as exc:
        raw = []
        diagnostics.append(str(exc))
    events = [job.radar.fixture_to_event(x) for x in raw]
    for e in events:e['calendar_source']='API-Football'
    # Use established league identity, never the old fuzzy history remapping.
    eligible = [e for e in events if e.get('canonical_league') in POPULAR
                and identity_safe(e) and e['start_timestamp']>now.timestamp()]
    if not eligible:
        fallback, _ = local.safe.enhanced_combined_calendar(date_iso,now)
        events, _ = job.merge_calendar_sources(events,fallback)
        eligible = [e for e in events if e.get('canonical_league') in POPULAR
                    and identity_safe(e) and e['start_timestamp']>now.timestamp()]
    historical = job.radar.load_live_training()
    historical, history_refresh = refresh(historical,eligible,now)
    historical = historical[pd.to_datetime(historical['Date'],errors='coerce').dt.date < now.date()]
    hist, teams = job.base.latest_histories(historical)
    models = job.base.train_live_models(historical)
    rules = job.base.load_live_rules()
    analyses = local.build_candidates_balanced(eligible,models,hist,teams,rules)
    lookup = {str(e['event_id']):e for e in eligible}
    for r in analyses:
        r.update(start_timestamp=lookup[str(r['event_id'])]['start_timestamp'],odds=None,analysis_only=True)
    supported = {str(r['event_id']) for r in analyses}
    for e in eligible:e['model_supported']=str(e['event_id']) in supported
    offers, quote_diagnostics = collect_odds(client,eligible,date_iso,max_calls=20)
    diagnostics.extend(quote_diagnostics)
    # Preserve still-valid observations when the provider is temporarily unavailable.
    # New observations replace old prices for the same bookmaker and selection.
    for eid, old_prices in previous_offers.items():
        latest = {(o['bookmaker'],o['selection_code']):o for o in old_prices}
        latest.update({(o['bookmaker'],o['selection_code']):o for o in offers.get(eid,[])})
        offers[eid]=list(latest.values())
    finished = datetime.now(job.ROME)
    rows = priced_rows(analyses,offers,finished)
    published = tickets(rows)
    bookmaker_tickets = {book:tickets([r for r in rows if r['bookmaker']==book])
                         for book in sorted({r['bookmaker'] for r in rows})}
    rejection_summary = dict(analysed_events=len(supported), events_without_analysis=len(eligible)-len(supported),
        events_without_quotes=sum(str(e['event_id']) not in offers for e in eligible),
        events_with_valid_prices=len({r['event_id'] for r in rows}),
        tickets_available=sum(bool(published[k]) for k in ('single','double','triple')))
    payload = dict(generated_at=finished.isoformat(timespec='seconds'),date=date_iso,
        source='Calendario e quote API-Football; storico Football-Data; modello SpiderWeb',
        mode='observed_odds',selection_diagnostics=rejection_summary,history_refresh=history_refresh,fixtures_count=len(events),api_football_fixtures_count=len(raw),
        popular_fixtures_count=len(eligible),eligible_history_count=len({r['event_id'] for r in analyses}),
        fixtures_with_odds=len(offers),playable_count=len({r['event_id'] for r in rows}),
        candidate_count=len(analyses),active_rules=len(rules),shortlist=analyses,
        priced_shortlist=rows,calendar=eligible,odds_diagnostics=diagnostics,
        observed_offers=offers,bookmaker_tickets=bookmaker_tickets,
        odds_requests_used=client.calls,api_requests_remaining=client.remaining,
        note='Quote reali del provider, con bookmaker e orario di aggiornamento. Verifica sempre il prezzo attuale e la disponibilità sul tuo bookmaker. Singole alternative visibili anche sotto quota 2; multiple con stesso bookmaker e senza incontri duplicati. Le stime del modello e i backtest non garantiscono il risultato.',**published)
    job.OUT.parent.mkdir(parents=True,exist_ok=True)
    job.OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:payload[k] for k in ('popular_fixtures_count','candidate_count','fixtures_with_odds',
        'playable_count','odds_requests_used','api_requests_remaining','odds_diagnostics')},ensure_ascii=False))

if __name__=='__main__':main()
