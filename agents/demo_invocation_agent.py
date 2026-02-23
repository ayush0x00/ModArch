#!/usr/bin/env python3
"""Demo action agent: HTTP server only. Registers invocation URL with master once (Redis). No WebSocket."""
import asyncio
import sys
import threading
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import uvicorn
from fastapi import FastAPI, Request

import config
from openagent import ToolSchema, OrchestratorInvocationAgent

TOOLS = [
    ToolSchema(
        name="echo",
        description="Echo back a message. Use when the user wants to repeat or echo something.",
        parameters={
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Message to echo back"}},
            "required": ["message"],
        },
        endpoint="/run",
    ),
    ToolSchema(
        name="get_time",
        description="Get the current time. Use when the user asks for the time.",
        parameters={
            "type": "object",
            "properties": {"timezone": {"type": "string", "description": "Timezone, e.g. UTC or America/New_York"}},
            "required": [],
        },
        endpoint="/get_time",
    ),
    ToolSchema(
        name="long_task",
        description="Run a long-running task that reports progress. Use when the user asks to run a long task or test progress.",
        parameters={
            "type": "object",
            "properties": {"seconds": {"type": "number", "description": "How many seconds to run"}},
            "required": [],
        },
        endpoint="/long_task",
    ),
]


async def handle_tool(
    tool_name: str,
    arguments: dict,
    *,
    progress_callback_url: str | None = None,
    call_id: str | None = None,
) -> str | dict:
    print(f"[demo-invocation-agent] tool_call: {tool_name}({arguments})")
    if tool_name == "echo":
        msg = arguments.get("message", "")
        return {"echo": msg}
    if tool_name == "get_time":
        tz = arguments.get("timezone") or "UTC"
        now = datetime.now(timezone.utc)
        return {"time": now.isoformat(), "timezone": tz}
    if tool_name == "long_task":
        seconds = float(arguments.get("seconds", 3))
        for i in range(int(seconds * 2) + 1):
            pct = min(100, int(100 * i / (seconds * 2)))
            if progress_callback_url and call_id:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        progress_callback_url,
                        json={
                            "call_id": call_id,
                            "progress": {"percent": pct, "message": f"Invocation progress {pct}%", "stage": "running"},
                        },
                        timeout=5.0,
                    )
            await asyncio.sleep(0.5)
        if progress_callback_url and call_id:
            async with httpx.AsyncClient() as client:
                await client.post(
                    progress_callback_url,
                    json={"call_id": call_id, "progress": {"percent": 100, "message": "Done", "stage": "complete"}},
                    timeout=5.0,
                )
        return {"status": "ok", "seconds": seconds, "agent": "demo-invocation-agent (HTTP)"}
    raise ValueError(f"Unknown tool: {tool_name}")


app = FastAPI(title="Demo Invocation Agent")


@app.get("/health")
def health():
    """Health check for master. Master calls GET {invocation_base_url}/health to see if agent is UP."""
    return {"status": "ok"}


async def _run_impl(request: Request):
    body = await request.json()
    call_id = body.get("call_id")
    tool_name = body.get("tool_name")
    arguments = body.get("arguments", {})
    callback_url = body.get("callback_url")
    progress_callback_url = body.get("progress_callback_url")
    if not call_id or not tool_name or not callback_url:
        return {"ok": False, "error": "call_id, tool_name, callback_url required"}
    try:
        result = await handle_tool(
            tool_name,
            arguments,
            progress_callback_url=progress_callback_url,
            call_id=call_id,
        )
        payload = {"call_id": call_id, "success": True, "result": result}
    except Exception as e:
        payload = {"call_id": call_id, "success": False, "error": str(e)}
    async with httpx.AsyncClient() as client:
        await client.post(callback_url, json=payload, timeout=10.0)
    return {"ok": True}


@app.post("/run")
async def run(request: Request):
    return await _run_impl(request)


@app.post("/get_time")
async def get_time(request: Request):
    return await _run_impl(request)


@app.post("/long_task")
async def long_task(request: Request):
    return await _run_impl(request)


def _run_server():
    uvicorn.run(app, host=config.INVOCATION_HOST, port=config.INVOCATION_PORT, log_level="warning")


async def main():
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()
    await asyncio.sleep(0.5)  # let server bind
    print(f"Invocation base: {config.INVOCATION_BASE_URL} (tools: /run, /get_time)")
    agent = OrchestratorInvocationAgent(
        "demo-invocation-agent",
        TOOLS,
        config.INVOCATION_BASE_URL,
    )
    print("Registering with master (HTTP, Redis)...")
    await agent.register()
    print("Registered. Server running; master will invoke via URL. Ctrl+C to stop.")
    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down.")
