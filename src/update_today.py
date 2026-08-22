from __future__ import annotations

import itertools
import json
import math
import re
import unicodedata
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from backtest_multisource_real import FEATURES, add_features, load_data, make_model, no_vig_prob

OUT = Path('data/output/today.json')
STABLE_FILE = Path('data/output/backtest_multisource_stable.csv')
ROME = ZoneInfo('Europe/Rome')
BASES = ['https://api.sofascore.com/api/v1', 'https://www.sofascore.com/api/v1']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.sofascore.com/'
}
MAX_EVENTS_WITH_ODDS = 140
BAD_WORDS = ('women','femmin','u17','u18','u19','u20','u21','u23','youth','junior','reserve','reserves')

MIN_LIVE_SYSTEM_ROI = 0.03
MIN_LIVE_SYSTEM_BETS = 120


def get_json(path: str, timeout: int = 12):
    last = None
    for base in BASES:
        try:
            r = requests.get(base + path, headers=HEADERS, timeout=timeout)
            if r.ok:
                return r.json()
            last = f'{r.status_code} {r.text[:120]}'
        except Exception as exc:
            last = str(exc)
    # La fonte live può bloccare gli IP dei runner GitHub con 403.
    # Non deve far crollare l'intera pipeline: il chiamante può provare
    # le fonti/fallback successive e produrre comunque diagnostica utile.
    print(f'WARN live source {path}: {last or "richiesta fallita"}')
    return {}


def frac_to_decimal(v):
    if v is None:
        return None
    if isinstance(v, (int,float)):
        x = float(v)
        return x if x > 1 else None
    s = str(v).strip()
    try:
        if '/' in s:
            a,b = s.split('/',1)
            return 1 + float(a)/float(b)
        x = float(s)
        return x if x > 1 else None
    except Exception:
        return None


def choice_odds(c):
    for k in ('decimalValue','decimalOdds','value'):
        x = frac_to_decimal(c.get(k))
        if x:
            return x
    return frac_to_decimal(c.get('fractionalValue'))


def fair_probs(choices):
    vals=[]
    for c in choices:
        o=choice_odds(c)
        if o:
            vals.append((c,o))
    inv=sum(1/o for _,o in vals)
    return [(c,o,(1/o)/inv) for c,o in vals] if inv else []

# NOTE: resto del modulo mantenuto nel repository precedente.