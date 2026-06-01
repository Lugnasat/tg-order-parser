# ---------------------------------------------
# FINGERPRINT — md5-отпечаток текста для дедупа
# Берётся из образца (utils/fingerprint.py) как есть.
# ---------------------------------------------

import hashlib


# -------------------------
# FINGERPRINT — одинаков для одинакового текста
# -------------------------
def fingerprint(text: str) -> str:
    # мягкая нормализация: регистр + крайние пробелы (как в образце)
    normalized = text.lower().strip()

    return hashlib.md5(normalized.encode()).hexdigest()
