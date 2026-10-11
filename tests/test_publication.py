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

if __name__=='__main__':unittest.main()
