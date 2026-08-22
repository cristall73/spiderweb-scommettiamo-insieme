from pathlib import Path
from backtest_multisource_real import load_data

OUT=Path('data/output/live_training.csv')


def main():
    df=load_data().copy()
    keep=['Date','Season','LeagueName','HomeTeam','AwayTeam','FTHG','FTAG',
          'over_2.5_close','under_2.5_close','bts_yes_close','bts_no_close']
    # Manteniamo fino a 6 stagioni/anni per lega: sufficiente per forma e training live,
    # molto più leggero dell'intero archivio grezzo.
    parts=[]
    for _,g in df.groupby('LeagueName'):
        seasons=sorted(g.Season.astype(str).unique())[-6:]
        parts.append(g[g.Season.astype(str).isin(seasons)][keep])
    live=__import__('pandas').concat(parts,ignore_index=True) if parts else df[keep]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    live.to_csv(OUT,index=False)
    print(f'Storico live: {len(live)} partite | {live.LeagueName.nunique()} campionati -> {OUT}')

if __name__=='__main__':
    main()
