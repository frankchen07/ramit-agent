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


class AgentState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    chat_id: int


def _get_model() -> str:
    return os.getenv("CHAT_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6-20250514"))


async def _call_llm(system: str, messages: list[dict]) -> str:
    provider = os.getenv("CHAT_PROVIDER", "anthropic")
    model = _get_model()

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


async def _respond(state: AgentState) -> dict:
    user_message = state["messages"][-1]["content"]

    knowledge = await asyncio.to_thread(query_knowledge, user_message)
    system = _SOUL_MD + "\n\n" + knowledge
    history = state["messages"][-_MAX_HISTORY:]

    text = await _call_llm(system, history)
    return {"messages": [{"role": "assistant", "content": text}]}


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
