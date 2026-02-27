#!/usr/bin/env python3
"""Run many queries in one session to trigger multiple summaries. Master logs will show [Context] building/summarizing."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol import QueryResult
from openagent import OrchestratorQueryAgent

QUERIES = [
    "What is the weather in San Francisco?",
    "What is the 3-day forecast for San Francisco?",
    "What is the air quality in San Francisco?",
    "What is the humidity in San Francisco?",
    "What is the wind like in San Francisco?",
    "What did I ask in my first question?",
    "What did I ask in my second question?",
    "Summarize everything we've discussed about San Francisco.",
]

async def main():
    agent = OrchestratorQueryAgent("summarizer-multi-test-agent")
    await agent.register()
    session_id = None
    try:
        for i, q in enumerate(QUERIES):
            print(f"\n[{i+1}] Q: {q}")
            res = await agent.client.query(q, session_id=session_id)
            if getattr(res, "session_id", None):
                session_id = res.session_id
            if type(res).__name__ == "QueryResult":
                print(f"    A: {res.result or res.error}")
            else:
                print(f"    A: {getattr(res, 'message', res)}")
        if session_id:
            print(f"\nSession ID: {session_id}")
    finally:
        await agent.close()

if __name__ == "__main__":
    asyncio.run(main())
