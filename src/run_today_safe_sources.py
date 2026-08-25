from __future__ import annotations

import update_today_multisource as multi


def disabled_legacy_football_data_calendar(date_iso):
    """Disabilita il vecchio feed CSV Football-Data.

    Il feed legacy sta restituendo contenuto non CSV e genera errori di parsing.
    Usiamo invece football-data.org via API/token, gia gestita da
    update_today_multisource.py con una sola richiesta per run.
    """
    print('INFO vecchio feed CSV Football-Data disabilitato; uso football-data.org API con token.')
    return [], 0


# Riduce richieste e rimuove il parser legacy difettoso. Il modello SpiderWeb,
# i filtri, le soglie, le probabilita e la selezione delle giocate non cambiano.
multi.radar_job.football_data_calendar = disabled_legacy_football_data_calendar


if __name__ == '__main__':
    multi.radar_job.main()
