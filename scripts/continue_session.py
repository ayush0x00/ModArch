#!/usr/bin/env python3
"""Query agent that continues an existing session. No server startup; master + agents must be running.

Usage:
  From repo root: python scripts/continue_session.py
  With args:      python scripts/continue_session.py "Q1" "Q2"
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol import QueryResult
from openagent import OrchestratorQueryAgent

# Continue from this existing session (loads prior turns from Redis).
SESSION_ID = "4c62a7a2-5092-4a6a-89a9-c1d469f6d2c0"

# Run these when no CLI args.
FOLLOW_QUERIES = [
    "What did we discuss earlier?",
    "What's the weather there tomorrow?",
    "Summarize our conversation in one sentence.",
]


async def main():
    agent = OrchestratorQueryAgent("continue-session-query-agent")
    await agent.register()
    try:
        if len(sys.argv) > 1:
            for q in sys.argv[1:]:
                print(f"\nQuery: {q}")
                res = await agent.client.query(q, session_id=SESSION_ID)
                if isinstance(res, QueryResult):
                    if res.error:
                        print(f"  Error: {res.error}")
                    else:
                        print(f"  Result: {res.result}")
                else:
                    print(f"  Error: {getattr(res, 'message', res)}")
        else:
            print(f"Session: {SESSION_ID}\n")
            for q in FOLLOW_QUERIES:
                print(f"Query: {q}")
                res = await agent.client.query(q, session_id=SESSION_ID)
                if isinstance(res, QueryResult):
                    if res.error:
                        print(f"  Error: {res.error}")
                    else:
                        print(f"  Result: {res.result}")
                else:
                    print(f"  Error: {getattr(res, 'message', res)}")
                print()
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
