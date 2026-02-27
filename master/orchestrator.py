"""Orchestrator: GPT-4o-mini decides answer_directly or call_tool."""
from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

SYSTEM = """You are an orchestrator. Given a user query and a list of available agents with their tools (each tool has name, description, parameters), you must respond with exactly one JSON object, no other text.

If the query can be answered by calling one of the tools, you MUST respond with:
{"action": "call_tool", "agent_id": "<agent_id>", "tool_name": "<tool name>", "arguments": {<tool arguments as key-value pairs>}}

Only if the query cannot be answered by any tool (e.g. greeting, meta-questions about the conversation, or no relevant tool exists) respond with:
{"action": "answer_directly", "text": "<your short answer>"}

Prefer calling a tool when a tool clearly applies (e.g. weather questions -> weather tools). Use only agent_id and tool_name from the provided list. Arguments must match the tool's parameters. Respond with valid JSON only."""


async def decide_with_messages(
    openai_client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Same as decide() but accepts full message list (system + history + last user with tools + query).
    Returns {"action": "answer_directly", "text": "..."} or {"action": "call_tool", ...}.
    """
    resp = await openai_client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
    )
    content = (resp.choices[0].message.content or "").strip()
    return _parse_decision(content)


def _parse_decision(content: str) -> dict[str, Any]:
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return {"action": "answer_directly", "text": f"I couldn't parse a response. Raw: {content[:200]}"}
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"action": "answer_directly", "text": f"Invalid JSON from model: {content[:200]}"}
    if out.get("action") == "answer_directly":
        return {"action": "answer_directly", "text": out.get("text", "") or "No answer."}
    if out.get("action") == "call_tool":
        return {
            "action": "call_tool",
            "agent_id": out.get("agent_id", ""),
            "tool_name": out.get("tool_name", ""),
            "arguments": out.get("arguments") or {},
        }
    return {"action": "answer_directly", "text": f"Unknown action: {out}"}


async def decide(
    openai_client: AsyncOpenAI,
    model: str,
    query: str,
    agents_snapshot: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Returns either {"action": "answer_directly", "text": "..."} or
    {"action": "call_tool", "agent_id": "...", "tool_name": "...", "arguments": {...}}.
    Thin wrapper: builds single user message and calls decide_with_messages.
    """
    tools_json = json.dumps(agents_snapshot, indent=2)
    user = f"Available agents and tools:\n{tools_json}\n\nUser query: {query}"
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
    return await decide_with_messages(openai_client, model, messages)


SYNTHESIZE_SYSTEM = """You are a helpful assistant. The user asked a question and a tool was called. You are given the user's question, the tool name, and the tool's raw result (possibly JSON). Reply in one or two short sentences that directly answer the user. Do not repeat raw JSON; turn it into natural language. Be concise."""


async def synthesize_tool_result(
    openai_client: AsyncOpenAI,
    model: str,
    user_query: str,
    tool_name: str,
    tool_result: Any,
) -> str:
    """Turn a raw tool result into a short natural-language answer for the user."""
    result_str = json.dumps(tool_result, default=str) if not isinstance(tool_result, str) else tool_result
    if len(result_str) > 2000:
        result_str = result_str[:2000] + "..."
    user_msg = f"User asked: {user_query}\nTool called: {tool_name}\nTool result: {result_str}\n\nYour short answer:"
    resp = await openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYNTHESIZE_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip() or result_str
