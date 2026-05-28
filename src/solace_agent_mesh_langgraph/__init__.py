# SPDX-License-Identifier: Apache-2.0
"""
solace_agent_mesh_langgraph — host a compiled LangGraph as a Solace Agent Mesh A2A agent.

Typical use:

    from solace_agent_mesh_langgraph import A2ALangchainServer

    server = A2ALangchainServer(graph, broker_properties, agent_card)
    await server.start()
"""

from .adapter import (
    AgentExecutor,
    EventQueue,
    LangChainA2AAdapter,
    RequestContext,
    Task,
    new_agent_text_message,
)
from .config import broker_properties_from_env, env_str
from .server import A2ALangchainServer

__all__ = [
    "A2ALangchainServer",
    "LangChainA2AAdapter",
    "AgentExecutor",
    "Task",
    "RequestContext",
    "EventQueue",
    "new_agent_text_message",
    "broker_properties_from_env",
    "env_str",
]

__version__ = "0.1.0"
