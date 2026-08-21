from __future__ import annotations

from pathlib import Path
from itertools import combinations

import pandas as pd

INPUT = Path("data/output/backtest_1x2.csv")
OUT_SEGMENTS = Path("data/output/backtest_segments.csv")
OUT_FILTERS = Path("data/output/backtest_stable_filters.csv")


def stats(df: pd.DataFrame) -> dict:
    bets = len(df)
    if bets == 0:
        return {"bets": 0, "wins": 0, "profit_units": 0.0, "hit_rate": 0.0, "roi": 0.0, "avg_odds": 0.0, "avg_edge": 0.0}
    wins = int((df["profit_units"] > 0).sum())
    profit = float(df["profit_units"].sum())
    return {
        "bets": bets,
        "wins": wins,
        "profit_units": profit,
        "hit_rate": wins / bets,
        "roi": profit / bets,
        "avg_odds": float(df["reference_odds"].mean()),
        "avg_edge": float(df["edge"].mean()),
    }


def add_segment(rows: list[dict], name: str, value: str, df: pd.DataFrame) -> None:
    rows.append({"segment": name, "value": value, **stats(df)})


def main() -> None:
    df = pd.read_csv(INPUT)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Segmenti descrittivi: servono a capire dove nasce il risultato.
    rows: list[dict] = []
    add_segment(rows, "totale", "tutte", df)

    for league, g in df.groupby("league"):
        add_segment(rows, "campionato", str(league), g)
    for sel, g in df.groupby("selection"):
        add_segment(rows, "esito", str(sel), g)

    odds_bins = [1.55, 1.8, 2.2, 2.8, 3.5, 5.0, float("inf")]
    odds_labels = ["1.55-1.79", "1.80-2.19", "2.20-2.79", "2.80-3.49", "3.50-4.99", "5.00+"]
    df["odds_band"] = pd.cut(df["reference_odds"], odds_bins, right=False, labels=odds_labels)
    for band, g in df.groupby("odds_band", observed=True):
        add_segment(rows, "fascia_quota", str(band), g)

    edge_bins = [0.05, 0.07, 0.09, 0.12, 0.16, float("inf")]
    edge_labels = ["5-6.9%", "7-8.9%", "9-11.9%", "12-15.9%", "16%+"]
    df["edge_band"] = pd.cut(df["edge"], edge_bins, right=False, labels=edge_labels)
    for band, g in df.groupby("edge_band", observed=True):
        add_segment(rows, "fascia_edge", str(band), g)

    for (league, sel), g in df.groupby(["league", "selection"]):
        add_segment(rows, "campionato_esito", f"{league} | {sel}", g)

    pd.DataFrame(rows).sort_values(["segment", "roi"], ascending=[True, False]).to_csv(OUT_SEGMENTS, index=False)

    # Ricerca esplorativa di filtri. Per ridurre il rischio di inseguire il rumore,
    # un filtro viene definito "stabile" solo se ha almeno 60 giocate totali,
    # almeno 25 per meta' temporale e ROI positivo in entrambe le meta'.
    midpoint = df["date"].min() + (df["date"].max() - df["date"].min()) / 2
    leagues = [None] + sorted(df["league"].dropna().unique().tolist())
    selections = [None, "H", "D", "A"]
    min_edges = [0.05, 0.07, 0.09, 0.12, 0.16]
    min_odds = [1.55, 1.8, 2.0, 2.2, 2.5]
    max_odds = [2.2, 2.8, 3.5, 5.0, 100.0]

    candidates: list[dict] = []
    for league in leagues:
        for selection in selections:
            for min_edge in min_edges:
                for lo in min_odds:
                    for hi in max_odds:
                        if hi <= lo:
                            continue
                        g = df[(df["edge"] >= min_edge) & (df["reference_odds"] >= lo) & (df["reference_odds"] < hi)]
                        if league is not None:
                            g = g[g["league"] == league]
                        if selection is not None:
                            g = g[g["selection"] == selection]
                        if len(g) < 60:
                            continue
                        first = g[g["date"] <= midpoint]
                        second = g[g["date"] > midpoint]
                        if len(first) < 25 or len(second) < 25:
                            continue
                        s_all, s1, s2 = stats(g), stats(first), stats(second)
                        if s1["roi"] <= 0 or s2["roi"] <= 0:
                            continue
                        candidates.append({
                            "league": league or "TUTTI",
                            "selection": selection or "TUTTI",
                            "min_edge": min_edge,
                            "min_odds": lo,
                            "max_odds": hi if hi < 100 else "nessuno",
                            "bets": s_all["bets"],
                            "profit_units": s_all["profit_units"],
                            "roi": s_all["roi"],
                            "hit_rate": s_all["hit_rate"],
                            "avg_odds": s_all["avg_odds"],
                            "first_half_bets": s1["bets"],
                            "first_half_roi": s1["roi"],
                            "second_half_bets": s2["bets"],
                            "second_half_roi": s2["roi"],
                            "worst_half_roi": min(s1["roi"], s2["roi"]),
                        })

    out = pd.DataFrame(candidates)
    if not out.empty:
        out = out.sort_values(["worst_half_roi", "bets"], ascending=[False, False])
    out.to_csv(OUT_FILTERS, index=False)
    print(f"Segmenti salvati in {OUT_SEGMENTS}")
    print(f"Filtri stabili salvati in {OUT_FILTERS}: {len(out)} candidati")


if __name__ == "__main__":
    main()
