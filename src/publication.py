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
    """Allocate the three primary tickets together before the optional double.

    Keep alternative markets until allocation; the top market for an event
    does not necessarily fit the requested combined price.
    """
    slots = [('single', 1, 2.0, 3.0), ('double', 2, 1.90, 2.30),
             ('triple', 3, 2.80, 3.50)]
    options = {}
    for key, n, low, high in slots:
        candidates = []
        for book in sorted({r['bookmaker'] for r in rows}):
            pool = [r for r in rows if r['bookmaker'] == book]
            # Bound work, but retain up to three different markets per event.
            events = {}
            for r in pool:
                bucket = events.setdefault(r['event_id'], {})
                bucket.setdefault(r.get('selection_code', ''), r)
            pool = [r for bucket in list(events.values())[:24]
                    for r in list(bucket.values())[:3]]
            for legs in combinations(pool, n):
                ids = frozenset(r['event_id'] for r in legs)
                if len(ids) != n:
                    continue
                q = math.prod(r['odds'] for r in legs)
                probability = math.prod(r['model_probability'] for r in legs)
                if not low <= q <= high or probability < {1:0, 2:.35, 3:.25}[n]:
                    continue
                ticket = legs[0] if n == 1 else dict(legs=list(legs),
                    total_odds=round(q, 2), combined_probability=probability, bookmaker=book)
                candidates.append((probability, ids, ticket))
        # Different event sets preserve allocation choices across tickets.
        unique = {}
        for candidate in sorted(candidates, key=lambda x:-x[0]):
            unique.setdefault(candidate[1], candidate)
        options[key] = list(unique.values())[:60]
    best_score = (-1, -1)
    best = {}
    def allocate(index, used, chosen, quality):
        nonlocal best_score, best
        if index == len(slots):
            score = (len(chosen), quality)
            if score > best_score:
                best_score, best = score, dict(chosen)
            return
        key = slots[index][0]
        for probability, ids, ticket in options[key]:
            if not used.intersection(ids):
                chosen[key] = ticket
                allocate(index+1, used | ids, chosen, quality+probability)
                del chosen[key]
        allocate(index+1, used, chosen, quality)
    allocate(0, frozenset(), {}, 0)
    result = {key:best.get(key) for key, *_ in slots}
    used = {r['event_id'] for t in best.values() for r in t.get('legs', [t])}
    remaining = [r for r in rows if r['event_id'] not in used]
    # Optional second double only after single, double and triple allocation.
    aggressive = []
    for legs in combinations(remaining, 2):
        if legs[0]['bookmaker'] != legs[1]['bookmaker'] or legs[0]['event_id'] == legs[1]['event_id']:
            continue
        q = math.prod(r['odds'] for r in legs)
        probability = math.prod(r['model_probability'] for r in legs)
        if 2.50 <= q <= 2.80 and probability >= .35:
            aggressive.append(dict(legs=list(legs), total_odds=round(q,2),
                combined_probability=probability, bookmaker=legs[0]['bookmaker']))
    result['double_aggressive'] = max(aggressive, key=lambda t:t['combined_probability'], default=None)
    return result
