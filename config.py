# ---------------------------------------------
# CONFIG — секреты из .env + статический список чатов-источников
# Секреты НЕ хранятся в коде и НЕ коммитятся — только в .env (он в .gitignore).
# Отличие от образца: при отсутствии ключа — понятная ошибка, а не None молча.
# ---------------------------------------------

import os

from dotenv import load_dotenv

# подхватываем .env из текущей папки (если есть)
load_dotenv()


# -------------------------
# _REQUIRED — взять переменную из окружения или упасть с понятным текстом
# -------------------------
def _required(name: str) -> str:
    value = os.environ.get(name)

    if not value:
        raise RuntimeError(
            f"В .env нет обязательной переменной {name}. "
            f"Скопируй .env.example в .env и заполни значения."
        )

    return value


# -------------------------
# СЕКРЕТЫ (из .env)
# -------------------------
API_ID: int = int(_required("API_ID"))
API_HASH: str = _required("API_HASH")
TELEGRAM_SESSION: str = _required("TELEGRAM_SESSION")

BOT_TOKEN: str = _required("BOT_TOKEN")

# id Давида — куда бот шлёт заказы; приводим к int (os.environ отдаёт строку,
# а send_message ждёт число — правка П10)
MY_TELEGRAM_ID: int = int(_required("MY_TELEGRAM_ID"))


# -------------------------
# SOURCE_CHATS — чаты-источники (marked-id вида -100…), из .env
# Список держим в .env, а не в коде: событие из чата не из списка -> skip
# (это и есть фильтр источников; аккаунт сессии уже состоит в этих чатах).
# Почему из .env: чтобы не светить личные источники в публичном репозитории
# и менять их без правки кода. Формат в .env — id через запятую.
# -------------------------
SOURCE_CHATS: list[int] = [
    int(chat_id.strip())
    for chat_id in _required("SOURCE_CHATS").split(",")
    if chat_id.strip()
]
