# ---------------------------------------------
# GENERATE_SESSION — разовый генератор строки Telethon-сессии.
# Запускается ОДИН раз, вместе с Давидом: логин по номеру/коду телефона,
# на выходе — строка TELEGRAM_SESSION (её Давид вписывает в .env).
#
# ВАЖНО: читаем только API_ID / API_HASH напрямую из .env, а НЕ через
# config.py — иначе сработал бы его строгий _required на TELEGRAM_SESSION,
# которой на этом шаге ещё нет (она и есть результат скрипта).
# ---------------------------------------------

import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]


# -------------------------
# MAIN — логин и печать строки сессии
# -------------------------
async def main() -> None:
    # пустая StringSession -> Telethon попросит номер телефона и код из Telegram
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        session_str = client.session.save()

        print("\n" + "=" * 50)
        print("ВАША TELEGRAM_SESSION (вставь её в .env):")
        print("=" * 50)
        print(session_str)
        print("=" * 50)
        print("Никому не показывай эту строку — это доступ к аккаунту.\n")


asyncio.run(main())
