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
