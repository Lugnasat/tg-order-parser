# Парсер заказов в Telegram

Личный Telegram-парсер заказов. Слушает заданные чаты **от лица
твоего аккаунта** (Telethon user-session), ловит релевантные посты по
словарю IT/BA-ключевиков, отсекает мусор (рекламу, предложения услуг,
boilerplate) и шлёт подходящие заказы тебе **в личку бота** со ссылкой на
исходное сообщение. Без ручного дежурства.

## Как это работает

```
Telethon (твой аккаунт) -> слушает SOURCE_CHATS
   -> has_minus?  (минус-слово -> выбросить)
   -> extract_category?  (нет категории -> выбросить)
   -> is_duplicate?  (дубль -> выбросить)
   -> формат сообщения -> aiogram-бот шлёт тебе в личку
```

Два «телеграм-лица»:
- **читатель** — твой аккаунт (через `TELEGRAM_SESSION`), читает чаты;
- **отправитель** — бот (через `BOT_TOKEN`), пишет тебе в личку (`MY_TELEGRAM_ID`).

## Требования

- Python 3.12+ (проверено на 3.14)
- Зависимости: `pip install -r requirements.txt` (telethon, aiogram, python-dotenv)

## Настройка

1. Скопируй `.env.example` в `.env` и заполни:

   | Переменная | Что это | Откуда |
   |---|---|---|
   | `API_ID` / `API_HASH` | ключи входа аккаунта | my.telegram.org → API development tools |
   | `TELEGRAM_SESSION` | строка user-сессии | генерится `generate_session.py` (см. ниже) |
   | `BOT_TOKEN` | токен бота-отправителя | @BotFather |
   | `MY_TELEGRAM_ID` | куда слать заказы (id или группа) | @userinfobot |
   | `SOURCE_CHATS` | чаты-источники (marked-id `-100…`, через запятую) | id видно в логах при первом запуске |
   | `SITE_PUSH_URL` | *(опц.)* URL приёма витрины на сайте | `https://muskat.pro/wp-json/dm/v1/feed` |
   | `SITE_PUSH_TOKEN` | *(опц.)* общий токен пуша | тот же, что `DM_FEED_TOKEN` в `wp-config.php` сайта |

2. Сгенерируй сессию (разово, интерактивно — спросит телефон + код + 2FA):
   ```
   python generate_session.py
   ```
   Полученную строку впиши в `.env` → `TELEGRAM_SESSION=`.

3. Нажми `/start` у бота с того аккаунта, куда указывает `MY_TELEGRAM_ID`
   (иначе бот не сможет тебе написать).

## Запуск (локально)

```
python main.py
```
Логи идут в stdout (время, уровень, событие). Слушатель работает до Ctrl+C.

## Как настраивать фильтр

- **Добавить/убрать чат-источник** — список `SOURCE_CHATS` в `.env`
  (marked-id вида `-100…`, через запятую). Если аккаунт не состоит в
  чате — он сам отсеется на старте с предупреждением в логе.
- **Добавить ключевик** — словарь `KEYWORDS` в `keywords.py`. Принцип:
  фразы по намерению заказа, не голые слова (голое слово ловит boilerplate).
  Маркер `*` в конце = префиксный матч словоформ (только на одиночных словах).
- **Добавить минус-слово** — список `MINUS` в `keywords.py` (отсекает пост
  до проверки ключевиков).

## Деплой на сервер (systemd)

Шаблон юнита — `deploy/freelance-lead-parser.service`. Кратко:

1. Скопировать проект на сервер, например в `/opt/freelance-lead-parser`.
2. Создать venv и поставить зависимости:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. Перенести **заполненный `.env`** на сервер (секреты — только так, не в git).
4. Поправить пути/пользователя в `deploy/freelance-lead-parser.service`,
   скопировать в `/etc/systemd/system/`, затем:
   ```
   sudo systemctl daemon-reload
   sudo systemctl enable --now freelance-lead-parser
   sudo journalctl -u freelance-lead-parser -f   # смотреть логи
   ```

Юнит перезапускает сервис после сбоя. Если сессия отозвана/протухла —
сервис выйдет с ненулевым кодом (в логе будет понятная причина), чтобы это
было видно, а не «работает молча без уведомлений».

> **Одна сессия — один процесс.** Не запускай парсер на сервере и локально
> одновременно с одной и той же `TELEGRAM_SESSION` — Telegram отзовёт ключ.

## Экспорт витрины на сайт (модуль `exporter`)

Отдельный модуль: раз в ~7 мин пушит на портфолио-сайт `muskat.pro`
**обезличенную** сводку — живую ленту последних заявок + почасовой график.
Парсинг/фильтрацию НЕ трогает, только читает агрегаты из той же SQLite.

```
exporter.py -> читает БД (showcase + почасовые из seen)
   -> build_payload(): updated · leads[ts,category,snippet] · counts_hourly[t,n]
   -> POST на SITE_PUSH_URL, заголовок Authorization: Bearer SITE_PUSH_TOKEN
```

**Закон «0 утечек».** Сниппеты обезличиваются `anonymize()` (`anonymize.py`)
**на записи** в таблицу `showcase` (в `collector.py`, после отправки заказа) —
в БД оседает уже чистый текст: ни контактов, ни @ников, ни ссылок, ни
названий площадок. Регресс-тест на реальных заявках:

```
python anonymize_check.py     # все кейсы должны быть OK (это стоп-линия)
```

**Сухой прогон** (собрать payload и напечатать, без сети):

```
python exporter.py --dry
```

**Боевой пуш** (нужны `SITE_PUSH_URL` + `SITE_PUSH_TOKEN` в `.env`):

```
python exporter.py
```
Сайт недоступен/таймаут или неверный токен (401) — не падаем, пишем в лог,
тик восполнит следующий запуск (push «в одну сторону», без ретрай-очереди).

### Запуск по расписанию (systemd timer)

Парсер (`main.py`) крутится постоянно, а `exporter.py` — разовый прогон по
таймеру. Рядом с сервисом парсера заводим пару `*.service` + `*.timer`:

```ini
# /etc/systemd/system/lead-exporter.service  (Type=oneshot)
[Service]
Type=oneshot
WorkingDirectory=/opt/freelance-lead-parser
EnvironmentFile=/opt/freelance-lead-parser/.env
ExecStart=/opt/freelance-lead-parser/.venv/bin/python exporter.py
```
```ini
# /etc/systemd/system/lead-exporter.timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=7min
[Install]
WantedBy=timers.target
```
```
sudo systemctl daemon-reload
sudo systemctl enable --now lead-exporter.timer
sudo journalctl -u lead-exporter -f   # смотреть пуши
```

Альтернатива — cron: `*/7 * * * * cd /opt/freelance-lead-parser && .venv/bin/python exporter.py`.

План реализации: [plans/2026-05-31-mvp-freelance-lead-parser.md](plans/2026-05-31-mvp-freelance-lead-parser.md)
