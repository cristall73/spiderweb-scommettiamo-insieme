import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from publication import priced_rows, tickets

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,11,10,tzinfo=timezone.utc)
        self.row=dict(event_id=1,selection_code='OVER25',start_timestamp=self.now.timestamp()+3600,
            min_acceptable_odds=1.8,model_probability=.7,score=.8)
        self.offer=dict(selection_code='OVER25',odds=2,bookmaker='Book',updated_at=self.now.isoformat())
    def test_threshold_is_not_quote(self):
        self.assertEqual(priced_rows([self.row],{},self.now),[])
    def test_rejects_stale_wrong_market_started_and_low_prices(self):
        for change in [dict(updated_at='2026-10-10T10:00:00+00:00'),dict(odds=1.7),dict(odds='NaN'),dict(selection_code='UNDER25')]:
            self.assertEqual(priced_rows([self.row],{'1':[{**self.offer,**change}]},self.now),[])
        self.assertEqual(priced_rows([{**self.row,'start_timestamp':0}],{'1':[self.offer]},self.now),[])
    def test_provider_three_hour_update_is_usable(self):
        offer={**self.offer,'updated_at':'2026-10-11T07:00:00+00:00'}
        self.assertEqual(len(priced_rows([self.row],{'1':[offer]},self.now)),1)
    def test_rule_upper_bound_is_respected(self):
        self.assertEqual(priced_rows([{**self.row,'max_acceptable_odds':1.9}],{'1':[self.offer]},self.now),[])
    def test_provider_string_prices_are_numeric(self):
        row=priced_rows([self.row],{'1':[{**self.offer,'odds':'2.1'}]},self.now)[0]
        self.assertIsInstance(row['odds'],float)
        self.assertIsNotNone(tickets([row])['single'])
    def test_observed_price_retained(self):
        result=priced_rows([self.row],{'1':[self.offer]},self.now)[0]
        self.assertEqual(result['odds'],2)
        self.assertAlmostEqual(result['expected_value'],.4)
    def test_no_mixed_bookmakers_or_repeated_events(self):
        rows=[dict(event_id=i,odds=1.45,model_probability=.8,score=.9,bookmaker='A' if i%2 else 'B') for i in range(1,9)]
        result=tickets(rows)
        used=[]
        for t in result.values():
            if not t:continue
            legs=t.get('legs',[t]);self.assertEqual(len({l['bookmaker'] for l in legs}),1)
            used.extend(l['event_id'] for l in legs)
        self.assertEqual(len(used),len(set(used)))

class AllocationTests(unittest.TestCase):
    def test_primary_three_before_optional_second_double(self):
        rows=[dict(event_id=i, odds=q, model_probability=p, score=p,
                   bookmaker='A',selection_code='HOME')
              for i,q,p in [(1,2.1,.6),(2,1.45,.8),(3,1.45,.8),
                            (4,1.45,.8),(5,1.45,.8),(6,1.45,.8)]]
        result=tickets(rows)
        self.assertTrue(all(result[k] for k in ('single','double','triple')))
        self.assertIsNone(result['double_aggressive'])
        ids=[r['event_id'] for t in result.values() if t for r in t.get('legs',[t])]
        self.assertEqual(len(ids),len(set(ids)))
    def test_alternative_market_can_supply_required_price(self):
        rows=[dict(event_id=i, odds=q, model_probability=p, score=p,
                   bookmaker='A',selection_code=code)
              for i,q,p,code in [(1,1.1,.95,'DC_1X'),(1,2.1,.6,'HOME'),
                                 (2,1.45,.8,'OVER15'),(3,1.45,.8,'OVER15')]]
        result=tickets(rows)
        self.assertEqual(result['single']['selection_code'],'HOME')
        self.assertIsNotNone(result['double'])
    def test_optional_double_does_not_claim_below_250(self):
        rows=[dict(event_id=i,odds=1.53,model_probability=.8,score=.8,bookmaker='A') for i in range(6)]
        self.assertIsNone(tickets(rows)['double_aggressive'])

if __name__=='__main__':unittest.main()
