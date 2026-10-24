import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telegram import Chat, Message, Update, User
from telegram.constants import ParseMode
from telegram.error import BadRequest

from src.bot import (
    _MAX_MSG_LEN,
    _allowed_user_ids,
    _split_message,
    _to_telegram_html,
    handle_error,
    handle_message,
)


def test_short_message_returned_unchanged():
    text = "Here's a quick budgeting tip."
    assert _split_message(text) == [text]


def test_message_at_limit_returned_unchanged():
    text = "x" * _MAX_MSG_LEN
    assert _split_message(text) == [text]


def test_long_message_splits_on_paragraph_breaks():
    paragraph = "x" * 1000
    text = "\n\n".join([paragraph] * 5)  # ~5004 chars, over the 4096 limit

    chunks = _split_message(text)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk  # no empty chunks (Telegram rejects empty messages)
        assert len(chunk) <= _MAX_MSG_LEN
    # no content lost
    assert "".join(chunks).replace("\n\n", "").replace("\n", "") == text.replace("\n\n", "")


def test_unbroken_long_message_hard_splits():
    text = "x" * (_MAX_MSG_LEN * 2 + 10)

    chunks = _split_message(text)

    assert len(chunks) == 3
    for chunk in chunks:
        assert len(chunk) <= _MAX_MSG_LEN
    assert "".join(chunks) == text


def test_leading_whitespace_does_not_produce_empty_chunk():
    # LLMs sometimes prepend a blank line; a naive splitter could turn
    # the leading "\n\n" into its own empty chunk.
    text = "\n\n" + "x" * (_MAX_MSG_LEN + 10)

    chunks = _split_message(text)

    assert all(chunk for chunk in chunks)
    for chunk in chunks:
        assert len(chunk) <= _MAX_MSG_LEN


def _make_update(text: str) -> Update:
    message = Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=4242, type="private"),
        from_user=User(id=777, first_name="Pat", is_bot=False),
        text=text,
    )
    return Update(update_id=99, message=message)


@pytest.mark.asyncio
async def test_handle_error_does_not_log_message_text(caplog):
    update = _make_update("my salary is 123456")
    context = SimpleNamespace(error=RuntimeError("boom"))

    with caplog.at_level(logging.ERROR, logger="src.bot"):
        await handle_error(update, context)

    assert "123456" not in caplog.text
    assert "Pat" not in caplog.text
    assert "4242" in caplog.text


def test_to_telegram_html_converts_bold_and_code():
    assert _to_telegram_html("**Automate** it with `401k`") == "<b>Automate</b> it with <code>401k</code>"


def test_to_telegram_html_converts_headings():
    assert _to_telegram_html("## The Plan\nDo it") == "<b>The Plan</b>\nDo it"


def test_to_telegram_html_escapes_html():
    assert _to_telegram_html("fixed costs < 60% & rising") == "fixed costs &lt; 60% &amp; rising"


def test_to_telegram_html_leaves_bullets_alone():
    assert _to_telegram_html("* rent\n* food") == "* rent\n* food"


@pytest.mark.asyncio
async def test_handle_message_falls_back_to_plain_text_when_html_rejected(monkeypatch):
    sent = []

    async def fake_reply_text(text, parse_mode=None):
        if parse_mode == ParseMode.HTML:
            raise BadRequest("Can't parse entities")
        sent.append(text)

    async def fake_chat(graph, chat_id, text):
        return "**Bold** reply"

    async def fake_send_chat_action(chat_id, action):
        pass

    monkeypatch.setattr("src.bot.chat", fake_chat)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=777),
        effective_chat=SimpleNamespace(id=4242),
        message=SimpleNamespace(text="hi", reply_text=fake_reply_text),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"graph": None, "allowed_user_ids": {777}}),
        bot=SimpleNamespace(send_chat_action=fake_send_chat_action),
    )

    await handle_message(update, context)

    assert sent == ["**Bold** reply"]


@pytest.mark.asyncio
async def test_handle_message_rejects_user_not_on_allowlist(monkeypatch):
    sent = []
    chat_calls = []

    async def fake_reply_text(text, parse_mode=None):
        sent.append(text)

    async def fake_chat(graph, chat_id, text):
        chat_calls.append(text)
        return "should not happen"

    monkeypatch.setattr("src.bot.chat", fake_chat)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_chat=SimpleNamespace(id=4242),
        message=SimpleNamespace(text="hi", reply_text=fake_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"graph": None, "allowed_user_ids": {777}}))

    await handle_message(update, context)

    assert chat_calls == []
    assert len(sent) == 1


def test_allowed_user_ids_parses_comma_separated_env(monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_USER_IDS", " 111, 222,,333 ")
    assert _allowed_user_ids() == {111, 222, 333}


def test_allowed_user_ids_refuses_to_start_when_unset(monkeypatch):
    # An empty allowlist would open the bot (and the API bill) to anyone.
    monkeypatch.delenv("ADMIN_TELEGRAM_USER_IDS", raising=False)
    with pytest.raises(SystemExit):
        _allowed_user_ids()


def test_to_telegram_html_bare_heading_does_not_swallow_next_line():
    assert _to_telegram_html("##\n- item") == "##\n- item"
