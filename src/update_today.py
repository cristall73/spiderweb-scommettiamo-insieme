from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from backtest_1x2 import build_model, NUMERIC, CATEGORICAL
from build_dataset import add_reference_odds, normalize_one_file
from build_features import add_features

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
CURRENT_SEASON = "2627"
LEAGUES = {"E0": "Premier League", "I1": "Serie A", "D1": "Bundesliga", "SP1": "La Liga", "F1": "Ligue 1"}
HISTORICAL = Path("data/processed/football_matches.csv")
OUT = Path("data/output/today.json")
TMP = Path("data/current")
ROME = ZoneInfo("Europe/Rome")

# Priorità di fonti/colonne quote: usiamo la prima coppia completa disponibile.
OU_PAIRS = [
    ("Avg>2.5", "Avg<2.5", "Media mercato Football-Data"),
    ("Max>2.5", "Max<2.5", "Massima quota mercato Football-Data"),
    ("B365>2.5", "B365<2.5", "Bet365 Football-Data"),
    ("P>2.5", "P<2.5", "Pinnacle Football-Data"),
    ("over_2.5_close", "under_2.5_close", "Media mercato"),
]
BTTS_PAIRS = [
    ("bts_yes_close", "bts_no_close", "Media mercato BTTS"),
    ("BTTSY", "BTTSN", "Football-Data BTTS"),
    ("BTSY", "BTSN", "Football-Data BTTS"),
    ("B365BTTSY", "B365BTTSN", "Bet365 BTTS"),
]


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


def first_pair(raw: pd.DataFrame, pairs: list[tuple[str, str, str]]):
    for a, b, src in pairs:
        if a in raw.columns and b in raw.columns:
            return a, b, src
    return None


def fixture_rows() -> pd.DataFrame:
    path = download(FIXTURES_URL, TMP / "fixtures.csv")
    raw = pd.read_csv(path)
    if "Div" not in raw.columns:
        raise RuntimeError("Il file fixtures.csv non contiene la colonna Div")
    raw = raw[raw["Div"].isin(LEAGUES)].copy()
    raw = add_reference_odds(raw)

    ou = first_pair(raw, OU_PAIRS)
    if ou:
        oc, uc, src = ou
        raw["odds_over25_ref"] = pd.to_numeric(raw[oc], errors="coerce")
        raw["odds_under25_ref"] = pd.to_numeric(raw[uc], errors="coerce")
        raw["ou_odds_source"] = src
    else:
        raw["odds_over25_ref"] = np.nan
        raw["odds_under25_ref"] = np.nan
        raw["ou_odds_source"] = "Non disponibile"

    bt = first_pair(raw, BTTS_PAIRS)
    if bt:
        yc, nc, src = bt
        raw["odds_btts_yes_ref"] = pd.to_numeric(raw[yc], errors="coerce")
        raw["odds_btts_no_ref"] = pd.to_numeric(raw[nc], errors="coerce")
        raw["btts_odds_source"] = src
    else:
        raw["odds_btts_yes_ref"] = np.nan
        raw["odds_btts_no_ref"] = np.nan
        raw["btts_odds_source"] = "Non disponibile"

    raw = raw.rename(columns={"Date": "date", "Time": "time", "HomeTeam": "home_team", "AwayTeam": "away_team"})
    raw["date"] = pd.to_datetime(raw["date"], dayfirst=True, errors="coerce")
    raw["league_code"] = raw["Div"]
    raw["league"] = raw["Div"].map(LEAGUES)
    raw["season"] = CURRENT_SEASON
    raw["data_source"] = "Football-Data.co.uk fixtures"
    for c in ["home_goals", "away_goals", "result_1x2"]:
        raw[c] = np.nan
    return raw


def devig_two(oa: float, ob: float) -> tuple[float, float]:
    ia, ib = 1.0 / oa, 1.0 / ob
    s = ia + ib
    return ia / s, ib / s


def status_rank(status: str) -> int:
    return {"VALIDATA_FORTE": 0, "VALIDATA": 1, "IN_TEST": 2, "NO_BET": 3, "DATI_INSUFFICIENTI": 4}.get(status, 9)


def classify_1x2(league: str, sel: str, edge: float, odds: float) -> tuple[str, str]:
    if league == "Bundesliga" and sel == "A" and edge >= 0.12 and 2.50 <= odds <= 5.00:
        return "VALIDATA_FORTE", "1X2 Bundesliga: 2 · edge ≥12% · quota 2.50–5.00"
    if league == "Bundesliga" and sel == "A" and edge >= 0.12 and 2.00 <= odds <= 5.00:
        return "VALIDATA", "1X2 Bundesliga: 2 · edge ≥12% · quota 2.00–5.00"
    if league == "Serie A" and sel == "A" and edge >= 0.09 and 1.80 <= odds <= 2.80:
        return "IN_TEST", "1X2 Serie A: 2 · edge ≥9% · quota 1.80–2.80"
    return "NO_BET", "Nessun filtro 1X2 validato superato"


def classify_ou(league: str, sel: str, edge: float, odds: float) -> tuple[str, str]:
    if league == "Premier League" and sel == "OVER25" and edge >= 0.07 and 1.70 <= odds <= 2.20:
        return "VALIDATA_FORTE", "Over 2.5 Premier League · edge ≥7% · quota 1.70–2.20"
    if league == "Premier League" and sel == "OVER25" and edge >= 0.05 and 2.00 <= odds <= 2.20:
        return "VALIDATA", "Over 2.5 Premier League · edge ≥5% · quota 2.00–2.20"
    return "NO_BET", "Nessun filtro Over/Under validato superato"


def classify_btts(league: str, edge: float, odds: float) -> tuple[str, str]:
    # Il filtro La Liga è promettente ma con ROI contenuto: resta in osservazione.
    if league == "La Liga" and edge >= 0.12 and 2.00 <= odds <= 4.00:
        return "IN_TEST", "BTTS La Liga · edge ≥12% · quota 2.00–4.00"
    return "NO_BET", "Nessun filtro BTTS validato superato"


def candidate(market: str, selection: str, label: str, p: float, mp: float, odds: float, source: str, status: str, rule: str):
    return {
        "market": market,
        "selection_code": selection,
        "selection": label,
        "model_probability": round(float(p), 4),
        "market_probability": round(float(mp), 4),
        "edge": round(float(p - mp), 4),
        "odds": round(float(odds), 2),
        "odds_source": source,
        "status": status,
        "rule": rule,
    }


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
    completed = completed.drop_duplicates(subset=["league", "date", "home_team", "away_team"], keep="last")

    today_fixtures = fixtures[fixtures["date"].dt.normalize() == today].copy()
    combined = pd.concat([completed, today_fixtures], ignore_index=True, sort=False)
    combined = combined.sort_values(["date", "league", "home_team", "away_team"], na_position="last")
    featured = add_features(combined)

    train = featured[featured["result_1x2"].isin(["H", "D", "A"])].copy()
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

        for _, row in target.iterrows():
            alternatives = []
            league = str(row.get("league") or "")

            # 1X2
            mapping = {
                "H": ("odds_home_ref", "market_prob_home", "1"),
                "D": ("odds_draw_ref", "market_prob_draw", "X"),
                "A": ("odds_away_ref", "market_prob_away", "2"),
            }
            one_x_two = []
            for sel, (oc, mc, label) in mapping.items():
                p, odds, mp = row.get(f"model_prob_{sel}"), row.get(oc), row.get(mc)
                if pd.isna(p) or pd.isna(odds) or pd.isna(mp) or float(odds) <= 1:
                    continue
                one_x_two.append((float(p - mp), sel, label, float(p), float(mp), float(odds)))
            if one_x_two:
                edge, sel, label, p, mp, odds = max(one_x_two, key=lambda x: x[0])
                st, rule = classify_1x2(league, sel, edge, odds)
                alternatives.append(candidate("1X2", sel, label, p, mp, odds, str(row.get("odds_source") or "Football-Data"), st, rule))

            # Over/Under 2.5: probabilità esclusivamente pre-match, medie ultime 10.
            oo, ou = row.get("odds_over25_ref"), row.get("odds_under25_ref")
            h10, a10 = row.get("home_over25_10"), row.get("away_over25_10")
            if not any(pd.isna(x) for x in [oo, ou, h10, a10]) and float(oo) > 1 and float(ou) > 1:
                mp_o, mp_u = devig_two(float(oo), float(ou))
                p_o = float(np.clip((float(h10) + float(a10)) / 2, 0.03, 0.97))
                ou_opts = [(p_o - mp_o, "OVER25", "Over 2.5", p_o, mp_o, float(oo)), ((1-p_o) - mp_u, "UNDER25", "Under 2.5", 1-p_o, mp_u, float(ou))]
                edge, sel, label, p, mp, odds = max(ou_opts, key=lambda x: x[0])
                st, rule = classify_ou(league, sel, edge, odds)
                alternatives.append(candidate("OVER/UNDER 2.5", sel, label, p, mp, odds, str(row.get("ou_odds_source") or "Football-Data"), st, rule))

            # BTTS: entra nella selezione solo se la fonte odierna fornisce entrambe le quote reali.
            oy, on = row.get("odds_btts_yes_ref"), row.get("odds_btts_no_ref")
            hb, ab = row.get("home_btts_10"), row.get("away_btts_10")
            if not any(pd.isna(x) for x in [oy, on, hb, ab]) and float(oy) > 1 and float(on) > 1:
                mp_y, mp_n = devig_two(float(oy), float(on))
                p_y = float(np.clip((float(hb) + float(ab)) / 2, 0.03, 0.97))
                bt_opts = [(p_y-mp_y, "BTTS_YES", "Goal / Sì", p_y, mp_y, float(oy)), ((1-p_y)-mp_n, "BTTS_NO", "No Goal / No", 1-p_y, mp_n, float(on))]
                edge, sel, label, p, mp, odds = max(bt_opts, key=lambda x: x[0])
                st, rule = classify_btts(league, edge, odds)
                alternatives.append(candidate("GOAL / NO GOAL", sel, label, p, mp, odds, str(row.get("btts_odds_source") or "Football-Data"), st, rule))

            if alternatives:
                # Prima lo stato di validazione, poi l'edge: una sola scelta migliore per partita.
                best = sorted(alternatives, key=lambda x: (status_rank(x["status"]), -(x.get("edge") or -99)))[0]
                checked = [a["market"] for a in alternatives]
            else:
                best = {
                    "market": "—", "selection": "—", "model_probability": None, "market_probability": None,
                    "edge": None, "odds": None, "odds_source": "Non disponibile", "status": "DATI_INSUFFICIENTI",
                    "rule": "Quote insufficienti per i mercati analizzati"
                }
                checked = []

            matches.append({
                "league": row.get("league"),
                "time": str(row.get("time") or ""),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                **best,
                "markets_checked": checked,
            })

    matches.sort(key=lambda x: (status_rank(x["status"]), x.get("time") or ""))
    signals = [m for m in matches if m["status"] in {"VALIDATA_FORTE", "VALIDATA", "IN_TEST"}]

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "source": "Football-Data.co.uk + filtri multi-fonte validati",
        "fixtures_count": len(matches),
        "signals_count": len(signals),
        "signals": signals,
        "matches": matches,
        "markets": ["1X2", "Over/Under 2.5", "Goal/No Goal (quando sono disponibili quote reali)"],
        "note": "Il sistema confronta i mercati disponibili e mostra una sola scelta per partita: quella con il filtro più robusto; a parità di validazione privilegia l'edge maggiore. Le quote di riferimento possono differire da Sisal. BTTS viene valutato solo quando sono disponibili quote reali correnti: nessuna quota viene inventata."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"date": payload["date"], "fixtures": len(matches), "signals": len(signals), "markets": payload["markets"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
