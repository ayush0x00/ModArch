"""Abstract base for agents that connect to the orchestrator. Enforces the contract for registration."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Literal

from protocol import ToolSchema

from .client import (
    AgentClient,
    register_invocation_agent as _register_invocation_agent,
)


class OrchestratorAgent(ABC):
    """Abstract base. Subclass and implement required members to use the orchestrator."""

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Unique id for this agent. Required."""
        ...

    @property
    @abstractmethod
    def agent_type(self) -> Literal["query", "action"]:
        """'query' = sends queries to master; 'action' = receives tool calls."""
        ...

    def get_tools(self) -> list[ToolSchema]:
        """Tools this agent exposes. Required for action agents; default []."""
        return []

    def get_metadata(self) -> dict[str, Any]:
        """Optional metadata sent to master on register."""
        return {}

    @abstractmethod
    async def register(
        self,
        *,
        master_url: str | None = None,
        master_base_url: str | None = None,
    ) -> None:
        """Register with the orchestrator. Must connect (WS or HTTP) and complete registration."""
        ...


class OrchestratorQueryAgent(OrchestratorAgent):
    """Query agent: connects via WebSocket, registers, then you use .client to run queries."""

    agent_type: Literal["query"] = "query"

    def __init__(
        self,
        agent_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ):
        self._agent_id = agent_id
        self._metadata = metadata or {}

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_type(self) -> Literal["query"]:
        return "query"

    def get_metadata(self) -> dict[str, Any]:
        return self._metadata

    async def register(
        self,
        *,
        master_url: str | None = None,
        master_base_url: str | None = None,
    ) -> None:
        from .client import _resolve_master_url
        url = _resolve_master_url(master_url)
        self._client = AgentClient(
            master_url=url,
            agent_id=self._agent_id,
            agent_type="query",
            metadata=self._metadata,
        )
        await self._client.connect()

    @property
    def client(self) -> AgentClient:
        """After register(), use this to run client.query(...)."""
        return self._client

    async def close(self) -> None:
        """Close WebSocket. Call when done querying."""
        if hasattr(self, "_client"):
            await self._client.close()


class OrchestratorActionAgent(OrchestratorAgent):
    """Action agent over WebSocket: connects, registers, handles tool calls. Runs until close()."""

    agent_type: Literal["action"] = "action"

    def __init__(
        self,
        agent_id: str,
        tools: list[ToolSchema],
        tool_handler: Callable[[str, dict[str, Any]], Awaitable[Any]],
        *,
        metadata: dict[str, Any] | None = None,
        invocation_url: str | None = None,
    ):
        self._agent_id = agent_id
        self._tools = tools
        self._tool_handler = tool_handler
        self._metadata = metadata or {}
        self._invocation_url = invocation_url

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_type(self) -> Literal["action"]:
        return "action"

    def get_tools(self) -> list[ToolSchema]:
        return self._tools

    def get_metadata(self) -> dict[str, Any]:
        return self._metadata

    async def register(
        self,
        *,
        master_url: str | None = None,
        master_base_url: str | None = None,
    ) -> None:
        from .client import _resolve_master_url
        url = _resolve_master_url(master_url)
        self._client = AgentClient(
            master_url=url,
            agent_id=self._agent_id,
            agent_type="action",
            tools=self._tools,
            tool_handler=self._tool_handler,
            metadata=self._metadata,
            invocation_url=self._invocation_url,
        )
        await self._client.connect()
        self._recv_task = self._client._recv_task

    async def run(self) -> None:
        """Run the action agent (handle tool calls) until cancelled. Call after register()."""
        if not hasattr(self, "_client"):
            raise RuntimeError("Call register() before run()")
        try:
            if self._client._recv_task:
                await self._client._recv_task
        finally:
            await self._client.close()

    async def close(self) -> None:
        if hasattr(self, "_client"):
            if getattr(self, "_recv_task", None) and not self._recv_task.done():
                self._recv_task.cancel()
                try:
                    await self._recv_task
                except Exception:
                    pass
            await self._client.close()


class OrchestratorInvocationAgent(OrchestratorAgent):
    """Action agent via HTTP: registers invocation URL with master. No WebSocket."""

    agent_type: Literal["action"] = "action"

    def __init__(
        self,
        agent_id: str,
        tools: list[ToolSchema],
        invocation_base_url: str,
        *,
        metadata: dict[str, Any] | None = None,
    ):
        self._agent_id = agent_id
        self._tools = tools
        self._invocation_base_url = invocation_base_url.rstrip("/")
        self._metadata = metadata or {}

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_type(self) -> Literal["action"]:
        return "action"

    def get_tools(self) -> list[ToolSchema]:
        return self._tools

    def get_metadata(self) -> dict[str, Any]:
        return self._metadata

    async def register(
        self,
        *,
        master_url: str | None = None,
        master_base_url: str | None = None,
    ) -> None:
        await _register_invocation_agent(
            self._agent_id,
            self._tools,
            self._invocation_base_url,
            master_base_url=master_base_url,
            metadata=self._metadata,
        )
