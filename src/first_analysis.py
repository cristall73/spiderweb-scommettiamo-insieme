from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_FILE = Path("data/processed/football_matches.csv")
OUTPUT_DIR = Path("data/output")
SUMMARY_FILE = OUTPUT_DIR / "first_summary.csv"


def pct(series: pd.Series) -> float:
    clean = series.dropna()
    return round(float(clean.mean() * 100), 2) if len(clean) else float("nan")


def main() -> None:
    if not INPUT_FILE.exists():
        raise SystemExit(
            "Dataset non trovato. Esegui prima: python src/build_dataset.py"
        )

    df = pd.read_csv(INPUT_FILE, parse_dates=["date"])

    rows = []
    for (season, league), group in df.groupby(["season", "league"], dropna=False):
        valid_results = group["result_1x2"].dropna()
        rows.append(
            {
                "season": season,
                "league": league,
                "matches": len(group),
                "home_win_pct": round((valid_results == "H").mean() * 100, 2),
                "draw_pct": round((valid_results == "D").mean() * 100, 2),
                "away_win_pct": round((valid_results == "A").mean() * 100, 2),
                "over_2_5_pct": pct(group["over_2_5"]),
                "btts_pct": pct(group["btts"]),
                "avg_total_goals": round(group["total_goals"].mean(), 3),
                "avg_market_margin_pct": round(group["market_margin"].mean() * 100, 2),
                "odds_coverage_pct": round(group["odds_home_ref"].notna().mean() * 100, 2),
            }
        )

    summary = pd.DataFrame(rows).sort_values(["season", "league"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_FILE, index=False)

    print("\n=== PRIMA ANALISI DESCRITTIVA ===\n")
    print(summary.to_string(index=False))
    print(f"\nSalvato: {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
