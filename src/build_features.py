from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path("data/processed/football_matches.csv")
OUTPUT = Path("data/processed/football_features.csv")
WINDOWS = (5, 10)


def mean_or_nan(values):
    return float(np.mean(values)) if values else np.nan


def team_snapshot(history: deque[dict], window: int) -> dict[str, float]:
    rows = list(history)[-window:]
    if not rows:
        return {
            f"pts_{window}": np.nan,
            f"gf_{window}": np.nan,
            f"ga_{window}": np.nan,
            f"btts_{window}": np.nan,
            f"over25_{window}": np.nan,
        }

    return {
        f"pts_{window}": mean_or_nan([r["pts"] for r in rows]),
        f"gf_{window}": mean_or_nan([r["gf"] for r in rows]),
        f"ga_{window}": mean_or_nan([r["ga"] for r in rows]),
        f"btts_{window}": mean_or_nan([r["btts"] for r in rows]),
        f"over25_{window}": mean_or_nan([r["over25"] for r in rows]),
    }


def venue_snapshot(history: deque[dict], window: int) -> dict[str, float]:
    rows = list(history)[-window:]
    if not rows:
        return {
            f"venue_pts_{window}": np.nan,
            f"venue_gf_{window}": np.nan,
            f"venue_ga_{window}": np.nan,
        }
    return {
        f"venue_pts_{window}": mean_or_nan([r["pts"] for r in rows]),
        f"venue_gf_{window}": mean_or_nan([r["gf"] for r in rows]),
        f"venue_ga_{window}": mean_or_nan([r["ga"] for r in rows]),
    }


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values(["date", "league", "home_team", "away_team"]).reset_index(drop=True)

    overall = defaultdict(lambda: deque(maxlen=max(WINDOWS)))
    home_hist = defaultdict(lambda: deque(maxlen=max(WINDOWS)))
    away_hist = defaultdict(lambda: deque(maxlen=max(WINDOWS)))

    feature_rows = []

    for _, row in df.iterrows():
        league = row["league"]
        home = row["home_team"]
        away = row["away_team"]
        hk = (league, home)
        ak = (league, away)

        feats = {}
        for w in WINDOWS:
            hs = team_snapshot(overall[hk], w)
            as_ = team_snapshot(overall[ak], w)
            hv = venue_snapshot(home_hist[hk], w)
            av = venue_snapshot(away_hist[ak], w)

            for key, value in hs.items():
                feats[f"home_{key}"] = value
            for key, value in as_.items():
                feats[f"away_{key}"] = value
            for key, value in hv.items():
                feats[f"home_{key}"] = value
            for key, value in av.items():
                feats[f"away_{key}"] = value

            feats[f"diff_pts_{w}"] = hs[f"pts_{w}"] - as_[f"pts_{w}"]
            feats[f"diff_gf_{w}"] = hs[f"gf_{w}"] - as_[f"gf_{w}"]
            feats[f"diff_ga_{w}"] = hs[f"ga_{w}"] - as_[f"ga_{w}"]

        feats["home_matches_seen"] = len(overall[hk])
        feats["away_matches_seen"] = len(overall[ak])
        feature_rows.append(feats)

        if pd.isna(row.get("home_goals")) or pd.isna(row.get("away_goals")):
            continue

        hg = int(row["home_goals"])
        ag = int(row["away_goals"])
        btts = int(hg > 0 and ag > 0)
        over25 = int(hg + ag > 2)
        if hg > ag:
            hp, ap = 3, 0
        elif hg < ag:
            hp, ap = 0, 3
        else:
            hp = ap = 1

        home_row = {"pts": hp, "gf": hg, "ga": ag, "btts": btts, "over25": over25}
        away_row = {"pts": ap, "gf": ag, "ga": hg, "btts": btts, "over25": over25}
        overall[hk].append(home_row)
        overall[ak].append(away_row)
        home_hist[hk].append(home_row)
        away_hist[ak].append(away_row)

    feature_df = pd.DataFrame(feature_rows)
    return pd.concat([df.reset_index(drop=True), feature_df], axis=1)


def main() -> None:
    if not INPUT.exists():
        raise SystemExit("Dataset non trovato. Esegui prima download_football_data.py e build_dataset.py")

    df = pd.read_csv(INPUT)
    out = add_features(df)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT, index=False)
    print(f"Feature dataset creato: {OUTPUT}")
    print(f"Righe: {len(out)} | Colonne: {len(out.columns)}")


if __name__ == "__main__":
    main()
