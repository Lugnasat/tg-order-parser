# ---------------------------------------------
# MAIN — точка входа: настройка логирования -> init БД -> запуск слушателя.
# Reconnect-loop с разделением ошибок (П6):
#   - сетевой/транзиентный сбой -> лог + пауза + переподключение;
#   - ошибка авторизации (сессия отозвана/протухла) -> понятный лог + выход
#     с кодом !=0, чтобы systemd показал failed, а не крутил молча.
# Логирование инлайн в stdout (П8) — journald заберёт под systemd.
# ---------------------------------------------

import asyncio
import logging
import sys

import db
from collector import run, AUTH_FATAL, RECONNECT_DELAY

logger = logging.getLogger("main")


# -------------------------
# SETUP_LOGGING — stdout, уровень + таймстемп (П8)
# -------------------------
def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


# -------------------------
# MAIN — инициализация БД + reconnect-loop (П6)
# -------------------------
async def main() -> None:
    conn = db.connect()
    db.init(conn)

    while True:
        try:
            await run(conn)

        except AUTH_FATAL as e:
            # сессия мертва — молчать нельзя, выходим с ненулевым кодом
            logger.error(
                "Авторизация Telegram не прошла: %s. "
                "Сессия отозвана/протухла — перегенерируй TELEGRAM_SESSION "
                "через generate_session.py и обнови .env.",
                e,
            )
            sys.exit(1)

        except Exception as e:
            # транзиентный сбой — ждём и переподключаемся
            logger.warning(
                "Сбой соединения: %s. Переподключение через %d c.",
                e,
                RECONNECT_DELAY,
            )
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
