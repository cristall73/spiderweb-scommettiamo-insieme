from pathlib import Path
import numpy as np
import pandas as pd

RAW=Path('data/raw')
FEATURES=Path('data/processed/football_features.csv')
OUT=Path('data/output/backtest_ou_real.csv')
SUMMARY=Path('data/output/backtest_ou_real_summary.csv')
STABLE=Path('data/output/backtest_ou_real_stable.csv')
LEAGUES={'E0':'Premier League','I1':'Serie A','D1':'Bundesliga','SP1':'La Liga','F1':'Ligue 1'}
ODDS_PAIRS=[('Avg>2.5','Avg<2.5','Media mercato Football-Data'),('Max>2.5','Max<2.5','Massima quota mercato Football-Data'),('B365>2.5','B365<2.5','Bet365 Football-Data'),('P>2.5','P<2.5','Pinnacle Football-Data')]


def get_pair(df):
    for oc,uc,src in ODDS_PAIRS:
        if oc in df.columns and uc in df.columns and df[[oc,uc]].notna().any().all():
            return oc,uc,src
    return None


def main():
    feat=pd.read_csv(FEATURES,dtype={'season':str})
    feat['date']=pd.to_datetime(feat['date'],errors='coerce').dt.date.astype(str)
    keep=['season','league','date','home_team','away_team','home_over25_10','away_over25_10','home_matches_seen','away_matches_seen','home_goals','away_goals']
    feat=feat[keep].copy()
    rows=[]
    for p in sorted(RAW.glob('*.csv')):
        season,code=p.stem.split('_',1)
        if code not in LEAGUES: continue
        df=pd.read_csv(p)
        pair=get_pair(df)
        if not pair: continue
        oc,uc,src=pair
        if not all(c in df.columns for c in ['Date','HomeTeam','AwayTeam','FTHG','FTAG']): continue
        z=df[['Date','HomeTeam','AwayTeam','FTHG','FTAG',oc,uc]].copy()
        z['season']=season; z['league']=LEAGUES[code]
        z['date']=pd.to_datetime(z['Date'],dayfirst=True,errors='coerce').dt.date.astype(str)
        z=z.rename(columns={'HomeTeam':'home_team','AwayTeam':'away_team',oc:'odds_over',uc:'odds_under'})
        m=z.merge(feat,on=['season','league','date','home_team','away_team'],how='inner',suffixes=('_raw',''))
        for _,r in m.iterrows():
            if r.home_matches_seen<10 or r.away_matches_seen<10: continue
            oo=pd.to_numeric(r.odds_over,errors='coerce'); ou=pd.to_numeric(r.odds_under,errors='coerce')
            if pd.isna(oo) or pd.isna(ou) or oo<=1 or ou<=1: continue
            inv_o,inv_u=1/oo,1/ou; total=inv_o+inv_u
            mp_o,mp_u=inv_o/total,inv_u/total
            p_o=float(np.clip((r.home_over25_10+r.away_over25_10)/2,.03,.97)); p_u=1-p_o
            candidates=[('OVER25',p_o,mp_o,float(oo)),('UNDER25',p_u,mp_u,float(ou))]
            edge,sel,prob,market,odds=max([(p-mp,s,p,mp,o) for s,p,mp,o in candidates],key=lambda x:x[0])
            tg=int(r.home_goals)+int(r.away_goals)
            won=(sel=='OVER25' and tg>2.5) or (sel=='UNDER25' and tg<2.5)
            rows.append({'season':season,'date':r.date,'league':r.league,'home_team':r.home_team,'away_team':r.away_team,'selection':sel,'model_probability':prob,'market_probability':market,'edge':edge,'reference_odds':odds,'odds_source':src,'profit_units':odds-1 if won else -1.0})
    out=pd.DataFrame(rows); OUT.parent.mkdir(parents=True,exist_ok=True); out.to_csv(OUT,index=False)
    summaries=[]; stable=[]
    for edge_min in [0.03,0.05,0.07,0.10,0.12]:
      for league in list(LEAGUES.values())+['TUTTI']:
       for sel in ['OVER25','UNDER25','TUTTI']:
        q=out[out.edge>=edge_min].copy()
        if league!='TUTTI': q=q[q.league==league]
        if sel!='TUTTI': q=q[q.selection==sel]
        if q.empty: continue
        total={'league':league,'selection':sel,'min_edge':edge_min,'season':'TOTALE','bets':len(q),'profit_units':q.profit_units.sum(),'roi':q.profit_units.mean(),'hit_rate':(q.profit_units>0).mean(),'avg_odds':q.reference_odds.mean()}; summaries.append(total)
        per=[]
        for season,zs in q.groupby('season'):
            row={'league':league,'selection':sel,'min_edge':edge_min,'season':season,'bets':len(zs),'profit_units':zs.profit_units.sum(),'roi':zs.profit_units.mean(),'hit_rate':(zs.profit_units>0).mean(),'avg_odds':zs.reference_odds.mean()}; summaries.append(row); per.append(row)
        recent=[x for x in per if x['season'] in ['2324','2425','2526'] and x['bets']>=30]
        if len(recent)>=2:
            pos=sum(x['roi']>0 for x in recent); worst=min(x['roi'] for x in recent)
            if len(q)>=120 and pos>=2 and worst>-0.05 and total['roi']>0:
                stable.append({**total,'validated_seasons':len(recent),'positive_seasons':pos,'worst_recent_roi':worst})
    pd.DataFrame(summaries).to_csv(SUMMARY,index=False)
    pd.DataFrame(stable).sort_values(['roi','bets'],ascending=[False,False]).to_csv(STABLE,index=False)
    print(pd.DataFrame(stable).sort_values(['roi','bets'],ascending=[False,False]).head(30).to_string(index=False))

if __name__=='__main__': main()
