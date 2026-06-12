"""LangGraph agent for Ramit. Uses PostgresSaver for persistent conversation history."""
import asyncio
import logging
import os
from pathlib import Path
from typing import Annotated, TypedDict
import operator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from src.tools import query_knowledge, load_knowledge

logger = logging.getLogger(__name__)

_SOUL_MD = (Path(__file__).parent.parent / "persona" / "SOUL.md").read_text()
_MAX_HISTORY = 20
_COMPACT_BATCH = 10

_MEMORY_FLUSH_PROMPT = (
    "You extract durable facts about a user from a conversation excerpt — "
    "their financial situation, goals, preferences, and anything already "
    "discussed that future replies should remember. Merge these with the "
    "existing summary below. Output ONLY the updated summary as concise "
    "bullet points, under 300 words. No commentary."
)


class AgentState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    chat_id: int
    summary: str
    summarized_through: int


def _get_model() -> str:
    return os.getenv("CHAT_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6-20250514"))


def _get_memory_model() -> str:
    return os.getenv("MEMORY_MODEL", _get_model())


def _get_memory_provider() -> str:
    return os.getenv("MEMORY_PROVIDER", os.getenv("CHAT_PROVIDER", "anthropic"))


async def _call_llm(system: str, messages: list[dict], model: str | None = None, provider: str | None = None) -> str:
    provider = provider or os.getenv("CHAT_PROVIDER", "anthropic")
    model = model or _get_model()

    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        resp = await AsyncAnthropic().messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=messages,
        )
        return resp.content[0].text

    if provider in ("openrouter", "openai"):
        from openai import AsyncOpenAI
        if provider == "openrouter":
            client = AsyncOpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url="https://openrouter.ai/api/v1",
            )
        else:
            client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

        oai_messages = [{"role": "system", "content": system}] + messages
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=oai_messages,
        )
        return resp.choices[0].message.content

    raise ValueError(f"Unknown CHAT_PROVIDER: {provider}")


async def _maybe_compact(state: AgentState) -> dict | None:
    messages = state["messages"]
    if len(messages) <= _MAX_HISTORY:
        return None

    overflow = messages[:-_MAX_HISTORY]
    summarized_through = state.get("summarized_through", 0)
    new_overflow = overflow[summarized_through:]
    if len(new_overflow) < _COMPACT_BATCH:
        return None

    prior_summary = state.get("summary", "") or "(none yet)"
    excerpt = "\n".join(f"{m['role']}: {m['content']}" for m in new_overflow)
    prompt = f"Existing summary:\n{prior_summary}\n\nNew conversation excerpt:\n{excerpt}"

    new_summary = await _call_llm(
        _MEMORY_FLUSH_PROMPT,
        [{"role": "user", "content": prompt}],
        model=_get_memory_model(),
        provider=_get_memory_provider(),
    )
    return {"summary": new_summary, "summarized_through": len(overflow)}


async def _respond(state: AgentState) -> dict:
    user_message = state["messages"][-1]["content"]

    knowledge = await asyncio.to_thread(query_knowledge, user_message)
    summary = state.get("summary", "")
    system = _SOUL_MD
    if summary:
        system += "\n\n## What you remember about this user\n" + summary
    system += "\n\n" + knowledge

    history = state["messages"][-_MAX_HISTORY:]
    text = await _call_llm(system, history)

    update = {"messages": [{"role": "assistant", "content": text}]}
    compaction = await _maybe_compact(state)
    if compaction:
        update.update(compaction)
    return update


async def build_graph(db_url: str):
    pool = AsyncConnectionPool(
        db_url,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    builder = StateGraph(AgentState)
    builder.add_node("respond", _respond)
    builder.set_entry_point("respond")
    builder.add_edge("respond", END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("Agent graph ready.")
    return graph, pool


async def chat(graph, chat_id: int, user_text: str) -> str:
    config = {"configurable": {"thread_id": str(chat_id)}}
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": user_text}], "chat_id": chat_id},
        config=config,
    )
    return result["messages"][-1]["content"]
