# ---------------------------------------------
# ANONYMIZE_CHECK — offline-проверка закона «0 утечек» (спека §8).
#
# Telegram/секреты НЕ нужны — импортируем только anonymize. Прогоняем через
# anonymize() РЕАЛЬНЫЕ заявки из живого потока (с хвостами площадок: Автор/
# Проект/Kwork Бот/бюджет/ссылки) + синтетические кейсы с явным PII (телефон,
# e-mail, @ник, ссылка, markdown-ссылка).
#
# Две проверки на каждый кейс:
#   УНИВЕРСАЛЬНАЯ — в выходе НЕТ структурного PII: '@', http/t.me/www,
#                   e-mail, прогон 7+ цифр (телефон/длинный id), имя площадки.
#   ТОЧЕЧНАЯ      — конкретные ники/телефоны/домены этого кейса исчезли.
# Плюс: для реальных заказов сниппет НЕ должен схлопнуться в пустоту.
#
# Запуск: python anonymize_check.py
# ---------------------------------------------

import re

from anonymize import anonymize


# -------------------------
# CASES — (имя, сырой текст, [подстроки, которых в выходе быть НЕ должно],
#          ожидаем_непустой_сниппет)
# Реальные заявки взяты из потока 04.06.2026 (см. dedup_check.py).
# -------------------------
CASES: list[tuple[str, str, list[str], bool]] = [
    ("Верстка (freelance_zakazy, хвост бюджет/хэштег)",
     "📌 Верстка сайта\n\n📝 Всем доброго дня!\n"
     "Необходимо сверстать сайт по макету (только верстка)\n"
     "Адаптив на свое виденье\n"
     "Спасибо!\n〰️〰️〰️〰️\n💳 Бюджет:\nОт  12,000 ₽  до  36,000 ₽\n"
     "〰️〰️〰️〰️\n🌐 Оплата на любую карту мира\n#верстка",
     ["12,000", "36,000", "₽", "#верстка"], True),

    ("Openclaw (kwork_market, Автор+Проект+Kwork Бот)",
     "Настройка Openclaw\n\nНужно развернуть и стартово настроить Openclaw на VDS.\n"
     "Прошу оценивать силы и не играть, а сделать!\n\n=============\nБюджет: 1000 - 1000\n"
     "Проект: 3190351\nАвтор: infoexpert\n🤖 Kwork Бот",
     ["infoexpert", "3190351", "Kwork", "====="], True),

    ("Верстка (kwork, Автор: devdfarino46)",
     "Верстка сайта\n\nНеобходимо сверстать сайт по макету.\n"
     "=============\nБюджет: 12000 - 36000\nПроект: 3190320\n"
     "Автор: devdfarino46\n🤖 Kwork Бот",
     ["devdfarino46", "3190320", "12000", "36000"], True),

    ("Явный PII: @ник + телефон",
     "Нужен телеграм-бот под заявки. Свяжитесь @ivan_petrov или по тел "
     "+7 (999) 123-45-67, можно 8 999 765 43 21.",
     ["@ivan_petrov", "ivan_petrov", "999", "123-45-67", "765"], True),

    ("Явный PII: e-mail",
     "Требуется парсер маркетплейса в Excel. Почта для связи: john.doe@example.com",
     ["john.doe@example.com", "@example", "example.com"], True),

    ("Явный PII: голая ссылка + t.me",
     "Доработать корзину WooCommerce. Подробности https://disk.yandex.ru/d/abc123 "
     "и в канале t.me/myprivatechan/42",
     ["https://disk.yandex.ru", "yandex.ru", "t.me/myprivatechan", "myprivatechan"], True),

    ("Явный PII: markdown-ссылка (текст оставляем, url режем)",
     "Связать форму с amoCRM. [Техзадание тут](https://evil.tracker.io/u/777)",
     ["evil.tracker.io", "https://evil.tracker.io", "/u/777", "777"], True),
]


# -------------------------
# UNIVERSAL_LEAKS — структурный PII, который НЕ должен уцелеть ни в одном выходе.
# Возвращает список найденных утечек (пусто = чисто).
# -------------------------
_RE_DIGIT_RUN = re.compile(r"\+?\d[\d\s().\-]{5,}\d")


def universal_leaks(out: str) -> list[str]:
    leaks: list[str] = []
    low = out.lower()

    if "@" in out:
        leaks.append("символ '@' (ник/почта)")
    for token in ("http", "t.me", "www."):
        if token in low:
            leaks.append(f"ссылка '{token}'")
    if "kwork" in low:
        leaks.append("название площадки 'kwork'")

    # прогон из 7+ цифр (телефон/длинный id)
    for m in _RE_DIGIT_RUN.finditer(out):
        if sum(ch.isdigit() for ch in m.group(0)) >= 7:
            leaks.append(f"7+ цифр подряд: «{m.group(0).strip()}»")
            break

    return leaks


# -------------------------
# RUN — прогнать кейсы, собрать вердикт
# -------------------------
def main() -> None:
    print("ANONYMIZE — проверка закона «0 утечек»")
    print("-" * 70)

    ok = True

    for name, raw, forbidden, expect_nonempty in CASES:
        out = anonymize(raw)

        problems: list[str] = list(universal_leaks(out))

        # точечные подстроки кейса
        for needle in forbidden:
            if needle.lower() in out.lower():
                problems.append(f"осталось «{needle}»")

        # сниппет не должен схлопнуться в пустоту (для реальных заказов)
        if expect_nonempty and not out.strip():
            problems.append("сниппет пуст (вырезали всё)")

        clean = not problems
        ok = ok and clean
        mark = "OK " if clean else "!! "

        print(f"{mark}«{name}»")
        print(f"     -> «{out}»")
        if problems:
            for p in problems:
                print(f"     !! УТЕЧКА: {p}")

    print("\n" + "=" * 70)
    if ok:
        print("ИТОГ: все кейсы чистые — PII не утекает, сниппеты читаемы.")
    else:
        print("ИТОГ: ЕСТЬ УТЕЧКИ — см. строки с !! выше. Это СТОП-линия.")


if __name__ == "__main__":
    main()
