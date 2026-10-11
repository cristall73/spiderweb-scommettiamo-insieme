import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from odds_feed import FootballClient, collect_odds, decode_offers

class FakeResponse:
    status_code=200
    headers={'x-ratelimit-requests-remaining':'95'}
    def json(self):return {'response':[]}

class FeedTests(unittest.TestCase):
    def test_requests_are_paced(self):
        state={'time':0}; waits=[]
        def sleep(n):waits.append(n);state['time']+=n
        class Session:
            def get(self,*a,**k):return FakeResponse()
        client=FootballClient('fake',Session(),lambda:state['time'],sleep)
        client.get('/odds',{});client.get('/odds',{})
        self.assertEqual(waits,[7])
    def test_all_pages_and_fixture_identity(self):
        class Client:
            calls=0
            def get(self,path,params):
                self.calls+=1
                return {'paging':{'total':2},'response':[{'fixture':{'id':params['page']},
                    'update':'2026-10-11T10:00:00Z','bookmakers':[{'name':'Book','bets':[
                        {'id':1,'values':[{'value':'Home','odd':'2.1'}]}]}]}]}
        c=Client();offers,errors=collect_odds(c,[{'event_id':2,'api_league_id':135}],'2026-10-11')
        self.assertEqual(c.calls,2);self.assertEqual(set(offers),{'2'});self.assertFalse(errors)
    def test_fixture_fallback_when_date_and_season_queries_are_denied(self):
        from odds_feed import FeedError
        class Client:
            calls=0
            def get(self,path,params):
                self.calls+=1
                if 'fixture' not in params:raise FeedError('Unavailable query')
                return {'response':[{'fixture':{'id':params['fixture']},'update':'2026-10-11T10:00:00Z',
                         'bookmakers':[{'name':'Book','bets':[{'id':1,'values':[{'value':'Home','odd':'2'}]}]}]}]}
        c=Client();offers,_=collect_odds(c,[{'event_id':1,'api_league_id':135,'api_season':2026}], '2026-10-11')
        self.assertIn('1',offers);self.assertEqual(c.calls,2)
    def test_missing_fixture_is_fetched_after_complete_bulk_pages(self):
        class Client:
            calls=0
            def get(self,path,params):
                self.calls+=1
                eid=params.get('fixture',1)
                return {'paging':{'total':1},'response':[{'fixture':{'id':eid},
                    'update':'2026-10-11T10:00:00Z','bookmakers':[{'name':'Book','bets':[
                        {'id':1,'values':[{'value':'Home','odd':'2.1'}]}]}]}]}
        c=Client()
        offers,errors=collect_odds(c,[{'event_id':1},{'event_id':2}], '2026-10-11')
        self.assertEqual(set(offers),{'1','2'})
        self.assertEqual(c.calls,2)
        self.assertFalse(errors)

    def test_first_half_is_not_full_time(self):
        item={'bookmakers':[{'name':'Book','bets':[{'id':6,'name':'First Half Winner',
                    'values':[{'value':'Home','odd':'2'}]}]}]}
        self.assertEqual(decode_offers(item),[])
    def test_budget_caps_pagination(self):
        class Client:
            calls=0
            def get(self,*args):self.calls+=1;return {'paging':{'total':10},'response':[]}
        c=Client();_,errors=collect_odds(c,[{'event_id':1,'api_league_id':135}],'2026-10-11',2)
        self.assertEqual(c.calls,2);self.assertTrue(errors)

if __name__=='__main__':unittest.main()
