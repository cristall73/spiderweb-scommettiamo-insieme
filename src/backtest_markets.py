from pathlib import Path
import numpy as np
import pandas as pd

INPUT=Path('data/processed/football_features.csv')
OUT=Path('data/output/backtest_markets.csv')
SUMMARY=Path('data/output/backtest_markets_summary.csv')

# Prima estensione multi-mercato: mercati liquidissimi e verificabili dai dati storici.
# Le strategie usano SOLO informazioni pre-match (medie mobili delle gare precedenti).

def settle(sel,hg,ag,odds):
    tg=hg+ag; btts=hg>0 and ag>0
    win={'OVER25':tg>2.5,'UNDER25':tg<2.5,'BTTS_YES':btts,'BTTS_NO':not btts}[sel]
    return odds-1 if win else -1.0

def fair_odds(p,margin=.05):
    # quota sintetica prudente SOLO per ricerca statistica quando manca la quota storica del mercato.
    # Non va usata come quota reale nelle giocate live.
    return 1/(p*(1+margin)) if 0<p<1 else np.nan

def main():
    df=pd.read_csv(INPUT)
    df=df[(df.home_matches_seen>=10)&(df.away_matches_seen>=10)].copy()
    rows=[]
    for _,r in df.iterrows():
        if pd.isna(r.home_goals) or pd.isna(r.away_goals): continue
        # probabilita semplice, trasparente, esclusivamente pre-match
        p_over=np.clip((r.home_over25_10+r.away_over25_10)/2,.05,.95)
        p_btts=np.clip((r.home_btts_10+r.away_btts_10)/2,.05,.95)
        markets=[('OVER25',p_over),('UNDER25',1-p_over),('BTTS_YES',p_btts),('BTTS_NO',1-p_btts)]
        for sel,p in markets:
            o=fair_odds(p)
            # benchmark: non dichiariamo value con quote sintetiche; misuriamo hit-rate e break-even.
            rows.append({'date':r.date,'season':r.season,'league':r.league,'home_team':r.home_team,'away_team':r.away_team,'market':sel,'model_prob':p,'break_even_odds':1/p,'benchmark_odds':o,'profit_benchmark':settle(sel,int(r.home_goals),int(r.away_goals),o)})
    out=pd.DataFrame(rows); OUT.parent.mkdir(parents=True,exist_ok=True); out.to_csv(OUT,index=False)
    s=[]
    for (league,mkt),z in out.groupby(['league','market']):
        hits=(z.profit_benchmark>0).sum(); n=len(z); p=hits/n if n else np.nan
        s.append({'league':league,'market':mkt,'matches':n,'hit_rate':p,'avg_model_prob':z.model_prob.mean(),'avg_break_even_odds':z.break_even_odds.mean(),'benchmark_roi':z.profit_benchmark.mean()})
    pd.DataFrame(s).sort_values('benchmark_roi',ascending=False).to_csv(SUMMARY,index=False)
    print(pd.DataFrame(s).sort_values('benchmark_roi',ascending=False).to_string(index=False))
if __name__=='__main__': main()
