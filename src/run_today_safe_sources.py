from __future__ import annotations

import update_today_multisource as multi


ORIGINAL_FOOTBALL_DATA_ORG_CALENDAR = multi.football_data_org_calendar


def disabled_legacy_football_data_calendar(date_iso):
    """Disabilita il vecchio feed CSV Football-Data.

    Il feed legacy sta restituendo contenuto non CSV e genera errori di parsing.
    Usiamo invece football-data.org via API/token, gia gestita da
    update_today_multisource.py con una sola richiesta per run.
    """
    print('INFO vecchio feed CSV Football-Data disabilitato; uso football-data.org API con token.')
    return [], 0


def diagnostic_football_data_org_calendar(date_iso, now):
    """Aggiunge diagnostica senza fare richieste API aggiuntive.

    La funzione originale esegue l'unica chiamata a football-data.org; qui
    leggiamo soltanto il risultato gia ottenuto e stampiamo quante partite
    grezze sono arrivate e quante sono rimaste utilizzabili dopo i controlli.
    """
    events, raw_count = ORIGINAL_FOOTBALL_DATA_ORG_CALENDAR(date_iso, now)
    print(
        'DIAG football-data.org: '
        f'righe_api={int(raw_count or 0)}, '
        f'utili_dopo_controlli={len(events)}, '
        'richieste_extra=0'
    )
    if raw_count and not events:
        print('DIAG football-data.org: l API ha restituito partite, ma nessuna e rimasta utilizzabile dopo i controlli.')
    elif not raw_count:
        print('DIAG football-data.org: la risposta valida dell API contiene 0 partite per la data richiesta.')
    return events, raw_count


# Riduce richieste e rimuove il parser legacy difettoso. Il modello SpiderWeb,
# i filtri, le soglie, le probabilita e la selezione delle giocate non cambiano.
multi.radar_job.football_data_calendar = disabled_legacy_football_data_calendar
multi.football_data_org_calendar = diagnostic_football_data_org_calendar


if __name__ == '__main__':
    multi.radar_job.main()
