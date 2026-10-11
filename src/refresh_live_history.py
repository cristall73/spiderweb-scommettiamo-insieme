"""Refresh current-season results from Football-Data, without API credits."""
import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
import pandas as pd
import requests
from league_catalog import EUROPE_LEAGUES, WORLD_LEAGUES, EUROPE_URL, WORLD_URL
from backtest_multisource_real import normalise_file

MARKER=Path('data/output/history_refresh.json')
PATH=Path('data/output/live_training.csv')


def current_season(now):
    year=now.year if now.month>=7 else now.year-1
    return f'{year%100:02d}{(year+1)%100:02d}'


def refresh(historical, events, now):
    if MARKER.exists():
        try:
            marker=json.loads(MARKER.read_text())
            if marker.get('date')==now.date().isoformat():return historical,marker
        except (ValueError,OSError):pass
    wanted={e.get('canonical_league') for e in events}
    season=current_season(now)
    frames=[];failed=[]
    session=requests.Session()
    for table,template in [(EUROPE_LEAGUES,EUROPE_URL),(WORLD_LEAGUES,WORLD_URL)]:
        for code,meta in table.items():
            if meta['name'] not in wanted:continue
            try:
                response=session.get(template.format(season=season,code=code),timeout=20,
                                     headers={'User-Agent':'SpiderWeb/2.0','Accept':'text/csv'})
                response.raise_for_status()
                if '<html' in response.text[:300].lower():raise ValueError('not CSV')
                frame=normalise_file(StringIO(response.text),meta['name'],season if table is EUROPE_LEAGUES else None)
                if frame.empty:raise ValueError('empty CSV')
                frame=frame[pd.to_datetime(frame.Date).dt.date<now.date()]
                frames.append(frame)
            except (requests.RequestException,ValueError,KeyError):failed.append(meta['name'])
    combined=pd.concat([historical,*frames],ignore_index=True,sort=False)
    combined['Date']=pd.to_datetime(combined.Date,errors='coerce')
    combined=combined.dropna(subset=['Date','FTHG','FTAG']).sort_values('Date')
    combined=combined.drop_duplicates(['Date','LeagueName','HomeTeam','AwayTeam'],keep='last')
    keep=['Date','Season','LeagueName','HomeTeam','AwayTeam','FTHG','FTAG',
          'over_2.5_close','under_2.5_close','bts_yes_close','bts_no_close']
    combined=combined.reindex(columns=keep)
    marker={'date':now.date().isoformat(),'season':season,'refreshed_leagues':len(frames),
            'failed_leagues':failed,'latest_result':combined.Date.max().date().isoformat(),
            'source':'Football-Data current-season results'}
    PATH.parent.mkdir(parents=True,exist_ok=True)
    combined.to_csv(PATH,index=False)
    MARKER.write_text(json.dumps(marker,ensure_ascii=False,indent=2)+'\n')
    return combined,marker
