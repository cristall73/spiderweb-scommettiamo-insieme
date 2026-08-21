from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

INPUT=Path('data/processed/football_features.csv')
OUT=Path('data/output/walk_forward_1x2.csv')
SUMMARY=Path('data/output/walk_forward_summary.csv')
NUMERIC=['market_prob_home','market_prob_draw','market_prob_away','market_margin','home_pts_5','away_pts_5','home_gf_5','away_gf_5','home_ga_5','away_ga_5','home_btts_5','away_btts_5','home_over25_5','away_over25_5','home_venue_pts_5','away_venue_pts_5','home_venue_gf_5','away_venue_gf_5','home_venue_ga_5','away_venue_ga_5','diff_pts_5','diff_gf_5','diff_ga_5','home_pts_10','away_pts_10','diff_pts_10']
CAT=['league']
SEASONS=['2122','2223','2324','2425','2526']

def model():
 n=Pipeline([('imputer',SimpleImputer(strategy='median')),('scale',StandardScaler())])
 c=Pipeline([('imputer',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore'))])
 return Pipeline([('prep',ColumnTransformer([('num',n,NUMERIC),('cat',c,CAT)])),('model',LogisticRegression(max_iter=2000))])

def profit(r,s,o): return o-1 if r==s else -1.0

def main():
 df=pd.read_csv(INPUT,dtype={'season':str}); df=df[df.result_1x2.isin(['H','D','A'])].copy(); df=df[(df.home_matches_seen>=5)&(df.away_matches_seen>=5)].copy()
 rows=[]
 mapping={'H':('odds_home_ref','market_prob_home'),'D':('odds_draw_ref','market_prob_draw'),'A':('odds_away_ref','market_prob_away')}
 # expanding-window walk-forward: each season is predicted only from earlier seasons
 for i in range(2,len(SEASONS)):
  train_seasons=SEASONS[:i]; test_season=SEASONS[i]
  tr=df[df.season.isin(train_seasons)].copy(); te=df[df.season==test_season].copy()
  if tr.empty or te.empty: continue
  m=model(); m.fit(tr[NUMERIC+CAT],tr.result_1x2); probs=m.predict_proba(te[NUMERIC+CAT]); classes=list(m.named_steps['model'].classes_)
  for j,cl in enumerate(classes): te[f'p_{cl}']=probs[:,j]
  for _,r in te.iterrows():
   cand=[]
   for s,(oc,mc) in mapping.items():
    p=r.get(f'p_{s}'); o=r.get(oc); mp=r.get(mc)
    if pd.isna(p) or pd.isna(o) or pd.isna(mp) or o<=1: continue
    cand.append((float(p-mp),s,float(p),float(o)))
   if not cand: continue
   edge,s,p,o=max(cand,key=lambda x:x[0])
   rows.append({'test_season':test_season,'date':r.date,'league':r.league,'selection':s,'edge':edge,'odds':o,'profit_units':profit(r.result_1x2,s,o)})
 out=pd.DataFrame(rows); OUT.parent.mkdir(parents=True,exist_ok=True); out.to_csv(OUT,index=False)
 filters=[('Bundesliga_A_edge12_odds2_5',lambda x:(x.league=='Bundesliga')&(x.selection=='A')&(x.edge>=.12)&(x.odds>=2)&(x.odds<=5)),('Bundesliga_A_edge12_odds2_5to5',lambda x:(x.league=='Bundesliga')&(x.selection=='A')&(x.edge>=.12)&(x.odds>=2.5)&(x.odds<=5)),('SerieA_A_edge09_odds18_28',lambda x:(x.league=='Serie A')&(x.selection=='A')&(x.edge>=.09)&(x.odds>=1.8)&(x.odds<=2.8))]
 summary=[]
 for name,fn in filters:
  z=out[fn(out)].copy()
  for season in list(z.test_season.unique())+['TOTALE']:
   q=z if season=='TOTALE' else z[z.test_season==season]
   if q.empty: continue
   summary.append({'filter':name,'season':season,'bets':len(q),'profit_units':q.profit_units.sum(),'roi':q.profit_units.mean(),'hit_rate':(q.profit_units>0).mean(),'avg_odds':q.odds.mean()})
 pd.DataFrame(summary).to_csv(SUMMARY,index=False)
 print(pd.DataFrame(summary).to_string(index=False))
if __name__=='__main__': main()
