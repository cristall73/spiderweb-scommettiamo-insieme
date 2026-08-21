from __future__ import annotations

from collections import defaultdict, deque
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

OUT = Path('data/output')
DETAIL = OUT / 'backtest_multisource_real.csv'
SUMMARY = OUT / 'backtest_multisource_summary.csv'
STABLE = OUT / 'backtest_multisource_stable.csv'

SOURCES = {
    'Premier League': 'https://raw.githubusercontent.com/nm2890/football-data/main/data/england/premier-league.csv',
    'Serie A': 'https://raw.githubusercontent.com/nm2890/football-data/main/data/italy/serie-a.csv',
    'Bundesliga': 'https://raw.githubusercontent.com/nm2890/football-data/main/data/germany/bundesliga.csv',
    'La Liga': 'https://raw.githubusercontent.com/nm2890/football-data/main/data/spain/laliga.csv',
    'Ligue 1': 'https://raw.githubusercontent.com/nm2890/football-data/main/data/france/ligue-1.csv',
}

FEATURES = [
    'home_pts5','away_pts5','home_gf5','away_gf5','home_ga5','away_ga5',
    'home_over5','away_over5','home_btts5','away_btts5',
    'home_pts10','away_pts10','home_gf10','away_gf10','home_ga10','away_ga10',
    'home_over10','away_over10','home_btts10','away_btts10',
]


def load_data() -> pd.DataFrame:
    frames=[]
    for league,url in SOURCES.items():
        r=requests.get(url,timeout=40)
        r.raise_for_status()
        df=pd.read_csv(StringIO(r.text))
        df['LeagueName']=league
        frames.append(df)
    df=pd.concat(frames,ignore_index=True)
    df['Date']=pd.to_datetime(df['Date'],errors='coerce')
    df=df.dropna(subset=['Date','Season','HomeTeam','AwayTeam','FTHG','FTAG']).copy()
    df=df.sort_values(['Date','LeagueName','HomeTeam','AwayTeam']).reset_index(drop=True)
    return df


def snap(hist: deque, n: int):
    x=list(hist)[-n:]
    if len(x)<5:
        return [np.nan]*5
    return [
        np.mean([r['pts'] for r in x]), np.mean([r['gf'] for r in x]),
        np.mean([r['ga'] for r in x]), np.mean([r['over'] for r in x]),
        np.mean([r['btts'] for r in x]),
    ]


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    hist=defaultdict(lambda:deque(maxlen=10))
    rows=[]
    for _,r in df.iterrows():
        hk=(r.LeagueName,r.HomeTeam); ak=(r.LeagueName,r.AwayTeam)
        h5=snap(hist[hk],5); a5=snap(hist[ak],5); h10=snap(hist[hk],10); a10=snap(hist[ak],10)
        rows.append(dict(zip(FEATURES,h5[:3]+a5[:3]+[h5[3],a5[3],h5[4],a5[4]]+h10[:3]+a10[:3]+[h10[3],a10[3],h10[4],a10[4]])))
        hg=int(r.FTHG); ag=int(r.FTAG)
        hp,ap=(3,0) if hg>ag else ((0,3) if hg<ag else (1,1))
        over=int(hg+ag>2.5); btts=int(hg>0 and ag>0)
        hist[hk].append({'pts':hp,'gf':hg,'ga':ag,'over':over,'btts':btts})
        hist[ak].append({'pts':ap,'gf':ag,'ga':hg,'over':over,'btts':btts})
    return pd.concat([df,pd.DataFrame(rows)],axis=1)


def make_model():
    return Pipeline([
        ('impute',SimpleImputer(strategy='median')),
        ('scale',StandardScaler()),
        ('model',LogisticRegression(max_iter=2000,class_weight='balanced')),
    ])


def no_vig_prob(o1,o2):
    a,b=1/o1,1/o2
    s=a+b
    return a/s,b/s


def settle(target,sel,hg,ag,odds):
    if target=='OU25': won=(hg+ag>2.5) if sel=='OVER25' else (hg+ag<2.5)
    else: won=(hg>0 and ag>0) if sel=='BTTS_YES' else not (hg>0 and ag>0)
    return odds-1 if won else -1.0


def walk_forward(df,target):
    if target=='OU25': yes_col,no_col='over_2.5_close','under_2.5_close'
    else: yes_col,no_col='bts_yes_close','bts_no_close'
    d=df.dropna(subset=[yes_col,no_col]).copy()
    d=d[(pd.to_numeric(d[yes_col],errors='coerce')>1)&(pd.to_numeric(d[no_col],errors='coerce')>1)]
    seasons=sorted(d.Season.astype(str).unique())
    rows=[]
    for i in range(3,len(seasons)):
        test_season=seasons[i]
        train=d[d.Season.astype(str).isin(seasons[:i])].copy()
        test=d[d.Season.astype(str)==test_season].copy()
        train=train.dropna(subset=FEATURES); test=test.dropna(subset=FEATURES)
        if len(train)<500 or len(test)<50: continue
        y=((train.FTHG+train.FTAG)>2.5).astype(int) if target=='OU25' else ((train.FTHG>0)&(train.FTAG>0)).astype(int)
        m=make_model(); m.fit(train[FEATURES],y)
        py=m.predict_proba(test[FEATURES])[:,1]
        for (_,r),p_yes in zip(test.iterrows(),py):
            oy=float(r[yes_col]); on=float(r[no_col]); mp_yes,mp_no=no_vig_prob(oy,on)
            cands=[]
            if target=='OU25':
                cands=[('OVER25',p_yes,mp_yes,oy),('UNDER25',1-p_yes,mp_no,on)]
            else:
                cands=[('BTTS_YES',p_yes,mp_yes,oy),('BTTS_NO',1-p_yes,mp_no,on)]
            sel,p,mp,od=max(cands,key=lambda x:x[1]-x[2])
            edge=float(p-mp)
            rows.append({
                'target':target,'season':test_season,'date':r.Date.date().isoformat(),'league':r.LeagueName,
                'home_team':r.HomeTeam,'away_team':r.AwayTeam,'selection':sel,'model_probability':float(p),
                'market_probability':float(mp),'edge':edge,'reference_odds':od,
                'odds_source':'nm2890/football-data average closing odds',
                'profit_units':settle(target,sel,int(r.FTHG),int(r.FTAG),od),
            })
    return pd.DataFrame(rows)


def analyse(bets: pd.DataFrame):
    all_rows=[]; stable=[]
    edges=[0.03,0.05,0.07,0.09,0.12]
    mins=[1.40,1.55,1.70,1.85,2.00]
    maxs=[2.20,2.50,3.00,4.00,99.0]
    for target in bets.target.unique():
      bt=bets[bets.target==target]
      for league in list(SOURCES)+['TUTTI']:
       for sel in sorted(bt.selection.unique())+['TUTTI']:
        for e in edges:
         for omin in mins:
          for omax in maxs:
           q=bt[(bt.edge>=e)&(bt.reference_odds>=omin)&(bt.reference_odds<=omax)]
           if league!='TUTTI': q=q[q.league==league]
           if sel!='TUTTI': q=q[q.selection==sel]
           if len(q)<40: continue
           overall=q.profit_units.mean()
           seasons=[]
           for season,z in q.groupby('season'):
               if len(z)>=20: seasons.append((season,len(z),z.profit_units.mean()))
           pos=sum(r>0 for _,_,r in seasons)
           worst=min([r for _,_,r in seasons],default=np.nan)
           row={'target':target,'league':league,'selection':sel,'min_edge':e,'min_odds':omin,
                'max_odds':None if omax==99 else omax,'bets':len(q),'profit_units':q.profit_units.sum(),
                'roi':overall,'hit_rate':(q.profit_units>0).mean(),'avg_odds':q.reference_odds.mean(),
                'tested_seasons':len(seasons),'positive_seasons':pos,'worst_season_roi':worst}
           all_rows.append(row)
           if len(q)>=120 and len(seasons)>=3 and overall>0 and pos>=max(3,len(seasons)-1) and worst>-0.08:
               stable.append(row)
    return pd.DataFrame(all_rows),pd.DataFrame(stable)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    df=add_features(load_data())
    bets=pd.concat([walk_forward(df,'OU25'),walk_forward(df,'BTTS')],ignore_index=True)
    bets.to_csv(DETAIL,index=False)
    summary,stable=analyse(bets)
    summary.sort_values(['roi','bets'],ascending=[False,False]).to_csv(SUMMARY,index=False)
    stable.sort_values(['roi','bets'],ascending=[False,False]).to_csv(STABLE,index=False)
    print('Top filtri stabili multi-fonte:')
    print(stable.sort_values(['roi','bets'],ascending=[False,False]).head(30).to_string(index=False))

if __name__=='__main__':
    main()
