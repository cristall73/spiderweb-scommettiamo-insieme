from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from backtest_1x2 import build_model, NUMERIC, CATEGORICAL
from build_dataset import add_reference_odds, normalize_one_file, LEAGUE_NAMES
from build_features import add_features

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
CURRENT_SEASON = "2627"
LEAGUES = {"E0": "Premier League", "I1": "Serie A", "D1": "Bundesliga", "SP1": "La Liga", "F1": "Ligue 1"}
HISTORICAL = Path("data/processed/football_matches.csv")
OUT = Path("data/output/today.json")
TMP = Path("data/current")
ROME = ZoneInfo("Europe/Rome")


def download(url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=40, headers={"User-Agent": "Mozilla/5.0 SpiderWeb/1.0"})
    r.raise_for_status()
    path.write_bytes(r.content)
    return path


def current_results() -> pd.DataFrame:
    frames = []
    for code in LEAGUES:
        try:
            path = TMP / f"{CURRENT_SEASON}_{code}.csv"
            download(BASE_URL.format(season=CURRENT_SEASON, league=code), path)
            frames.append(normalize_one_file(path))
        except Exception as exc:
            print(f"Risultati {code} non disponibili: {exc}")
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def fixture_rows() -> pd.DataFrame:
    path = download(FIXTURES_URL, TMP / "fixtures.csv")
    raw = pd.read_csv(path)
    if "Div" not in raw.columns:
        raise RuntimeError("Il file fixtures.csv non contiene la colonna Div")
    raw = raw[raw["Div"].isin(LEAGUES)].copy()
    raw = add_reference_odds(raw)
    raw = raw.rename(columns={"Date":"date","Time":"time","HomeTeam":"home_team","AwayTeam":"away_team"})
    raw["date"] = pd.to_datetime(raw["date"], dayfirst=True, errors="coerce")
    raw["league_code"] = raw["Div"]
    raw["league"] = raw["Div"].map(LEAGUES)
    raw["season"] = CURRENT_SEASON
    raw["data_source"] = "Football-Data.co.uk fixtures"
    for c in ["home_goals","away_goals","result_1x2"]:
        raw[c] = np.nan
    return raw


def classify_signal(row: pd.Series, selection: str, edge: float, odds: float) -> tuple[str, str]:
    league = row["league"]
    if league == "Bundesliga" and selection == "A" and edge >= 0.12 and 2.50 <= odds <= 5.00:
        return "VALIDATA_FORTE", "Bundesliga trasferta · edge ≥12% · quota 2.50–5.00"
    if league == "Bundesliga" and selection == "A" and edge >= 0.12 and 2.00 <= odds <= 5.00:
        return "VALIDATA", "Bundesliga trasferta · edge ≥12% · quota 2.00–5.00"
    if league == "Serie A" and selection == "A" and edge >= 0.09 and 1.80 <= odds <= 2.80:
        return "IN_TEST", "Serie A trasferta · edge ≥9% · quota 1.80–2.80"
    return "NO_BET", "Nessun filtro validato superato"


def main() -> None:
    now = datetime.now(ROME)
    today = pd.Timestamp(now.date())

    if not HISTORICAL.exists():
        raise SystemExit("Dataset storico assente: eseguire prima download_football_data.py e build_dataset.py")

    hist = pd.read_csv(HISTORICAL, dtype={"season": str})
    hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
    cur = current_results()
    fixtures = fixture_rows()

    completed = pd.concat([hist, cur], ignore_index=True, sort=False)
    completed = completed.drop_duplicates(subset=["league","date","home_team","away_team"], keep="last")

    today_fixtures = fixtures[fixtures["date"].dt.normalize() == today].copy()
    combined = pd.concat([completed, today_fixtures], ignore_index=True, sort=False)
    combined = combined.sort_values(["date","league","home_team","away_team"], na_position="last")
    featured = add_features(combined)

    train = featured[featured["result_1x2"].isin(["H","D","A"])].copy()
    train = train[(train["home_matches_seen"] >= 5) & (train["away_matches_seen"] >= 5)].copy()
    model = build_model()
    model.fit(train[NUMERIC + CATEGORICAL], train["result_1x2"])
    classes = list(model.named_steps["model"].classes_)

    target = featured[(featured["date"].dt.normalize() == today) & featured["result_1x2"].isna()].copy()
    matches = []
    if not target.empty:
        probs = model.predict_proba(target[NUMERIC + CATEGORICAL])
        for i, cls in enumerate(classes):
            target[f"model_prob_{cls}"] = probs[:, i]

        mapping = {
            "H": ("odds_home_ref", "market_prob_home", "1"),
            "D": ("odds_draw_ref", "market_prob_draw", "X"),
            "A": ("odds_away_ref", "market_prob_away", "2"),
        }
        for _, row in target.iterrows():
            candidates = []
            for sel, (odds_col, market_col, label) in mapping.items():
                p = row.get(f"model_prob_{sel}")
                odds = row.get(odds_col)
                mp = row.get(market_col)
                if pd.isna(p) or pd.isna(odds) or pd.isna(mp) or float(odds) <= 1:
                    continue
                candidates.append((float(p - mp), sel, label, float(p), float(mp), float(odds)))
            if candidates:
                edge, sel, label, p, mp, odds = max(candidates, key=lambda x: x[0])
                status, rule = classify_signal(row, sel, edge, odds)
            else:
                edge, sel, label, p, mp, odds = 0.0, "", "—", np.nan, np.nan, np.nan
                status, rule = "DATI_INSUFFICIENTI", "Quote non disponibili"

            matches.append({
                "league": row.get("league"),
                "time": str(row.get("time") or ""),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "selection": label,
                "model_probability": None if pd.isna(p) else round(p, 4),
                "market_probability": None if pd.isna(mp) else round(mp, 4),
                "edge": None if pd.isna(edge) else round(edge, 4),
                "odds": None if pd.isna(odds) else round(odds, 2),
                "status": status,
                "rule": rule,
                "odds_source": row.get("odds_source", "Non disponibile"),
            })

    rank = {"VALIDATA_FORTE":0,"VALIDATA":1,"IN_TEST":2,"NO_BET":3,"DATI_INSUFFICIENTI":4}
    matches.sort(key=lambda x: (rank.get(x["status"], 9), x.get("time") or ""))
    signals = [m for m in matches if m["status"] in {"VALIDATA_FORTE","VALIDATA","IN_TEST"}]

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "source": "Football-Data.co.uk fixtures + quote mercato",
        "fixtures_count": len(matches),
        "signals_count": len(signals),
        "signals": signals,
        "matches": matches,
        "note": "Le quote di Football-Data.co.uk vengono raccolte periodicamente e possono differire da Sisal o da altri bookmaker al momento della giocata."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"date": payload["date"], "fixtures": len(matches), "signals": len(signals)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
