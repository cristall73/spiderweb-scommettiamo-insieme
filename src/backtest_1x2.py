from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

INPUT = Path("data/processed/football_features.csv")
OUTPUT = Path("data/output/backtest_1x2.csv")
SUMMARY = Path("data/output/backtest_1x2_summary.csv")

TRAIN_SEASONS = {"2122", "2223", "2324", "2425"}
TEST_SEASON = "2526"
MIN_EDGE = 0.05
MIN_ODDS = 1.55

NUMERIC = [
    "market_prob_home", "market_prob_draw", "market_prob_away", "market_margin",
    "home_pts_5", "away_pts_5", "home_gf_5", "away_gf_5", "home_ga_5", "away_ga_5",
    "home_btts_5", "away_btts_5", "home_over25_5", "away_over25_5",
    "home_venue_pts_5", "away_venue_pts_5", "home_venue_gf_5", "away_venue_gf_5",
    "home_venue_ga_5", "away_venue_ga_5", "diff_pts_5", "diff_gf_5", "diff_ga_5",
    "home_pts_10", "away_pts_10", "diff_pts_10",
]
CATEGORICAL = ["league"]


def build_model() -> Pipeline:
    numeric_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    prep = ColumnTransformer([
        ("num", numeric_pipe, NUMERIC),
        ("cat", categorical_pipe, CATEGORICAL),
    ])
    return Pipeline([
        ("prep", prep),
        ("model", LogisticRegression(max_iter=2000, multi_class="auto")),
    ])


def realized_profit(result: str, selection: str, odds: float) -> float:
    return odds - 1 if result == selection else -1.0


def main() -> None:
    if not INPUT.exists():
        raise SystemExit("Feature dataset non trovato. Esegui prima build_features.py")

    df = pd.read_csv(INPUT, dtype={"season": str})
    df = df[df["result_1x2"].isin(["H", "D", "A"])].copy()
    df = df[(df["home_matches_seen"] >= 5) & (df["away_matches_seen"] >= 5)].copy()

    train = df[df["season"].isin(TRAIN_SEASONS)].copy()
    test = df[df["season"] == TEST_SEASON].copy()
    if train.empty or test.empty:
        raise SystemExit("Training o test vuoto: controlla le stagioni disponibili.")

    model = build_model()
    model.fit(train[NUMERIC + CATEGORICAL], train["result_1x2"])

    probs = model.predict_proba(test[NUMERIC + CATEGORICAL])
    classes = list(model.named_steps["model"].classes_)
    for i, cls in enumerate(classes):
        test[f"model_prob_{cls}"] = probs[:, i]

    pred = model.predict(test[NUMERIC + CATEGORICAL])
    print(f"Accuracy test {TEST_SEASON}: {accuracy_score(test['result_1x2'], pred):.3f}")
    print(f"Log loss test {TEST_SEASON}: {log_loss(test['result_1x2'], probs, labels=classes):.3f}")

    mapping = {
        "H": ("odds_home_ref", "market_prob_home"),
        "D": ("odds_draw_ref", "market_prob_draw"),
        "A": ("odds_away_ref", "market_prob_away"),
    }

    bets = []
    for idx, row in test.iterrows():
        candidates = []
        for sel, (odds_col, market_col) in mapping.items():
            model_prob = row.get(f"model_prob_{sel}")
            odds = row.get(odds_col)
            market_prob = row.get(market_col)
            if pd.isna(model_prob) or pd.isna(odds) or pd.isna(market_prob) or odds <= 1:
                continue
            edge = float(model_prob - market_prob)
            fair_odds = 1 / float(model_prob) if model_prob > 0 else np.nan
            candidates.append((edge, sel, float(model_prob), float(market_prob), float(odds), fair_odds))

        if not candidates:
            continue
        edge, sel, model_prob, market_prob, odds, fair_odds = max(candidates, key=lambda x: x[0])
        if edge < MIN_EDGE or odds < MIN_ODDS:
            continue

        bets.append({
            "date": row["date"],
            "league": row["league"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "result": row["result_1x2"],
            "selection": sel,
            "model_probability": model_prob,
            "market_probability": market_prob,
            "edge": edge,
            "fair_odds": fair_odds,
            "reference_odds": odds,
            "odds_source": row.get("odds_source"),
            "profit_units": realized_profit(row["result_1x2"], sel, odds),
        })

    bets_df = pd.DataFrame(bets)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    bets_df.to_csv(OUTPUT, index=False)

    if bets_df.empty:
        print("Nessuna selezione supera i filtri iniziali.")
        return

    summary = (
        bets_df.groupby("league")
        .agg(
            bets=("selection", "size"),
            wins=("profit_units", lambda s: int((s > 0).sum())),
            profit_units=("profit_units", "sum"),
            avg_edge=("edge", "mean"),
            avg_odds=("reference_odds", "mean"),
        )
        .reset_index()
    )
    summary["hit_rate"] = summary["wins"] / summary["bets"]
    summary["roi"] = summary["profit_units"] / summary["bets"]

    overall = pd.DataFrame([{
        "league": "TOTALE",
        "bets": len(bets_df),
        "wins": int((bets_df["profit_units"] > 0).sum()),
        "profit_units": bets_df["profit_units"].sum(),
        "avg_edge": bets_df["edge"].mean(),
        "avg_odds": bets_df["reference_odds"].mean(),
        "hit_rate": (bets_df["profit_units"] > 0).mean(),
        "roi": bets_df["profit_units"].sum() / len(bets_df),
    }])
    summary = pd.concat([summary, overall], ignore_index=True)
    summary.to_csv(SUMMARY, index=False)
    print(summary.to_string(index=False))
    print(f"\nDettaglio: {OUTPUT}\nRiepilogo: {SUMMARY}")


if __name__ == "__main__":
    main()
