#!/usr/bin/env python3
"""Example query agent: sends a few queries and prints results. Uses OrchestratorQueryAgent.
Includes a long_task query to exercise progress (WS or invocation); watch master for progress lines."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol import QueryResult
from openagent import OrchestratorQueryAgent

DEMO_QUERIES = [
    "What's the weather in NYC?",
    "Hello!",
    "Weather in London?",
    "I need to echo back 'HELLLOOO WORLDDD !!!'",
    "Run a long task for 2 seconds and report progress",  # exercises progress (WS or invocation)
]


async def main():
    agent = OrchestratorQueryAgent("demo-query-agent")
    await agent.register()
    try:
        for q in DEMO_QUERIES:
            print(f"\nQuery: {q}")
            res = await agent.client.query(q)
            if isinstance(res, QueryResult):
                if res.error:
                    print(f"  Error: {res.error}")
                else:
                    print(f"  Result: {res.result}")
            else:
                print(f"  Error: {getattr(res, 'message', res)}")
        print("\nDone.")
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
