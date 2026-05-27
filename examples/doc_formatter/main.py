"""
Deployment script for hosting the Documentation Formatter on Solace Agent Mesh.

Run with:

    python main.py

This file is where deployment concerns live: it imports the LangGraph from
agent.py, wraps it with a MemorySaver checkpointer (so the wrapper's
contextId → thread_id mapping actually retains state across A2A turns),
builds broker properties from env, loads the agent card, and starts the
server with graceful shutdown handling.

Other things that belong here in real deployments: non-basic-auth broker
properties (TLS client certs, OAuth, Kerberos), custom logging,
observability hooks, per-environment config.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

# Make src/ importable when running from a repo checkout without
# `pip install -e .`. Safe no-op when the package is already installed
# (e.g. inside the container, where /app has no `src/` sibling).
_parents = Path(__file__).resolve().parents
if len(_parents) > 2:
    _src_dir = _parents[2] / "src"
    if _src_dir.is_dir() and str(_src_dir) not in sys.path:
        sys.path.insert(0, str(_src_dir))

from sam_langgraph_a2a import A2ALangchainServer, broker_properties_from_env
from agent import DocumentationFormatterAgent

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("doc_formatter")


def load_agent_card() -> dict:
    with open(Path(__file__).with_name("agent_card.json"), "r", encoding="utf-8") as f:
        return json.load(f)


async def run() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    # Compose the deployment-time graph: a process-local checkpointer that
    # makes the wrapper's contextId → thread_id mapping persist state across
    # A2A turns. Swap for SqliteSaver (file-backed) or PostgresSaver (shared,
    # durable) when you outgrow MemorySaver. Leave it unset for a stateless
    # deployment.
    graph = DocumentationFormatterAgent(checkpointer=MemorySaver()).graph

    server = A2ALangchainServer(
        langgraph_app=graph,
        broker_properties=broker_properties_from_env(),
        agent_card=load_agent_card(),
    )

    # Graceful shutdown on SIGINT / SIGTERM.
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, _request_stop)

    server_task = asyncio.create_task(server.start(), name="a2a-server")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop-signal")

    try:
        done, _ = await asyncio.wait(
            {server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if server_task in done:
            server_task.result()
    finally:
        await server.stop()
        if not server_task.done():
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):
                pass
        if not stop_task.done():
            stop_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
