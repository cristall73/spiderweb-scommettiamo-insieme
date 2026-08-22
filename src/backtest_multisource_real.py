from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import re

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from league_catalog import EUROPE_LEAGUES, WORLD_LEAGUES

RAW = Path('data/raw')
OUT = Path('data/output')
DETAIL = OUT / 'backtest_multisource_real.csv'
SUMMARY = OUT / 'backtest_multisource_summary.csv'
STABLE = OUT / 'backtest_multisource_stable.csv'

FEATURES = [
    'home_pts5','away_pts5','home_gf5','away_gf5','home_ga5','away_ga5',
    'home_over5','away_over5','home_btts5','away_btts5',
    'home_pts10','away_pts10','home_gf10','away_gf10','home_ga10','away_ga10',
    'home_over10','away_over10','home_btts10','away_btts10',
]


def first_col(df, names):
    lookup={str(c).strip().lower():c for c in df.columns}
    for n in names:
        if n.lower() in lookup:
            return lookup[n.lower()]
    return None


def num_series(df, names):
    c=first_col(df,names)
    if c is None:
        return pd.Series(np.nan,index=df.index,dtype=float)
    return pd.to_numeric(df[c],errors='coerce')


def text_series(df, names):
    c=first_col(df,names)
    if c is None:
        return pd.Series('',index=df.index,dtype=object)
    return df[c].astype(str).str.strip()


def normalise_file(path: Path, league_name: str, season_hint: str|None=None) -> pd.DataFrame:
    try:
        raw=pd.read_csv(path,encoding_errors='ignore')
    except Exception:
        return pd.DataFrame()
    if raw.empty:
        return pd.DataFrame()

    date_col=first_col(raw,['Date','date'])
    home_col=first_col(raw,['HomeTeam','Home','home_team','home'])
    away_col=first_col(raw,['AwayTeam','Away','away_team','away'])
    hg_col=first_col(raw,['FTHG','HG','HomeGoals','home_goals'])
    ag_col=first_col(raw,['FTAG','AG','AwayGoals','away_goals'])
    if not all([date_col,home_col,away_col,hg_col,ag_col]):
        return pd.DataFrame()

    # Football-Data usa spesso gg/mm/aa; dayfirst gestisce correttamente i file europei.
    dates=pd.to_datetime(raw[date_col],errors='coerce',dayfirst=True)
    out=pd.DataFrame({
        'Date':dates,
        'HomeTeam':raw[home_col].astype(str).str.strip(),
        'AwayTeam':raw[away_col].astype(str).str.strip(),
        'FTHG':pd.to_numeric(raw[hg_col],errors='coerce'),
        'FTAG':pd.to_numeric(raw[ag_col],errors='coerce'),
    })

    season_col=first_col(raw,['Season','season'])
    if season_col:
        out['Season']=raw[season_col].astype(str)
    elif season_hint:
        out['Season']=season_hint
    else:
        # Per leghe a stagione solare (Brasile, Giappone, MLS ecc.) l'anno è una stagione naturale.
        out['Season']=dates.dt.year.astype('Int64').astype(str)

    out['LeagueName']=league_name

    # Quote closing medie preferite; fallback alle medie/pre-closing o a un bookmaker singolo.
    out['over_2.5_close']=num_series(raw,[
        'AvgC>2.5','Avg>2.5','B365C>2.5','B365>2.5','MaxC>2.5','Max>2.5','P>2.5'
    ])
    out['under_2.5_close']=num_series(raw,[
        'AvgC<2.5','Avg<2.5','B365C<2.5','B365<2.5','MaxC<2.5','Max<2.5','P<2.5'
    ])

    # Alcuni archivi hanno anche Goal/No Goal; se non esiste resta NaN e quel mercato viene ignorato.
    out['bts_yes_close']=num_series(raw,[
        'AvgCGG','AvgGG','B365CGG','B365GG','MaxGG','GG','BTSY','BTTSY','BothTeamsToScoreYes'
    ])
    out['bts_no_close']=num_series(raw,[
        'AvgCNG','AvgNG','B365CNG','B365NG','MaxNG','NG','BTSN','BTTSN','BothTeamsToScoreNo'
    ])

    out=out.dropna(subset=['Date','FTHG','FTAG'])
    out=out[(out.HomeTeam!='')&(out.AwayTeam!='')]
    return out


def load_data() -> pd.DataFrame:
    frames=[]

    for p in sorted(RAW.glob('eu_*_*.csv')):
        m=re.match(r'eu_([^_]+)_([^_]+)\.csv$',p.name)
        if not m:
            continue
        season,code=m.groups()
        meta=EUROPE_LEAGUES.get(code)
        if not meta:
            continue
        x=normalise_file(p,meta['name'],season)
        if not x.empty:
            frames.append(x)

    for code,meta in WORLD_LEAGUES.items():
        p=RAW/f'world_{code}.csv'
        if p.exists():
            x=normalise_file(p,meta['name'])
            if not x.empty:
                frames.append(x)

    # Fallback utile quando lo script viene eseguito senza download preliminare.
    if not frames:
        raise RuntimeError('Nessun archivio storico valido in data/raw: eseguire download_football_data.py')

    df=pd.concat(frames,ignore_index=True)
    df=df.drop_duplicates(subset=['LeagueName','Date','HomeTeam','AwayTeam'],keep='last')
    df=df.sort_values(['Date','LeagueName','HomeTeam','AwayTeam']).reset_index(drop=True)
    print(f"Storico normalizzato: {len(df)} partite | {df.LeagueName.nunique()} campionati")
    return df


def snap(hist: deque, n: int):
    x=list(hist)[-n:]
    if len(x)<5:
        return [np.nan]*5
    return [
        np.mean([r['pts'] for r in x]),np.mean([r['gf'] for r in x]),
        np.mean([r['ga'] for r in x]),np.mean([r['over'] for r in x]),
        np.mean([r['btts'] for r in x]),
    ]


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    hist=defaultdict(lambda:deque(maxlen=10)); rows=[]
    for _,r in df.iterrows():
        hk=(r.LeagueName,r.HomeTeam); ak=(r.LeagueName,r.AwayTeam)
        h5=snap(hist[hk],5); a5=snap(hist[ak],5); h10=snap(hist[hk],10); a10=snap(hist[ak],10)
        vals=h5[:3]+a5[:3]+[h5[3],a5[3],h5[4],a5[4]]+h10[:3]+a10[:3]+[h10[3],a10[3],h10[4],a10[4]]
        rows.append(dict(zip(FEATURES,vals)))
        hg=int(r.FTHG); ag=int(r.FTAG)
        hp,ap=(3,0) if hg>ag else ((0,3) if hg<ag else (1,1))
        over=int(hg+ag>2.5); btts=int(hg>0 and ag>0)
        hist[hk].append({'pts':hp,'gf':hg,'ga':ag,'over':over,'btts':btts})
        hist[ak].append({'pts':ap,'gf':ag,'ga':hg,'over':over,'btts':btts})
    return pd.concat([df.reset_index(drop=True),pd.DataFrame(rows)],axis=1)


def make_model():
    return Pipeline([
        ('impute',SimpleImputer(strategy='median')),
        ('scale',StandardScaler()),
        ('model',LogisticRegression(max_iter=2000,class_weight='balanced')),
    ])


def no_vig_prob(o1,o2):
    a,b=1/o1,1/o2; s=a+b
    return a/s,b/s


def settle(target,sel,hg,ag,odds):
    if target=='OU25':
        won=(hg+ag>2.5) if sel=='OVER25' else (hg+ag<2.5)
    else:
        won=(hg>0 and ag>0) if sel=='BTTS_YES' else not (hg>0 and ag>0)
    return odds-1 if won else -1.0


def walk_forward(df,target):
    yes_col,no_col=('over_2.5_close','under_2.5_close') if target=='OU25' else ('bts_yes_close','bts_no_close')
    d=df.copy()
    d[yes_col]=pd.to_numeric(d[yes_col],errors='coerce'); d[no_col]=pd.to_numeric(d[no_col],errors='coerce')
    d=d.dropna(subset=[yes_col,no_col])
    d=d[(d[yes_col]>1)&(d[no_col]>1)]
    rows=[]

    # Walk-forward separato per campionato: evita che una lega venga validata usando il futuro di un'altra.
    for league,ld in d.groupby('LeagueName'):
        seasons=sorted(ld.Season.astype(str).unique())
        if len(seasons)<4:
            continue
        for i in range(3,len(seasons)):
            test_season=seasons[i]
            train=ld[ld.Season.astype(str).isin(seasons[:i])].copy()
            test=ld[ld.Season.astype(str)==test_season].copy()
            train=train.dropna(subset=FEATURES); test=test.dropna(subset=FEATURES)
            if len(train)<180 or len(test)<25:
                continue
            y=((train.FTHG+train.FTAG)>2.5).astype(int) if target=='OU25' else ((train.FTHG>0)&(train.FTAG>0)).astype(int)
            if y.nunique()<2:
                continue
            m=make_model(); m.fit(train[FEATURES],y)
            py=m.predict_proba(test[FEATURES])[:,1]
            for (_,r),p_yes in zip(test.iterrows(),py):
                oy=float(r[yes_col]); on=float(r[no_col]); mp_yes,mp_no=no_vig_prob(oy,on)
                cands=[('OVER25',p_yes,mp_yes,oy),('UNDER25',1-p_yes,mp_no,on)] if target=='OU25' else [
                    ('BTTS_YES',p_yes,mp_yes,oy),('BTTS_NO',1-p_yes,mp_no,on)]
                sel,p,mp,od=max(cands,key=lambda x:x[1]-x[2])
                rows.append({
                    'target':target,'season':test_season,'date':r.Date.date().isoformat(),'league':league,
                    'home_team':r.HomeTeam,'away_team':r.AwayTeam,'selection':sel,
                    'model_probability':float(p),'market_probability':float(mp),'edge':float(p-mp),
                    'reference_odds':od,'odds_source':'Football-Data closing/market odds',
                    'profit_units':settle(target,sel,int(r.FTHG),int(r.FTAG),od),
                })
    return pd.DataFrame(rows)


def analyse(bets: pd.DataFrame):
    if bets.empty:
        return pd.DataFrame(),pd.DataFrame()
    all_rows=[]; stable=[]
    edges=[0.03,0.05,0.07,0.09,0.12]
    mins=[1.35,1.50,1.65,1.80,2.00]
    maxs=[2.00,2.20,2.50,3.00,4.00,99.0]
    leagues=sorted(bets.league.unique())
    for target in bets.target.unique():
      bt=bets[bets.target==target]
      for league in leagues+['TUTTI']:
       for sel in sorted(bt.selection.unique())+['TUTTI']:
        for e in edges:
         for omin in mins:
          for omax in maxs:
           q=bt[(bt.edge>=e)&(bt.reference_odds>=omin)&(bt.reference_odds<=omax)]
           if league!='TUTTI': q=q[q.league==league]
           if sel!='TUTTI': q=q[q.selection==sel]
           if len(q)<40: continue
           overall=q.profit_units.mean(); seasons=[]
           for season,z in q.groupby('season'):
               if len(z)>=15: seasons.append((season,len(z),z.profit_units.mean()))
           pos=sum(r>0 for _,_,r in seasons)
           worst=min([r for _,_,r in seasons],default=np.nan)
           row={'target':target,'league':league,'selection':sel,'min_edge':e,'min_odds':omin,
                'max_odds':None if omax==99 else omax,'bets':len(q),'profit_units':q.profit_units.sum(),
                'roi':overall,'hit_rate':(q.profit_units>0).mean(),'avg_odds':q.reference_odds.mean(),
                'tested_seasons':len(seasons),'positive_seasons':pos,'worst_season_roi':worst}
           all_rows.append(row)
           # Regola prudente: campione ampio, almeno 3 finestre OOS, quasi tutte positive.
           if len(q)>=120 and len(seasons)>=3 and overall>0 and pos>=max(3,len(seasons)-1) and worst>-0.08:
               stable.append(row)
    return pd.DataFrame(all_rows),pd.DataFrame(stable)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    df=add_features(load_data())
    pieces=[]
    for target in ('OU25','BTTS'):
        x=walk_forward(df,target)
        if not x.empty: pieces.append(x)
    bets=pd.concat(pieces,ignore_index=True) if pieces else pd.DataFrame()
    bets.to_csv(DETAIL,index=False)
    summary,stable=analyse(bets)
    if not summary.empty:
        summary.sort_values(['roi','bets'],ascending=[False,False]).to_csv(SUMMARY,index=False)
    else:
        summary.to_csv(SUMMARY,index=False)
    if not stable.empty:
        stable.sort_values(['roi','bets'],ascending=[False,False]).to_csv(STABLE,index=False)
        print('Top filtri stabili globali:')
        print(stable.sort_values(['roi','bets'],ascending=[False,False]).head(40).to_string(index=False))
    else:
        stable.to_csv(STABLE,index=False)
        print('Nessun filtro ha ancora superato i criteri di robustezza.')
    print(f'Bets OOS analizzate: {len(bets)} | leghe: {bets.league.nunique() if not bets.empty else 0}')


if __name__=='__main__':
    main()
