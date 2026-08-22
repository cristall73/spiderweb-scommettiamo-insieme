from __future__ import annotations

# Catalogo centrale delle fonti storiche Football-Data.
# 22 divisioni europee con file stagionali + 16 leghe extra-europee
# con archivio CSV dedicato.

EUROPE_LEAGUES = {
    'E0':  {'name':'England Premier League','country':'England','aliases':['premier league']},
    'E1':  {'name':'England Championship','country':'England','aliases':['championship']},
    'E2':  {'name':'England League One','country':'England','aliases':['league one']},
    'E3':  {'name':'England League Two','country':'England','aliases':['league two']},
    'EC':  {'name':'England National League','country':'England','aliases':['national league','conference']},
    'SC0': {'name':'Scotland Premiership','country':'Scotland','aliases':['premiership']},
    'SC1': {'name':'Scotland Championship','country':'Scotland','aliases':['championship']},
    'SC2': {'name':'Scotland League One','country':'Scotland','aliases':['league one']},
    'SC3': {'name':'Scotland League Two','country':'Scotland','aliases':['league two']},
    'D1':  {'name':'Germany Bundesliga','country':'Germany','aliases':['bundesliga']},
    'D2':  {'name':'Germany 2. Bundesliga','country':'Germany','aliases':['2. bundesliga','2 bundesliga']},
    'I1':  {'name':'Italy Serie A','country':'Italy','aliases':['serie a']},
    'I2':  {'name':'Italy Serie B','country':'Italy','aliases':['serie b']},
    'SP1': {'name':'Spain La Liga','country':'Spain','aliases':['laliga','la liga','primera division']},
    'SP2': {'name':'Spain Segunda','country':'Spain','aliases':['laliga 2','la liga 2','segunda division','segunda']},
    'F1':  {'name':'France Ligue 1','country':'France','aliases':['ligue 1']},
    'F2':  {'name':'France Ligue 2','country':'France','aliases':['ligue 2']},
    'N1':  {'name':'Netherlands Eredivisie','country':'Netherlands','aliases':['eredivisie']},
    'B1':  {'name':'Belgium First Division A','country':'Belgium','aliases':['first division a','jupiler pro league','pro league']},
    'P1':  {'name':'Portugal Primeira Liga','country':'Portugal','aliases':['primeira liga','liga portugal']},
    'T1':  {'name':'Turkey Super Lig','country':'Turkey','aliases':['super lig','super league']},
    'G1':  {'name':'Greece Super League','country':'Greece','aliases':['super league']},
}

WORLD_LEAGUES = {
    'ARG': {'name':'Argentina Primera Division','country':'Argentina','aliases':['liga profesional','primera division']},
    'AUT': {'name':'Austria Bundesliga','country':'Austria','aliases':['bundesliga']},
    'BRA': {'name':'Brazil Serie A','country':'Brazil','aliases':['brasileirao serie a','serie a']},
    'CHN': {'name':'China Super League','country':'China','aliases':['chinese super league','super league']},
    'DNK': {'name':'Denmark Superliga','country':'Denmark','aliases':['superliga']},
    'FIN': {'name':'Finland Veikkausliiga','country':'Finland','aliases':['veikkausliiga']},
    'IRL': {'name':'Ireland Premier Division','country':'Ireland','aliases':['premier division']},
    'JPN': {'name':'Japan J1 League','country':'Japan','aliases':['j1 league','j league']},
    'MEX': {'name':'Mexico Liga MX','country':'Mexico','aliases':['liga mx']},
    'NOR': {'name':'Norway Eliteserien','country':'Norway','aliases':['eliteserien']},
    'POL': {'name':'Poland Ekstraklasa','country':'Poland','aliases':['ekstraklasa']},
    'ROU': {'name':'Romania Liga I','country':'Romania','aliases':['liga i','liga 1']},
    'RUS': {'name':'Russia Premier League','country':'Russia','aliases':['premier league']},
    'SWE': {'name':'Sweden Allsvenskan','country':'Sweden','aliases':['allsvenskan']},
    'SWZ': {'name':'Switzerland Super League','country':'Switzerland','aliases':['super league']},
    'USA': {'name':'USA MLS','country':'USA','aliases':['major league soccer','mls']},
}

EUROPE_SEASONS = ['2021','2122','2223','2324','2425','2526']
EUROPE_URL = 'https://www.football-data.co.uk/mmz4281/{season}/{code}.csv'
WORLD_URL = 'https://www.football-data.co.uk/new/{code}.csv'

ALL_LEAGUES = {**EUROPE_LEAGUES, **WORLD_LEAGUES}
