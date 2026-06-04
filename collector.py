# ---------------------------------------------
# COLLECTOR — Telethon-слушатель + обработка сообщения + отправка боту.
#
# Правки относительно образца:
#   - П7: фильтр на уровне подписки (events.NewMessage(chats=SOURCE_CHATS)),
#     а вся логика решения вынесена в ЧИСТУЮ process_message() — её гоняем
#     offline синтетическими событиями, без Telegram;
#   - П6: сетевой сбой -> ретрай; ошибка авторизации (сессия отозвана/протухла)
#     -> понятный лог + выход с кодом !=0 (обрабатывается в main.py),
#     чтобы systemd показал failed, а не крутил молча без уведомлений;
#   - mark_seen вызываем ПОСЛЕ успешной отправки — иначе сбой связи «съел бы»
#     заказ (пометили seen, но не доставили).
# ---------------------------------------------

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from telethon import TelegramClient, events
from telethon import errors as telethon_errors
from telethon.sessions import StringSession

import db
# ВНИМАНИЕ: config НЕ импортируем на уровне модуля — он строго требует все
# секреты (.env), а offline-ядро (process_message) должно тестироваться без
# них (П7). Секреты подгружаем лениво, внутри run().
from matching import has_minus, extract_category
from fingerprint import fingerprint
from link import build_link
from formatter import format_message

logger = logging.getLogger("collector")

# пауза переподключения при транзиентном сетевом сбое (как в образце)
RECONNECT_DELAY: int = 5


# -------------------------
# AUTH_FATAL — ошибки авторизации, при которых НЕЛЬЗЯ молча ретраить (П6).
# Собираем кортеж по именам через getattr — устойчиво к разнице версий Telethon.
# -------------------------
def _auth_fatal_errors() -> tuple[type[BaseException], ...]:
    names = [
        "AuthKeyError",
        "AuthKeyUnregisteredError",
        "SessionRevokedError",
        "SessionExpiredError",
        "UserDeactivatedError",
        "UnauthorizedError",
    ]

    found: list[type[BaseException]] = []
    rpc = getattr(telethon_errors, "rpcerrorlist", None)

    for name in names:
        err = getattr(telethon_errors, name, None) or getattr(rpc, name, None)

        if err is not None:
            found.append(err)

    return tuple(found)


AUTH_FATAL = _auth_fatal_errors()


# -------------------------
# PROCESS_MESSAGE — ЧИСТАЯ оркестрация (без Telethon): решает, слать ли пост.
# Возвращает готовый текст уведомления или None (если пост отбрасываем).
# НЕ пишет в БД — mark_seen зовём после успешной отправки (см. handler).
# -------------------------
def process_message(
    conn,
    text: str,
    chat_id: int,
    message_id: int,
    author_id: int | None,
    username: str | None,
) -> str | None:
    # пустое / не-текстовое сообщение
    if not text or not text.strip():
        return None

    # минус-слово -> отбрасываем ДО проверки ключевиков
    if has_minus(text):
        return None

    # нет категории -> не наш заказ
    category = extract_category(text)
    if category is None:
        return None

    # дубль (оба уровня) -> skip. ДИАГ-лог (v2, период наблюдения): пишем
    # срабатывание дедупа в journald — иначе «событие без отправки»
    # неотличимо от отсева по фильтру/минус-слову. fp режем до 8 символов
    # (для глаза хватает сопоставить дубли). После наблюдения строку можно убрать.
    fp = fingerprint(text)
    if db.is_duplicate(conn, fp, chat_id, message_id, author_id):
        logger.info("дубль срезан: чат %s msg %s (fp %s)", chat_id, message_id, fp[:8])
        return None

    # собрать ссылку и готовый текст
    link = build_link(chat_id, message_id, username)

    return format_message(category, text, link)


# -------------------------
# RUN — поднять бота и Telethon-слушатель, слушать до обрыва соединения.
# Бросает исключение наверх (в main.py), где решается ретрай / выход.
# -------------------------
async def run(conn) -> None:
    # секреты подгружаем здесь (а не на уровне модуля) — чтобы импорт collector
    # для offline-тестов process_message не требовал заполненного .env (П7)
    from config import (
        API_ID,
        API_HASH,
        TELEGRAM_SESSION,
        BOT_TOKEN,
        MY_TELEGRAM_ID,
        SOURCE_CHATS,
    )

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    client = TelegramClient(StringSession(TELEGRAM_SESSION), API_ID, API_HASH)

    await client.start()

    # отсеиваем недоступные чаты: id, в которых аккаунт не состоит, не должны
    # ломать подписку на остальные (диагностика показала 10/13). П7-фильтр
    # строим только из реально доступных источников.
    resolved = []
    missing = []
    for cid in SOURCE_CHATS:
        try:
            resolved.append(await client.get_input_entity(cid))
        except Exception:
            missing.append(cid)

    if missing:
        logger.warning("аккаунт НЕ состоит в этих чатах, пропускаю: %s", missing)

    logger.info("подписка на %d из %d чатов", len(resolved), len(SOURCE_CHATS))

    # фильтр на уровне подписки (П7): хендлер не дёргается на чужих чатах
    async def handler(event) -> None:
        try:
            chat_id = event.chat_id
            message_id = event.message.id
            text = event.raw_text  # чистый текст; для не-текстовых будет пустым

            # лог входящего события — живая проверка Г2 (формат chat_id долетает)
            logger.info("событие из чата %s (msg %s)", chat_id, message_id)

            sender = await event.get_sender()
            author_id = getattr(sender, "id", None)  # пост «от имени канала» -> None (Г6)

            chat = await event.get_chat()
            username = getattr(chat, "username", None)

            message = process_message(conn, text, chat_id, message_id, author_id, username)

            if message:
                await bot.send_message(MY_TELEGRAM_ID, message)

                # помечаем seen ТОЛЬКО после успешной отправки (защита от потери)
                db.mark_seen(conn, fingerprint(text), chat_id, message_id, author_id)

                logger.info("заказ отправлен: чат %s msg %s", chat_id, message_id)

        except Exception:
            # одно битое событие не должно ронять слушатель целиком
            logger.exception("ошибка обработки события")

    client.add_event_handler(handler, events.NewMessage(chats=resolved))

    logger.info("слушатель запущен")

    await client.run_until_disconnected()
