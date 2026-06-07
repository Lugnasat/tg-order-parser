# ---------------------------------------------
# EXPORTER — пуш обезличенной витрины на портфолио-сайт (модуль экспорта).
#
# Спека `парсер-экспорт-на-сайт` §6: раз в ~7 мин собираем payload из SQLite
# и POST-им его на сайт server-to-server. Парсинг/фильтрацию НЕ трогаем —
# только читаем агрегаты (showcase + почасовые счётчики из seen).
#
# Контракт payload (приёмная сторона — тема davidmuskat, роут dm/v1/feed):
#   { updated, leads[ts,category,snippet], counts_hourly[t,n] }
#
# Транспорт — stdlib urllib (без новых зависимостей на VPS). Настройки берём
# ИЗ ОКРУЖЕНИЯ напрямую (load_dotenv), а не через config: так exporter
# собирает payload и для сухого прогона (--dry) без полного .env парсера.
# Закон приватности соблюдён ещё на записи в showcase (anonymize в collector);
# здесь PII уже нет, сайт дополнительно санитизирует как второй рубеж.
#
# Запуск:
#   python exporter.py         — собрать и запушить (нужны SITE_PUSH_URL/TOKEN)
#   python exporter.py --dry   — собрать и НАПЕЧАТАТЬ payload, без сети
# ---------------------------------------------

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv

import db
from keywords import CATEGORY_LABELS

load_dotenv()

logger = logging.getLogger("exporter")

# сетевой таймаут пуша (секунды): сайт недоступен -> не висим, тик пропускаем
PUSH_TIMEOUT: int = 10

# сколько свежих сниппетов в ленту и сколько часов в график (контракт §6)
LEADS_LIMIT: int = 8
COUNTS_HOURS: int = 48


# -------------------------
# _ISO — unix-epoch (UTC) -> строка ISO 8601 с Z (формат payload, §6).
# -------------------------
def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -------------------------
# BUILD_PAYLOAD — собрать тело запроса из БД. Чистая (без сети) — тестируема
# offline и используется в --dry. Сниппеты в showcase уже обезличены.
# -------------------------
def build_payload(conn) -> dict:
    now = int(datetime.now(tz=timezone.utc).timestamp())

    # лента: свежие обезличенные сниппеты; код категории -> человекочитаемая
    # подпись (нет подписи -> сам код как безопасный фолбэк)
    leads = []
    for created_at, category, snippet in db.recent_showcase(conn, LEADS_LIMIT):
        leads.append({
            "ts": _iso(created_at),
            "category": CATEGORY_LABELS.get(category or "", category or ""),
            "snippet": snippet,
        })

    # график: почасовые счётчики (с нулями для пустых часов)
    counts_hourly = [
        {"t": _iso(t), "n": n}
        for t, n in db.hourly_counts(conn, COUNTS_HOURS)
    ]

    return {
        "updated": _iso(now),
        "leads": leads,
        "counts_hourly": counts_hourly,
    }


# -------------------------
# PUSH — POST payload на сайт с Bearer-токеном. Возвращает True при успехе.
# Сетевые/HTTP-ошибки НЕ роняют процесс (спека §7): логируем и идём дальше —
# потерянный тик восполнит следующий. 401 логируем отдельно (неверный токен).
# -------------------------
def push(payload: dict, url: str, token: str) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=PUSH_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            logger.info("пуш ок: HTTP %s, ответ %s", response.status, body)
            return True

    except urllib.error.HTTPError as e:
        # сайт ответил, но кодом ошибки. 401 = токен не совпал с DM_FEED_TOKEN.
        if e.code == 401:
            logger.error("пуш отклонён 401: токен не совпал с DM_FEED_TOKEN на сайте")
        else:
            logger.error("пуш отклонён HTTP %s: %s", e.code, e.reason)
        return False

    except (urllib.error.URLError, OSError) as e:
        # сайт недоступен/таймаут — не падаем, восполнит следующий тик
        logger.warning("сайт недоступен (%s) — пропускаю тик", e)
        return False


# -------------------------
# MAIN — собрать payload и (если не --dry) запушить.
# -------------------------
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    dry = "--dry" in sys.argv[1:]

    conn = db.connect()
    db.init(conn)  # идемпотентно: гарантируем наличие таблицы showcase
    payload = build_payload(conn)
    conn.close()

    if dry:
        # сухой прогон: показать, ЧТО ушло бы на сайт; сеть не трогаем
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        logger.info(
            "dry-run: leads=%d, counts=%d (сеть не трогали)",
            len(payload["leads"]),
            len(payload["counts_hourly"]),
        )
        return

    url = os.environ.get("SITE_PUSH_URL", "")
    token = os.environ.get("SITE_PUSH_TOKEN", "")

    if not url or not token:
        logger.error(
            "нет SITE_PUSH_URL / SITE_PUSH_TOKEN в .env — пуш невозможен. "
            "Заполни .env (см. README) или гоняй с --dry."
        )
        sys.exit(1)

    push(payload, url, token)


if __name__ == "__main__":
    main()
