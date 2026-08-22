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
        # Il piano Free consente il calendario corrente ma puo negare le quote
        # di alcune stagioni. In quel caso non deve saltare l'intero radar:
        # registriamo la lega/season e proseguiamo con le successive.
        if path == '/odds' and season_limited:
            print(f'WARN quota non accessibile sul piano Free; salto richiesta {params}: {text}')
            return {'response': [], 'paging': {'current': 1, 'total': 0}, 'errors': {}}, {}
        raise


radar.api_get = safe_api_get

if __name__ == '__main__':
    radar.main()
