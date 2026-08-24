from __future__ import annotations

import update_today_apifootball as radar

_original_api_get = radar.api_get


def safe_api_get(path, params=None):
    try:
        return _original_api_get(path, params)
    except RuntimeError as exc:
        text = str(exc)
        season_limited = (
            'Free plans do not have access to this season' in text
            or 'do not have access to this season' in text
        )
        account_suspended = (
            'Your account is suspended' in text
            or 'account is suspended' in text
        )

        # Se API-Football e' temporaneamente sospesa/non disponibile, il radar
        # non deve fermarsi: prosegue con le altre fonti calendario configurate
        # (Football-Data/Sofascore). Le logiche del modello restano invariate.
        if account_suspended:
            print(f'WARN API-Football sospesa; continuo senza questa fonte per {path} {params}: {text}')
            return {'response': [], 'paging': {'current': 1, 'total': 0}, 'errors': {}}, {}

        # Il piano Free puo negare quote/stagioni specifiche. In quel caso si
        # salta soltanto la richiesta non accessibile e si continua il radar.
        if path == '/odds' and season_limited:
            print(f'WARN quota non accessibile sul piano Free; salto richiesta {params}: {text}')
            return {'response': [], 'paging': {'current': 1, 'total': 0}, 'errors': {}}, {}
        raise


radar.api_get = safe_api_get

if __name__ == '__main__':
    radar.main()
