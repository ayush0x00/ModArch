#!/usr/bin/env python3
"""Example action agent: exposes get_weather tool. Uses OrchestratorActionAgent."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openagent import ToolSchema, OrchestratorActionAgent

TOOLS = [
    ToolSchema(
        name="get_weather",
        description="Get current weather for a city. Use when the user asks about weather.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    ),
    ToolSchema(
        name="long_task",
        description="Run a long-running task that reports progress. Use when the user asks to run a long task or test progress.",
        parameters={
            "type": "object",
            "properties": {"seconds": {"type": "number", "description": "How many seconds to run"}},
            "required": [],
        },
    ),
]


async def handle_tool(
    tool_name: str,
    arguments: dict,
    *,
    progress_callback=None,
) -> str | dict:
    print(f"[weather-agent] received tool_call: {tool_name}({arguments})")
    if tool_name == "get_weather":
        city = arguments.get("city", "unknown")
        print(f"[weather-agent] get_weather for city={city}")
        result = {"city": city, "temperature": 72, "unit": "F", "conditions": "sunny"}
        print(f"[weather-agent] returning: {result}")
        return result
    if tool_name == "long_task":
        seconds = float(arguments.get("seconds", 3))
        for i in range(int(seconds * 2) + 1):
            pct = min(100, int(100 * i / (seconds * 2)))
            if progress_callback:
                await progress_callback({"percent": pct, "message": f"WS progress {pct}%", "stage": "running"})
            await asyncio.sleep(0.5)
        if progress_callback:
            await progress_callback({"percent": 100, "message": "Done", "stage": "complete"})
        return {"status": "ok", "seconds": seconds, "agent": "weather-agent (WS)"}
    raise ValueError(f"Unknown tool: {tool_name}")


async def main():
    agent = OrchestratorActionAgent("weather-agent", TOOLS, handle_tool)
    await agent.register()
    try:
        await agent.run()
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
