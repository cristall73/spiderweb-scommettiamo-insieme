from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests


BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

LEAGUES = {
    "E0": "Premier League",
    "I1": "Serie A",
    "D1": "Bundesliga",
    "SP1": "La Liga",
    "F1": "Ligue 1",
}

# Cinque stagioni concluse: prima base per il backtest.
SEASONS = ["2122", "2223", "2324", "2425", "2526"]

RAW_DIR = Path("data/raw")


def download_csv(season: str, league_code: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    destination = RAW_DIR / f"{season}_{league_code}.csv"
    url = BASE_URL.format(season=season, league=league_code)

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def validate_csv(path: Path) -> tuple[int, int]:
    df = pd.read_csv(path)
    return df.shape


def main() -> None:
    total_matches = 0

    for season in SEASONS:
        for league_code, league_name in LEAGUES.items():
            try:
                path = download_csv(season, league_code)
                rows, columns = validate_csv(path)
                total_matches += rows
                print(
                    f"OK | {season} | {league_name:<15} | "
                    f"{rows:>4} partite | {columns:>3} colonne"
                )
            except Exception as exc:
                print(f"ERRORE | {season} | {league_name} | {exc}")

    print(f"\nTotale righe scaricate: {total_matches}")


if __name__ == "__main__":
    main()
