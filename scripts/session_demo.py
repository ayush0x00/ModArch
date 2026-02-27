#!/usr/bin/env python3
"""Session demo: query agent that uses session_id for multi-turn conversation.
Demonstrates session management: first query starts a session, follow-ups send session_id
so the orchestrator has context (e.g. "what did I just ask?" or "and tomorrow?").

Starts the weather load_server (index 1); it self-registers with the master. Runs
queries, then stops the server. Requires: master running with Redis.
"""
import asyncio
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from protocol import QueryResult
from openagent import OrchestratorQueryAgent

# Weather app is load_server index 1.
WEATHER_SERVER_INDEX = 1
BASE_PORT = 9000

SESSION_DEMO_QUERIES = [
    "What's the weather in San Francisco?",
    "What did I just ask about?",
    "And what's the weather there tomorrow?",
    "Summarize what we've discussed so far.",
]

_server_proc: subprocess.Popen | None = None


def _wait_for_health(port: int, timeout_sec: float = 10) -> bool:
    deadline = time.perf_counter() + timeout_sec
    while time.perf_counter() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


async def main():
    global _server_proc
    # Start weather server; it self-registers with master (invocation-only, no WS process agents).
    _server_proc = subprocess.Popen(
        [sys.executable, "-m", "experiments.load_server", str(WEATHER_SERVER_INDEX)],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env={**os.environ, "OPENAGENT_INVOCATION_ONLY": "1"},
    )
    port = BASE_PORT + WEATHER_SERVER_INDEX
    print(f"Started weather server on port {port}. Waiting for health...")
    if not _wait_for_health(port):
        raise RuntimeError(f"Weather server did not become healthy on port {port}")
    print("Server healthy.")

    agent = None
    try:
        agent = OrchestratorQueryAgent("session-demo-query-agent")
        await agent.register()
        session_id: str | None = None
        for q in SESSION_DEMO_QUERIES:
            print(f"\nQuery: {q}")
            res = await agent.client.query(q, session_id=session_id)
            if isinstance(res, QueryResult):
                if res.session_id:
                    session_id = res.session_id
                    print(f"  Session: {session_id[:8]}...")
                if res.error:
                    print(f"  Error: {res.error}")
                else:
                    print(f"  Result: {res.result}")
            else:
                print(f"  Error: {getattr(res, 'message', res)}")
        print("\nDone.")
        if session_id:
            print(f"  Full session_id (for redis-cli): {session_id}")
    finally:
        if agent is not None:
            await agent.close()
        if _server_proc:
            _server_proc.terminate()
            try:
                _server_proc.wait(timeout=5)
            except Exception:
                _server_proc.kill()
            _server_proc = None
            print("Stopped weather server.")


if __name__ == "__main__":
    asyncio.run(main())
