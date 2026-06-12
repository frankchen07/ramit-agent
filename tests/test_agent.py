import pytest

from src.agent import (
    AgentState,
    _MAX_HISTORY,
    _COMPACT_BATCH,
    _maybe_compact,
    _respond,
    _get_memory_model,
    _get_memory_provider,
)


def _make_messages(n: int) -> list[dict]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"} for i in range(n)]


@pytest.mark.asyncio
async def test_maybe_compact_returns_none_when_under_max_history():
    state = {"messages": _make_messages(_MAX_HISTORY), "chat_id": 1}
    assert await _maybe_compact(state) is None


@pytest.mark.asyncio
async def test_maybe_compact_returns_none_when_overflow_below_batch():
    state = {"messages": _make_messages(_MAX_HISTORY + _COMPACT_BATCH - 1), "chat_id": 1}
    assert await _maybe_compact(state) is None


@pytest.mark.asyncio
async def test_maybe_compact_triggers_at_batch_threshold(monkeypatch):
    calls = []

    async def fake_call_llm(system, messages, model=None, provider=None):
        calls.append({"system": system, "messages": messages, "model": model, "provider": provider})
        return "- new summary"

    monkeypatch.setattr("src.agent._call_llm", fake_call_llm)

    messages = _make_messages(_MAX_HISTORY + _COMPACT_BATCH)
    state = {"messages": messages, "chat_id": 1, "summary": "- old fact"}

    result = await _maybe_compact(state)

    assert result == {"summary": "- new summary", "summarized_through": _COMPACT_BATCH}
    assert len(calls) == 1
    call = calls[0]
    assert call["model"] == _get_memory_model()
    assert call["provider"] == _get_memory_provider()
    assert "- old fact" in call["messages"][0]["content"]
    overflow = messages[:-_MAX_HISTORY]
    assert overflow[0]["content"] in call["messages"][0]["content"]
    assert overflow[-1]["content"] in call["messages"][0]["content"]


@pytest.mark.asyncio
async def test_maybe_compact_second_compaction_only_summarizes_new_overflow(monkeypatch):
    calls = []

    async def fake_call_llm(system, messages, model=None, provider=None):
        calls.append(messages[0]["content"])
        return "- merged summary"

    monkeypatch.setattr("src.agent._call_llm", fake_call_llm)

    # First compaction already folded the first _COMPACT_BATCH overflow messages.
    messages = _make_messages(_MAX_HISTORY + _COMPACT_BATCH * 2)
    state = {
        "messages": messages,
        "chat_id": 1,
        "summary": "- earlier facts",
        "summarized_through": _COMPACT_BATCH,
    }

    result = await _maybe_compact(state)

    overflow = messages[:-_MAX_HISTORY]
    assert result == {"summary": "- merged summary", "summarized_through": len(overflow)}
    assert len(calls) == 1
    prompt = calls[0]
    assert "- earlier facts" in prompt
    new_overflow = overflow[_COMPACT_BATCH:]
    assert new_overflow[0]["content"] in prompt
    assert new_overflow[-1]["content"] in prompt
    # the first-batch messages were already folded in and shouldn't be re-sent
    assert overflow[0]["content"] not in prompt


@pytest.mark.asyncio
async def test_respond_includes_summary_in_system_prompt(monkeypatch):
    captured = {}

    async def fake_call_llm(system, messages, model=None, provider=None):
        captured["system"] = system
        return "assistant reply"

    def fake_query_knowledge(text):
        return "knowledge chunk"

    monkeypatch.setattr("src.agent._call_llm", fake_call_llm)
    monkeypatch.setattr("src.agent.query_knowledge", fake_query_knowledge)

    state = {
        "messages": [{"role": "user", "content": "hi"}],
        "chat_id": 1,
        "summary": "- makes $120k, wants a house in 2 years",
    }

    await _respond(state)

    assert "## What you remember about this user" in captured["system"]
    assert "makes $120k" in captured["system"]


@pytest.mark.asyncio
async def test_respond_omits_summary_section_when_empty(monkeypatch):
    captured = {}

    async def fake_call_llm(system, messages, model=None, provider=None):
        captured["system"] = system
        return "assistant reply"

    def fake_query_knowledge(text):
        return "knowledge chunk"

    monkeypatch.setattr("src.agent._call_llm", fake_call_llm)
    monkeypatch.setattr("src.agent.query_knowledge", fake_query_knowledge)

    state = {"messages": [{"role": "user", "content": "hi"}], "chat_id": 1}

    await _respond(state)

    assert "## What you remember about this user" not in captured["system"]


def test_get_memory_model_defaults_to_chat_model(monkeypatch):
    monkeypatch.delenv("MEMORY_MODEL", raising=False)
    monkeypatch.setenv("CHAT_MODEL", "claude-sonnet-4-6-20250514")
    assert _get_memory_model() == "claude-sonnet-4-6-20250514"


def test_get_memory_model_uses_memory_model_when_set(monkeypatch):
    monkeypatch.setenv("MEMORY_MODEL", "anthropic/claude-haiku-4.5")
    assert _get_memory_model() == "anthropic/claude-haiku-4.5"


def test_get_memory_provider_defaults_to_chat_provider(monkeypatch):
    monkeypatch.delenv("MEMORY_PROVIDER", raising=False)
    monkeypatch.setenv("CHAT_PROVIDER", "anthropic")
    assert _get_memory_provider() == "anthropic"


def test_get_memory_provider_uses_memory_provider_when_set(monkeypatch):
    monkeypatch.setenv("MEMORY_PROVIDER", "openrouter")
    assert _get_memory_provider() == "openrouter"
