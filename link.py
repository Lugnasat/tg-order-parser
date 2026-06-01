# ---------------------------------------------
# LINK — ссылка на исходное сообщение (публичная / приватная)
# Образец умел только приватную форму (/c/) — расширяем публичной.
# ---------------------------------------------


# -------------------------
# BUILD_LINK — публичная ссылка при наличии username, иначе приватная
# -------------------------
def build_link(chat_id: int, message_id: int, username: str | None) -> str:
    # публичный канал/группа с @username -> прямая ссылка
    if username:
        return f"https://t.me/{username}/{message_id}"

    # приватный супергруппа/канал -> /c/<internal_id>/<message_id>,
    # где internal_id = marked-id без префикса -100 (как в образце)
    internal_id = str(chat_id)

    if internal_id.startswith("-100"):
        internal_id = internal_id[4:]

    return f"https://t.me/c/{internal_id}/{message_id}"
