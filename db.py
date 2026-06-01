# ---------------------------------------------
# DB — дедуп на голом sqlite3 (одна таблица seen)
# Семантика перенесена из образца (services/lead_service.py): два уровня
# дедупа. Правки относительно образца:
#   - П2: голый sqlite3 НЕ превращает (author_id = None) в IS NULL сам,
#     поэтому NULL-автора (пост «от имени канала», Г6) обрабатываем явно;
#   - П11: created_at храним как unix-epoch int в UTC, не строкой —
#     сравнение окна «30 минут» на числах надёжнее, чем на ISO-строках.
# ---------------------------------------------

import sqlite3
import time

# имя файла БД (в .gitignore через маску *.db)
DB_PATH: str = "seen.db"

# окно cross-chat-дедупа: тот же текст того же автора за 30 минут — дубль
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
# IS_DUPLICATE — два уровня: точный (chat+msg) и cross-chat (fingerprint+автор/30мин)
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

    # 2) cross-chat: тот же текст того же автора за последние 30 минут.
    #    NULL-автора сравниваем явно (правка П2): на голом sqlite3
    #    `author_id = NULL` всегда ложь, поэтому дедуп №2 для постов
    #    «от имени канала» (автор None, Г6) без этого тихо течёт.
    threshold = _now() - CROSS_CHAT_WINDOW_SECONDS
    cur.execute(
        """
        SELECT 1 FROM seen
        WHERE fingerprint = ?
          AND (author_id = ? OR (? IS NULL AND author_id IS NULL))
          AND created_at >= ?
        LIMIT 1
        """,
        (fingerprint, author_id, author_id, threshold),
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
