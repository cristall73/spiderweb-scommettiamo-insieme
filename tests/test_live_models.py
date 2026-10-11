import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
import pandas as pd
from update_today import OutcomeProbability,feature_row,latest_histories
from backtest_multisource_real import add_features,FEATURES

class ModelTests(unittest.TestCase):
    def test_outcomes_and_double_chances_are_coherent(self):
        class Model:
            classes_=np.array(['AWAY','DRAW','HOME'])
            def predict_proba(self,x):return np.array([[.2,.3,.5]])
        m=Model();ps={c:OutcomeProbability(m,[c]).predict_proba(None)[0,1] for c in m.classes_}
        self.assertAlmostEqual(sum(ps.values()),1)
        self.assertAlmostEqual(OutcomeProbability(m,['HOME','DRAW']).predict_proba(None)[0,1],.8)
    def test_training_and_live_features_agree_without_future_result(self):
        rows=[dict(Date=f'2026-09-{i+1:02d}',LeagueName='Test',HomeTeam='A',AwayTeam='B',
                   FTHG=i%4,FTAG=i%3) for i in range(12)]
        history=pd.DataFrame(rows[:-1]);hist,teams=latest_histories(history)
        live=feature_row(hist,'Test','A','B').iloc[0]
        expected=add_features(pd.DataFrame(rows)).iloc[-1]
        np.testing.assert_allclose(live[FEATURES].astype(float),expected[FEATURES].astype(float))

if __name__=='__main__':unittest.main()
