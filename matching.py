# ---------------------------------------------
# MATCHING — нормализация текста + поиск категории + минус-слова
# Перенос parsing/matching.py образца. Нормализация симметрична для
# текста И ключевика (образец уже так делает, matching.py:31 — правка П1,
# отдельной «правки симметрии» не требуется).
# ---------------------------------------------

import re

from keywords import KEYWORDS, MINUS


# -------------------------
# NORMALIZATION — общая для текста и ключевиков
# -------------------------
def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("ё", "е")

    # убираем пунктуацию (дефисы, точки -> пробел: "telegram-бот" -> "telegram бот")
    text = re.sub(r"[^\w\s]", " ", text)

    # схлопываем пробелы
    text = re.sub(r"\s+", " ", text).strip()

    return text


# -------------------------
# CATEGORY — какая категория ключевиков сработала (или None)
# -------------------------
def extract_category(text: str) -> str | None:
    text = normalize(text)
    words = text.split()

    for category, keywords in KEYWORDS.items():
        for keyword in keywords:

            # префиксный матч: маркер "*" = ловим словоформы по корню (П4)
            if keyword.endswith("*"):
                root = normalize(keyword[:-1])  # срезаем "*" ДО нормализации

                if any(word.startswith(root) for word in words):
                    return category

            # точный матч по границе слова (многословные и точные ключевики)
            else:
                keyword = normalize(keyword)

                if f" {keyword} " in f" {text} ":
                    return category

    return None


# -------------------------
# MINUS — есть ли минус-слово (проверяется ДО ключевиков)
# -------------------------
def has_minus(text: str) -> bool:
    text = normalize(text)

    for minus in MINUS:
        minus = normalize(minus)

        if f" {minus} " in f" {text} ":
            return True

    return False
