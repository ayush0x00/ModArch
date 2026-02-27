"""Build orchestrator messages from session turns; token counting and summarization for long context."""
from __future__ import annotations

import json
from typing import Any

import config

# Encoding used by gpt-4o-mini and most recent OpenAI models
_TIKTOK_ENCODING: Any = None


def _get_encoding() -> Any:
    global _TIKTOK_ENCODING
    if _TIKTOK_ENCODING is None:
        import tiktoken
        _TIKTOK_ENCODING = tiktoken.get_encoding("cl100k_base")
    return _TIKTOK_ENCODING


def count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text))


def count_messages_tokens(messages: list[dict[str, str]]) -> int:
    """Count tokens for OpenAI-style messages (role + content)."""
    total = 0
    for m in messages:
        total += 4  # overhead per message
        total += count_tokens((m.get("role") or "") + (m.get("content") or ""))
    return total


def _turn_to_messages(turn: dict[str, Any]) -> list[dict[str, str]]:
    """Convert one session turn to user/assistant message pair. Skips summary turns (caller handles those)."""
    if turn.get("decision") == "summary":
        return []
    out: list[dict[str, str]] = []
    query = turn.get("query") or ""
    out.append({"role": "user", "content": query})
    decision = turn.get("decision") or "answer_directly"
    if decision == "answer_directly":
        result = turn.get("result") or turn.get("error") or ""
        text = result if isinstance(result, str) else json.dumps(result)
        out.append({"role": "assistant", "content": f"Answered: {text}"})
    else:
        agent_id = turn.get("tool_agent_id") or ""
        tool_name = turn.get("tool_name") or ""
        result = turn.get("result")
        err = turn.get("error")
        if err:
            out.append({"role": "assistant", "content": f"Called tool {agent_id}.{tool_name} -> error: {err}"})
        else:
            text = result if isinstance(result, str) else json.dumps(result) if result is not None else ""
            out.append({"role": "assistant", "content": f"Called tool {agent_id}.{tool_name} -> {text}"})
    return out


async def _summarize_turns(
    openai_client: Any,
    model: str,
    turns: list[dict[str, Any]],
) -> str:
    """Summarize a list of turns into a short paragraph for context."""
    if not turns:
        return ""
    parts = []
    for t in turns:
        q = t.get("query") or ""
        decision = t.get("decision") or "answer_directly"
        if decision == "summary":
            parts.append(f"Summary: {t.get('summary', '')}")
        elif decision == "answer_directly":
            r = t.get("result") or t.get("error") or ""
            parts.append(f"User: {q}\nAssistant: {r}")
        else:
            an = t.get("tool_agent_id") or ""
            tn = t.get("tool_name") or ""
            r = t.get("result") or t.get("error") or ""
            parts.append(f"User: {q}\nAssistant: Called {an}.{tn} -> {r}")
    conversation = "\n\n".join(parts)
    prompt = (
        "Summarize this conversation between user and assistant (queries, tool calls, results) "
        "in one short paragraph. Preserve key facts and outcomes."
    )
    resp = await openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": conversation},
        ],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


def build_orchestrator_messages(
    turns: list[dict[str, Any]],
    new_query: str,
    agents_snapshot: list[dict[str, Any]],
    max_tokens: int,
    system_prompt: str,
) -> list[dict[str, str]]:
    """
    Build full message list for the orchestrator (system + optional summary + history + tools + new query).
    No summarization (sync, no LLM). For long context use build_orchestrator_messages_async.
    """
    tools_json = json.dumps(agents_snapshot, indent=2)
    final_user = f"Available agents and tools:\n{tools_json}\n\nUser query: {new_query}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for t in turns:
        messages.extend(_turn_to_messages(t))
    messages.append({"role": "user", "content": final_user})

    return messages


async def build_orchestrator_messages_async(
    turns: list[dict[str, Any]],
    new_query: str,
    agents_snapshot: list[dict[str, Any]],
    max_tokens: int,
    system_prompt: str,
    *,
    openai_client: Any = None,
) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    """
    Build orchestrator messages from session: all previous summaries + all raw turns after last summary.
    If over max_tokens, summarize some of the tail, persist a summary turn, and return it for the caller to append.
    Returns (messages, summary_turn_to_append or None).
    """
    recent_n = getattr(config, "ORCHESTRATOR_RECENT_TURNS", 8)
    summarizer_model = getattr(config, "SUMMARIZER_MODEL", None) or getattr(config, "ORCHESTRATOR_MODEL", "gpt-4o-mini")

    tools_json = json.dumps(agents_snapshot, indent=2)
    final_user = f"Available agents and tools:\n{tools_json}\n\nUser query: {new_query}"

    def is_summary(t: dict[str, Any]) -> bool:
        return t.get("decision") == "summary"

    # Summary turns in order; last summary's covers_through_index (-1 if none)
    summary_turns = [(i, t) for i, t in enumerate(turns) if is_summary(t)]
    last_summary_covers = max(t.get("covers_through_index", -1) for _, t in summary_turns) if summary_turns else -1

    # Raw turns after last summary (index > last_summary_covers, and not a summary turn)
    raw_after_last_summary = [(i, t) for i, t in enumerate(turns) if not is_summary(t) and i > last_summary_covers]

    # Build messages: system + all summary contents + raw turns after last summary + final user
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for _, st in summary_turns:
        summary_text = st.get("summary") or ""
        if summary_text:
            messages.append({"role": "user", "content": f"Previous conversation (summary): {summary_text}"})
            messages.append({"role": "assistant", "content": "(Summary above.)"})
    for _, t in raw_after_last_summary:
        messages.extend(_turn_to_messages(t))
    messages.append({"role": "user", "content": final_user})

    total = count_messages_tokens(messages)
    if total <= max_tokens or not turns:
        return (messages, None)

    # Over limit: summarize part of raw_after_last_summary, keep recent_n
    raw_list = [t for _, t in raw_after_last_summary]
    older_raw = raw_list[:-recent_n] if len(raw_list) > recent_n else []
    recent_raw = raw_list[-recent_n:] if len(raw_list) > recent_n else raw_list

    if not older_raw or not openai_client:
        # Fallback: truncate oldest raw turns until under limit
        for drop in range(1, len(raw_after_last_summary) + 1):
            truncated_raw = raw_after_last_summary[drop:]
            msgs = [{"role": "system", "content": system_prompt}]
            for _, st in summary_turns:
                summary_text = st.get("summary") or ""
                if summary_text:
                    msgs.append({"role": "user", "content": f"Previous conversation (summary): {summary_text}"})
                    msgs.append({"role": "assistant", "content": "(Summary above.)"})
            for _, t in truncated_raw:
                msgs.extend(_turn_to_messages(t))
            msgs.append({"role": "user", "content": final_user})
            if count_messages_tokens(msgs) <= max_tokens:
                return (msgs, None)
        return (messages, None)

    summary_text = await _summarize_turns(openai_client, summarizer_model, older_raw)
    # covers_through_index = index in full turns list of the last turn we're summarizing
    last_covered_index = raw_after_last_summary[len(older_raw) - 1][0]
    summary_turn: dict[str, Any] = {
        "decision": "summary",
        "summary": summary_text,
        "covers_through_index": last_covered_index,
        "ts": None,
    }

    # Build messages for this request: all summaries (including new) + recent raw
    messages = [{"role": "system", "content": system_prompt}]
    for _, st in summary_turns:
        s = st.get("summary") or ""
        if s:
            messages.append({"role": "user", "content": f"Previous conversation (summary): {s}"})
            messages.append({"role": "assistant", "content": "(Summary above.)"})
    if summary_text:
        messages.append({"role": "user", "content": f"Previous conversation (summary): {summary_text}"})
        messages.append({"role": "assistant", "content": "(Summary above.)"})
    for t in recent_raw:
        messages.extend(_turn_to_messages(t))
    messages.append({"role": "user", "content": final_user})

    return (messages, summary_turn)
