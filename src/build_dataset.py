from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
OUTPUT_FILE = PROCESSED_DIR / "football_matches.csv"

LEAGUE_NAMES = {
    "E0": "Premier League",
    "I1": "Serie A",
    "D1": "Bundesliga",
    "SP1": "La Liga",
    "F1": "Ligue 1",
}


def parse_filename(path: Path) -> tuple[str, str]:
    season, league = path.stem.split("_", maxsplit=1)
    return season, league


def first_complete_triplet(df: pd.DataFrame, candidates: list[tuple[str, str, str, str]]):
    """Sceglie il primo terzetto di quote 1X2 disponibile nel CSV.

    Restituisce home, draw, away e una descrizione trasparente della fonte.
    """
    for home_col, draw_col, away_col, source in candidates:
        if all(col in df.columns for col in (home_col, draw_col, away_col)):
            valid = df[[home_col, draw_col, away_col]].notna().all(axis=1)
            if valid.any():
                return home_col, draw_col, away_col, source
    return None


def add_reference_odds(df: pd.DataFrame) -> pd.DataFrame:
    candidates = [
        ("AvgH", "AvgD", "AvgA", "Media mercato riportata da Football-Data.co.uk"),
        ("MaxH", "MaxD", "MaxA", "Massima quota mercato riportata da Football-Data.co.uk"),
        ("B365H", "B365D", "B365A", "Bet365 riportata da Football-Data.co.uk"),
        ("PSH", "PSD", "PSA", "Pinnacle riportata da Football-Data.co.uk"),
    ]

    selected = first_complete_triplet(df, candidates)
    df = df.copy()

    if selected is None:
        df["odds_home_ref"] = np.nan
        df["odds_draw_ref"] = np.nan
        df["odds_away_ref"] = np.nan
        df["odds_source"] = "Non disponibile"
        return df

    home_col, draw_col, away_col, source = selected
    df["odds_home_ref"] = pd.to_numeric(df[home_col], errors="coerce")
    df["odds_draw_ref"] = pd.to_numeric(df[draw_col], errors="coerce")
    df["odds_away_ref"] = pd.to_numeric(df[away_col], errors="coerce")
    df["odds_source"] = source

    # Probabilita implicite grezze e depurate dal margine del bookmaker/mercato.
    inv = pd.DataFrame(
        {
            "h": 1 / df["odds_home_ref"],
            "d": 1 / df["odds_draw_ref"],
            "a": 1 / df["odds_away_ref"],
        }
    )
    overround = inv.sum(axis=1)
    df["market_margin"] = overround - 1
    df["market_prob_home"] = inv["h"] / overround
    df["market_prob_draw"] = inv["d"] / overround
    df["market_prob_away"] = inv["a"] / overround

    return df


def normalize_one_file(path: Path) -> pd.DataFrame:
    season, league_code = parse_filename(path)
    df = pd.read_csv(path)

    rename = {
        "Date": "date",
        "Time": "time",
        "HomeTeam": "home_team",
        "AwayTeam": "away_team",
        "FTHG": "home_goals",
        "FTAG": "away_goals",
        "FTR": "result_1x2",
        "HTHG": "ht_home_goals",
        "HTAG": "ht_away_goals",
        "HTR": "ht_result_1x2",
        "HS": "home_shots",
        "AS": "away_shots",
        "HST": "home_shots_on_target",
        "AST": "away_shots_on_target",
        "HC": "home_corners",
        "AC": "away_corners",
        "HF": "home_fouls",
        "AF": "away_fouls",
        "HY": "home_yellow",
        "AY": "away_yellow",
        "HR": "home_red",
        "AR": "away_red",
    }

    df = add_reference_odds(df)
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    df["season"] = season
    df["league_code"] = league_code
    df["league"] = LEAGUE_NAMES.get(league_code, league_code)
    df["data_source"] = "Football-Data.co.uk"

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")

    if "home_goals" in df.columns and "away_goals" in df.columns:
        df["total_goals"] = df["home_goals"] + df["away_goals"]
        df["over_2_5"] = (df["total_goals"] > 2.5).astype("Int64")
        df["btts"] = ((df["home_goals"] > 0) & (df["away_goals"] > 0)).astype("Int64")

    keep_first = [
        "season",
        "league_code",
        "league",
        "date",
        "time",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "result_1x2",
        "total_goals",
        "over_2_5",
        "btts",
        "odds_home_ref",
        "odds_draw_ref",
        "odds_away_ref",
        "odds_source",
        "market_margin",
        "market_prob_home",
        "market_prob_draw",
        "market_prob_away",
        "data_source",
    ]

    extra = [c for c in df.columns if c not in keep_first]
    ordered = [c for c in keep_first if c in df.columns] + extra
    return df[ordered]


def main() -> None:
    files = sorted(RAW_DIR.glob("*.csv"))
    if not files:
        raise SystemExit(
            "Nessun CSV trovato in data/raw. Esegui prima: python src/download_football_data.py"
        )

    frames = []
    for path in files:
        try:
            frame = normalize_one_file(path)
            frames.append(frame)
            print(f"OK | {path.name:<15} | {len(frame):>4} righe")
        except Exception as exc:
            print(f"ERRORE | {path.name} | {exc}")

    if not frames:
        raise SystemExit("Nessun file valido da unire.")

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(["date", "league", "home_team"], na_position="last")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)

    print(f"\nDataset creato: {OUTPUT_FILE}")
    print(f"Partite totali: {len(combined)}")
    print(f"Campionati: {combined['league'].nunique()}")
    print(f"Da: {combined['date'].min()} | A: {combined['date'].max()}")


if __name__ == "__main__":
    main()
