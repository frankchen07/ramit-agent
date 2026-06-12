from src.bot import _MAX_MSG_LEN, _split_message


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
