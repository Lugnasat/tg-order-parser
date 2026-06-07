# ---------------------------------------------
# DB — дедуп на голом sqlite3 (одна таблица seen). Два уровня:
#   - уровень 1 (точный): тот же (chat_id, message_id) — повтор сообщения;
#   - уровень 2 (cross-chat): тот же канонический fingerprint за окно
#     CROSS_CHAT_WINDOW_SECONDS — один заказ из разных каналов.
# Правки относительно образца:
#   - v2 (2026-06-04): cross-chat дедуп БЕЗ author_id. v1 требовал
#     совпадения автора, но один заказ постят РАЗНЫЕ боты-агрегаторы в
#     разные каналы → авторы не совпадают → дубли текли (спека v2 §1.2).
#     Канонический fingerprint (fingerprint.py) одинаков для заказа из
#     любого канала, автор не нужен. Колонка author_id остаётся (пишется
#     в mark_seen) для возможной диагностики.
#   - П11: created_at храним как unix-epoch int в UTC, не строкой —
#     сравнение окна на числах надёжнее, чем на ISO-строках.
# ---------------------------------------------

import sqlite3
import time

# имя файла БД (в .gitignore через маску *.db)
DB_PATH: str = "seen.db"

# окно cross-chat-дедупа: тот же канонический отпечаток за это время
# (любой канал/автор) — дубль. Тюнимый параметр (подбор на живом потоке).
CROSS_CHAT_WINDOW_SECONDS: int = 30 * 60

# витрина (модуль экспорта на сайт): сколько держим обезличенные сниппеты.
# Спека §7 — не показываем заявки старше суток; чистим при каждой записи.
SHOWCASE_TTL_SECONDS: int = 24 * 60 * 60


# -------------------------
# NOW — текущее время в unix-epoch UTC (правка П11)
# -------------------------
def _now() -> int:
    return int(time.time())


# -------------------------
# CONNECT — соединение с БД (отдельная функция ради тестов на temp-БД)
# -------------------------
def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


# -------------------------
# INIT — создать таблицу seen и индексы (идемпотентно)
# -------------------------
def init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen (
            fingerprint TEXT    NOT NULL,
            chat_id     INTEGER NOT NULL,
            message_id  INTEGER NOT NULL,
            author_id   INTEGER,
            created_at  INTEGER NOT NULL
        )
        """
    )

    # точный дедуп — по (chat_id, message_id); cross-chat — по fingerprint
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_chat_msg ON seen (chat_id, message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_fingerprint ON seen (fingerprint)")

    # витрина: обезличенные сниппеты для ленты на сайте. Отдельная таблица —
    # схему seen (дедуп) НЕ трогаем. В snippet кладём УЖЕ очищенный текст
    # (anonymize на стороне collector) — сырой PII в БД не оседает.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS showcase (
            created_at INTEGER NOT NULL,
            category   TEXT,
            snippet    TEXT    NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_showcase_created ON showcase (created_at)")

    conn.commit()


# -------------------------
# IS_DUPLICATE — два уровня: точный (chat+msg) и cross-chat (fingerprint/окно).
# author_id в сигнатуре сохранён ради совместимости вызова из collector,
# но в проверке v2 НЕ участвует (см. уровень 2 ниже).
# -------------------------
def is_duplicate(
    conn: sqlite3.Connection,
    fingerprint: str,
    chat_id: int,
    message_id: int,
    author_id: int | None,
) -> bool:
    cur = conn.cursor()

    # 1) точный: видели ровно это сообщение в этом чате
    cur.execute(
        "SELECT 1 FROM seen WHERE chat_id = ? AND message_id = ? LIMIT 1",
        (chat_id, message_id),
    )
    if cur.fetchone() is not None:
        return True

    # 2) cross-chat: тот же канонический отпечаток за последние
    #    CROSS_CHAT_WINDOW_SECONDS, НЕЗАВИСИМО от канала и автора.
    #    v2: убрали условие по author_id — один заказ постят разные боты
    #    в разные каналы, авторы не совпадают (диагноз — спека v2 §1.2).
    #    Канонический fingerprint (fingerprint.py) уже одинаков для одного
    #    заказа из любого канала, поэтому автор больше не нужен.
    threshold = _now() - CROSS_CHAT_WINDOW_SECONDS
    cur.execute(
        """
        SELECT 1 FROM seen
        WHERE fingerprint = ?
          AND created_at >= ?
        LIMIT 1
        """,
        (fingerprint, threshold),
    )

    return cur.fetchone() is not None


# -------------------------
# MARK_SEEN — записать увиденное сообщение
# created_at по умолчанию = сейчас; параметр оставлен ради тестов окна 30 мин
# -------------------------
def mark_seen(
    conn: sqlite3.Connection,
    fingerprint: str,
    chat_id: int,
    message_id: int,
    author_id: int | None,
    created_at: int | None = None,
) -> None:
    if created_at is None:
        created_at = _now()

    conn.execute(
        """
        INSERT INTO seen (fingerprint, chat_id, message_id, author_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (fingerprint, chat_id, message_id, author_id, created_at),
    )
    conn.commit()


# -------------------------
# RECORD_SHOWCASE — записать обезличенный сниппет для витрины + чистка старья.
# snippet ДОЛЖЕН быть уже прогнан через anonymize() (закон «0 утечек»);
# пустой сниппет (вырезали всё) не пишем — на ленте ему делать нечего.
# created_at оставлен параметром ради тестов (по умолчанию = сейчас).
# -------------------------
def record_showcase(
    conn: sqlite3.Connection,
    category: str | None,
    snippet: str,
    created_at: int | None = None,
) -> None:
    if not snippet or not snippet.strip():
        return

    if created_at is None:
        created_at = _now()

    conn.execute(
        "INSERT INTO showcase (created_at, category, snippet) VALUES (?, ?, ?)",
        (created_at, category, snippet),
    )

    # чистим записи старше суток (спека §7) — таблица не растёт без предела
    conn.execute(
        "DELETE FROM showcase WHERE created_at < ?",
        (_now() - SHOWCASE_TTL_SECONDS,),
    )
    conn.commit()


# -------------------------
# RECENT_SHOWCASE — последние N сниппетов для ленты (свежие первыми).
# Возвращает «сырьё» (epoch, категория, сниппет); сборку контракта payload
# (ISO-дата, человекочитаемая категория) делает exporter.
# -------------------------
def recent_showcase(
    conn: sqlite3.Connection,
    limit: int = 8,
) -> list[tuple[int, str | None, str]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT created_at, category, snippet FROM showcase "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return cur.fetchall()


# -------------------------
# HOURLY_COUNTS — почасовые счётчики пойманных заказов за последние `hours`.
# Источник — seen.created_at (строка seen = один отправленный релевантный
# заказ). Возвращаем РОВНО `hours` точек (старые → свежие), пустые часы = 0
# (спека §7: пустой период -> нули). Каждая точка — (epoch начала часа, n).
# -------------------------
def hourly_counts(
    conn: sqlite3.Connection,
    hours: int = 48,
) -> list[tuple[int, int]]:
    now = _now()
    current_hour = now - (now % 3600)          # начало текущего часа (UTC)
    start = current_hour - (hours - 1) * 3600  # начало самого старого окна

    cur = conn.cursor()
    cur.execute(
        # (created_at/3600)*3600 — округление вниз к началу часа (целочисленно)
        "SELECT (created_at / 3600) * 3600 AS h, COUNT(*) "
        "FROM seen WHERE created_at >= ? GROUP BY h",
        (start,),
    )
    by_hour = {h: n for h, n in cur.fetchall()}

    return [(start + i * 3600, by_hour.get(start + i * 3600, 0)) for i in range(hours)]
