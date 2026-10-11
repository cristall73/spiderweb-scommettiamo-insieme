"""Keep the existing model; replace threshold-based tickets with observed prices."""
import json
from datetime import datetime
import run_today_local_mapping as local
from publication import POPULAR, priced_rows, tickets

job = local.safe.multi.radar_job
original = job.build_candidates
captured = []
calendar = []


def candidates(events, models, hist, teams, rules):
    now = datetime.now(job.ROME)
    events = [e for e in events if e.get('canonical_league') in POPULAR
              and float(e.get('start_timestamp') or 0) > now.timestamp()]
    calendar.extend(events)
    rows = original(events, models, hist, teams, rules)
    lookup = {str(e['event_id']):e for e in events}
    for r in rows:
        r['start_timestamp'] = lookup[str(r['event_id'])]['start_timestamp']
        r['odds'] = None
        r['analysis_only'] = True
    captured.extend(rows)
    # Legacy main expects thresholds: only used for intermediate compatibility.
    return [{**r, 'odds':r['min_acceptable_odds']} for r in rows]


def main():
    if job.OUT.exists():
        old = json.loads(job.OUT.read_text())
        archive = job.OUT.parent / 'daily_snapshots'
        archive.mkdir(exist_ok=True)
        stamp = str(old.get('generated_at') or 'unknown').replace(':','-').replace('+','_')
        (archive / (stamp + '.json')).write_text(json.dumps(old,ensure_ascii=False))
    job.build_candidates = candidates
    job.main()
    now = datetime.now(job.ROME)
    offers = {}
    diagnostics = []
    ids = list(dict.fromkeys(str(r['event_id']) for r in captured))
    # Bounded calls; missing subscription/data never becomes a fabricated price.
    for eid in [x for x in ids if x.isdigit()][:12]:
        try:
            data, _ = job.radar.api_get('/odds', {'fixture':eid})
            for item in data.get('response') or []:
                if str((item.get('fixture') or {}).get('id')) != eid:
                    continue
                updated = item.get('update')
                for book in item.get('bookmakers') or []:
                    # Full-time markets only: exact IDs avoid first-half substitutions.
                    for bet in book.get('bets') or []:
                        codes = {1:{'Home':'HOME','Draw':'DRAW','Away':'AWAY'},
                                 8:{'Yes':'BTTS_YES','No':'BTTS_NO'},
                                 12:{'Home/Draw':'DC_1X','Draw/Away':'DC_X2','Home/Away':'DC_12'}}
                        bid = bet.get('id')
                        for value in bet.get('values') or []:
                            label = value.get('value')
                            code = codes.get(bid, {}).get(label)
                            if bid == 5:
                                code = {'Over 1.5':'OVER15','Under 1.5':'UNDER15',
                                        'Over 2.5':'OVER25','Under 2.5':'UNDER25',
                                        'Over 3.5':'OVER35','Under 3.5':'UNDER35'}.get(label)
                            if code:
                                offers.setdefault(eid, []).append({'selection_code':code,
                                    'odds':value.get('odd'), 'bookmaker':book.get('name'),
                                    'updated_at':updated, 'odds_source':'API-Football'})
        except Exception:
            diagnostics.append('Fonte quote non disponibile; alcune partite restano analisi.')
            break
    rows = priced_rows(captured, offers, now)
    payload = json.loads(job.OUT.read_text())
    payload.update(tickets(rows))
    payload.update(mode='observed_odds', shortlist=captured[:120], priced_shortlist=rows[:120],
        candidate_count=len(captured), fixtures_with_odds=len(offers),
        playable_count=len({r['event_id'] for r in rows}),
        popular_fixtures_count=len(calendar), calendar=calendar[:100],
        odds_diagnostics=diagnostics,
        note='Campionati principali e seconde divisioni selezionate. Le quote mostrate hanno fonte, bookmaker e orario; non sono confermate Sisal. Schedine solo con quote recenti (massimo 2 ore), stesso bookmaker e incontri distinti. Probabilità del modello non calibrate: non sono percentuali di successo garantite. Le analisi senza quote restano consultabili, senza schedine automatiche.')
    job.OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')

if __name__ == '__main__':
    main()
