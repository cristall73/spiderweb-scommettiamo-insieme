"""Bounded, paced API-Football client and full-time odds decoder."""
import os
import time
import requests

class FeedError(RuntimeError):
    pass

class FootballClient:
    def __init__(self, key=None, session=None, clock=time.monotonic, sleep=time.sleep):
        self.key = key if key is not None else os.getenv('API_FOOTBALL_KEY','').strip()
        self.session = session or requests.Session()
        self.clock, self.sleep = clock, sleep
        self.last_call = None
        self.remaining = None
        self.calls = 0

    def get(self, path, params):
        if not self.key:
            raise FeedError('Clé API-Football assente'.replace('Clé','Chiave'))
        if self.remaining is not None and self.remaining <= 2:
            raise FeedError('Budget giornaliero API quasi esaurito; quote mancanti da verificare manualmente')
        for attempt in range(2):
            if self.last_call is not None:
                delay = 7.0 - (self.clock() - self.last_call)
                if delay > 0:
                    self.sleep(delay)
            self.last_call = self.clock()
            self.calls += 1
            try:
                response = self.session.get('https://v3.football.api-sports.io'+path,
                    params=params, headers={'x-apisports-key':self.key,'Accept':'application/json'},timeout=30)
            except requests.RequestException:
                raise FeedError('Connessione al provider non disponibile') from None
            remaining = response.headers.get('x-ratelimit-requests-remaining')
            if remaining is not None:
                try:self.remaining = int(remaining)
                except ValueError:pass
            if response.status_code == 429 and attempt == 0:
                try:delay = min(60,max(7,float(response.headers.get('Retry-After',60))))
                except ValueError:delay = 60
                self.sleep(delay)
                continue
            if response.status_code != 200:
                raise FeedError(f'Provider quote HTTP {response.status_code}')
            try:data = response.json()
            except ValueError:raise FeedError('Risposta provider non leggibile') from None
            errors = data.get('errors')
            if errors:
                text = ' '.join(str(v) for v in errors.values()) if isinstance(errors,dict) else str(errors)
                if 'rate' in text.lower() and 'limit' in text.lower() and attempt == 0:
                    self.sleep(60)
                    continue
                # Do not expose response contents or credentials in diagnostics.
                reason = 'limite richieste' if 'limit' in text.lower() else 'piano o endpoint non disponibile'
                raise FeedError('Provider: '+reason)
            return data
        raise FeedError('Limite per minuto del provider raggiunto')


def decode_offers(item):
    out = []
    for book in item.get('bookmakers') or []:
        if not book.get('name'):continue
        for bet in book.get('bets') or []:
            codes = {1:{'Home':'HOME','Draw':'DRAW','Away':'AWAY'},
                     8:{'Yes':'BTTS_YES','No':'BTTS_NO'},
                     12:{'Home/Draw':'DC_1X','Draw/Away':'DC_X2','Home/Away':'DC_12'}}
            bid = bet.get('id')
            for value in bet.get('values') or []:
                label = value.get('value')
                code = codes.get(bid,{}).get(label)
                if bid == 5:
                    code = {'Over 1.5':'OVER15','Under 1.5':'UNDER15',
                            'Over 2.5':'OVER25','Under 2.5':'UNDER25',
                            'Over 3.5':'OVER35','Under 3.5':'UNDER35'}.get(label)
                if code:
                    out.append({'selection_code':code,'odds':value.get('odd'),
                                'bookmaker':book['name'],'updated_at':item.get('update'),
                                'odds_source':'API-Football'})
    return out


def collect_odds(client, events, date_iso, max_calls=24):
    """Fetch every page for selected leagues, then individual uncovered fixtures.
    Coverage is independent from score so high-probability selections do not
    consume the entire budget before smaller prices are inspected.
    """
    offers, diagnostics = {}, []
    wanted = {str(e['event_id']) for e in events}
    groups = {}
    for e in events:
        if e.get('api_league_id'):
            groups.setdefault(e['api_league_id'],[]).append(e)
    priority = {135:0,39:1,140:2,78:3,61:4,136:5,40:6,2:7,3:8,848:9}
    ordered = sorted(groups,key=lambda lid:(priority.get(lid,20),-len(groups[lid]),lid))
    start_calls = client.calls
    for lid in ordered:
        page, total = 1, 1
        while page <= total and client.calls-start_calls < max_calls:
            try:data=client.get('/odds',{'date':date_iso,'league':lid,'page':page})
            except FeedError as exc:
                diagnostics.append(str(exc))
                # Subscription/day budget applies to all leagues; no wasteful retries.
                return offers, diagnostics
            total = int((data.get('paging') or {}).get('total') or 1)
            for item in data.get('response') or []:
                eid = str((item.get('fixture') or {}).get('id'))
                if eid in wanted:
                    decoded = decode_offers(item)
                    if decoded:offers.setdefault(eid,[]).extend(decoded)
            page += 1
        if page <= total:
            diagnostics.append('Copertura quote parziale: budget della scansione raggiunto')
    return offers, diagnostics
