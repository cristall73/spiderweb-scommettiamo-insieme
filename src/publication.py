"""Publication policy: measured prices and one bookmaker per ticket."""
import math
from itertools import combinations
from datetime import datetime

# Provider refreshes pre-match odds about every 3h; allow one cycle plus 1h.
MAX_PRICE_AGE_SECONDS = 4 * 3600

POPULAR = {'England Premier League','England Championship','Italy Serie A','Italy Serie B',
 'Spain La Liga','Spain Segunda','Germany Bundesliga','Germany 2. Bundesliga',
 'France Ligue 1','France Ligue 2','Portugal Primeira Liga','Netherlands Eredivisie',
 'Belgium First Division A','Scotland Premiership','Turkey Super Lig','Greece Super League',
 'Austria Bundesliga','Switzerland Super League','Denmark Superliga','Sweden Allsvenskan',
 'Norway Eliteserien','USA MLS','Brazil Serie A','Argentina Primera Division'}


def future(row, now):
    return float(row.get('start_timestamp') or 0) > now.timestamp()


def priced_rows(analyses, offers, now):
    rows = []
    for r in analyses:
        if not future(r, now):
            continue
        for o in offers.get(str(r['event_id']), []):
            if o['selection_code'] != r['selection_code']:
                continue
            try:
                price = float(o['odds'])
                updated = datetime.fromisoformat(o['updated_at'].replace('Z','+00:00'))
                age = (now - updated).total_seconds()
            except (ValueError, TypeError, KeyError):
                continue
            if not math.isfinite(price) or not 1 < price <= 100 or not 0 <= age <= MAX_PRICE_AGE_SECONDS:
                continue
            if price < r['min_acceptable_odds'] or price > float(r.get('max_acceptable_odds') or 100):
                continue
            p = r['model_probability']
            rows.append({**r, **o, 'odds':price,'analysis_only':False,'needs_bookmaker_check': True,
                         'edge': round(p - 1 / price, 4),
                         'expected_value': round(p * price - 1, 4)})
    return sorted(rows, key=lambda r: (-r['score'], -r['model_probability']))


def tickets(rows):
    used = set()
    single = next((r for r in rows if 2 <= r['odds'] <= 3), None)
    if single:
        used.add(single['event_id'])
    def combo(n, low, high):
        best = None
        for book in sorted({r['bookmaker'] for r in rows}):
            best_events = {}
            for r in rows:
                if r['bookmaker'] == book and r['event_id'] not in used:
                    best_events.setdefault(r['event_id'],r)
            pool = list(best_events.values())[:24]
            for legs in combinations(pool, n):
                if len({r['event_id'] for r in legs}) != n:
                    continue
                q = math.prod(r['odds'] for r in legs)
                p = math.prod(r['model_probability'] for r in legs)
                if not low <= q <= high or p < {2:.35,3:.25}[n]:
                    continue
                if best is None or p > best['combined_probability']:
                    best = {'legs':list(legs), 'total_odds':round(q,2),
                            'combined_probability':p, 'bookmaker':book}
        if best:
            used.update(r['event_id'] for r in best['legs'])
        return best
    double = combo(2, 1.90, 2.30)
    aggressive = combo(2, 2.30, 2.80) or combo(2, 1.90, 2.30)
    triple = combo(3, 2.80, 3.50)
    return dict(single=single, double=double, double_aggressive=aggressive, triple=triple)
