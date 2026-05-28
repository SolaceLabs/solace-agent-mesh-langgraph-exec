"""
Template deployment script for hosting a LangGraph on Solace Agent Mesh.

Copy this file next to your agent.py + agent_card.json and edit the TODO
markers below. This is where deployment concerns live:

  - The checkpointer choice (MemorySaver / SqliteSaver / PostgresSaver) so
    the wrapper's contextId → thread_id mapping actually retains state.
  - Custom broker properties beyond what `broker_properties_from_env()`
    builds (TLS client certs, OAuth, Kerberos, etc).
  - Per-environment runtime config (e.g. different checkpointer in dev vs
    prod) without touching agent.py.
  - Custom logging, observability hooks, startup tasks.

Run with:

    python main.py
"""

import asyncio
import json
import logging
import os
import signal
from pathlib import Path

from dotenv import load_dotenv

from solace_agent_mesh_langgraph import A2ALangchainServer, broker_properties_from_env, env_str

# Use solace_agent_mesh_langgraph.env_str() (re-exported above) instead of os.getenv()
# anywhere you read env vars that might come from .env. python-dotenv strips
# surrounding quotes on load; Docker/Podman --env-file does not. env_str
# normalises both paths so the same .env file works under `python main.py`
# AND inside `docker run --env-file ...`. Naked os.getenv() reads will leak
# literal `"..."` characters into the value inside containers — a footgun.

# TODO: import your agent. The factory pattern below assumes a class with a
# `checkpointer=` kwarg and a `.graph` attribute, like the doc_formatter
# example. Adapt to whatever your agent.py exposes.
# from agent import MyAgent

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_graph():
    """Compose the deployment-time graph.

    Returns:
        A compiled LangGraph ready to hand to A2ALangchainServer.
    """
    # TODO: Replace this with your own graph construction.
    #
    # Example (with persistence):
    #   from langgraph.checkpoint.memory import MemorySaver
    #   return MyAgent(checkpointer=MemorySaver()).graph
    #
    # Example (stateless):
    #   return MyAgent().graph
    raise NotImplementedError("Replace this with your agent's graph builder")


def load_agent_card() -> dict:
    with open(Path(__file__).with_name("agent_card.json"), "r", encoding="utf-8") as f:
        return json.load(f)


async def run() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    server = A2ALangchainServer(
        langgraph_app=build_graph(),
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
