# Example: Documentation Formatter on Solace Agent Mesh

A minimal end-to-end example showing how to host a compiled LangGraph as an
A2A agent on Solace Agent Mesh, using the `solace_agent_mesh_langgraph` wrapper from
this repo.

The graph itself (`agent.py`) is a single-node LangGraph that takes raw
technical notes and returns a structured Markdown document with three
sections: `## Summary`, `## Technical Details`, `## Action Items`.

## What's in this folder

| File              | Purpose                                                              |
| ----------------- | -------------------------------------------------------------------- |
| `agent.py`        | The LangGraph definition. Exposes a module-level `graph` (compiled, no checkpointer) for `langgraph dev` and a `DocumentationFormatterAgent` class that accepts an optional `checkpointer=` for deployment-time wrapping. |
| `main.py`         | Entry point for the SAM/A2A deployment path. Wraps the graph with `MemorySaver`, builds broker properties, runs the server. |
| `agent_card.json` | A2A agent card published on the discovery topic.                     |
| `Dockerfile`      | Builds a single image bundling wrapper + this agent. Built with `-f` from the repo root. |
| `langgraph.json`  | **Optional.** LangGraph CLI manifest — only used if you want to run / debug the graph in LangGraph Studio or LangSmith. Not used by the A2A Solace path. |
| `requirements.txt`| Re-exports the top-level `requirements.txt`.                         |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[examples]"
cp .env.example examples/doc_formatter/.env
# edit examples/doc_formatter/.env: fill in broker creds + OPENAI_API_KEY
cd examples/doc_formatter
python main.py
```

`main.py` composes the deployment-time graph — wrapping with `MemorySaver`
so the wrapper's `contextId → thread_id` mapping actually persists state
across A2A turns — and runs the server with graceful shutdown handling.
See [Conversation continuity](#conversation-continuity) below for what
goes in `main.py` and why.

> **TLS configuration only matters for `tcps://` URLs.**
> - **Plain `tcp://` broker** (e.g. a local Solace PubSub+ container):
>   no TLS settings needed at all. Just the four `SOLACE_BROKER_*` creds.
> - **`tcps://` broker, real deployment**: configure
>   `SOLACE_BROKER_TRUST_STORE_DIR` to point at a directory of CA certs.
> - **`tcps://` broker, quick sandbox demo**: skip the trust store by
>   setting `SOLACE_BROKER_VALIDATE_CERTS=false` in `.env`. **Never use
>   this in production** — it disables TLS's man-in-the-middle protection.

What you should see (in order):

1. `Initializing Documentation Formatter Agent...` — the graph compiles.
2. `Connected to Solace PubSub+ broker` — wrapper is connected.
3. `Queue '<random>' created and receiver started` — non-durable exclusive queue.
4. `A2A LangChain Server ready - agent=doc_formatter ...`
5. Every 3 seconds, an agent-card publish happens silently in the background.

Send a JSON-RPC `message/send` to
`<SAM_NAMESPACE>/a2a/v1/agent/request/doc_formatter` with a `replyTo` user
property set to a topic you're subscribed to, and you'll receive the formatted
Markdown back on that `replyTo`.

## Run it as a container

[`Dockerfile`](Dockerfile) in this folder bundles the wrapper + this example
agent into a single image. Useful for handing a runnable agent to someone
without a Python environment, or as a starting point for deploying to a
container platform. (Stage 3 of the deployability roadmap will split this
into a published base image + a thin extension Dockerfile; for now it's
one self-contained file.)

The build context must be the **repo root** so the Dockerfile can reach
`src/` and `pyproject.toml`. Build from there with the `-f` flag pointing
at this Dockerfile:

```bash
docker build -t doc-formatter:dev -f examples/doc_formatter/Dockerfile .
```

Minimal run — works for any plain `tcp://` broker (e.g. a local Solace
PubSub+ container):

```bash
docker run --rm \
  --env-file examples/doc_formatter/.env \
  doc-formatter:dev
```

For a `tcps://` broker, mount your trust-store directory and tell the
container where it landed:

```bash
docker run --rm \
  --env-file examples/doc_formatter/.env \
  -v ~/.solace-truststore:/certs:ro \
  -e SOLACE_BROKER_TRUST_STORE_DIR=/certs \
  doc-formatter:dev
```

What the extra `tcps://` flags do:

- `-v ~/.solace-truststore:/certs:ro` mounts your TLS trust-store directory
  from the host into the container at `/certs`. Your host path doesn't
  exist inside the container, so the bind-mount is necessary.
- `-e SOLACE_BROKER_TRUST_STORE_DIR=/certs` overrides whatever the `.env`
  says for the in-container path. Container env vars beat `--env-file`.

> **TLS configuration only matters for `tcps://` URLs.**
> - **Plain `tcp://` broker**: use the minimal `docker run` above. No TLS
>   settings to configure.
> - **`tcps://` broker, real deployment**: use the second command above
>   with `SOLACE_BROKER_TRUST_STORE_DIR` pointing at real CA certs.
> - **`tcps://` broker, quick sandbox demo**: set
>   `SOLACE_BROKER_VALIDATE_CERTS=false` in `.env` and the minimal
>   `docker run` works for `tcps://` too — no trust-store mount needed.
>   **Never use this in production** — it disables TLS's
>   man-in-the-middle protection.

### Gotchas

- **Local broker on macOS / Windows.** If `SOLACE_BROKER_URL=tcp://localhost:55555`
  in your `.env`, "localhost" inside the container means *the container
  itself*, not your host. Change the URL to
  `tcp://host.docker.internal:55555` (Docker Desktop / Podman Desktop). On
  Linux, add `--network=host` instead and keep `localhost`.
- **Podman is a drop-in replacement.** Substitute `podman` for `docker` in
  both commands — the flags are identical.
- **Quoted env values are fine.** The wrapper strips surrounding `"..."` or
  `'...'` from broker properties at load time, so it doesn't matter whether
  your `.env` quotes the values or not. (Docker/Podman's `--env-file` parser
  preserves quotes; python-dotenv strips them — the wrapper normalises both
  paths.)

## Test the graph in isolation (no broker needed)

Useful when iterating on the LangGraph itself:

```bash
python examples/doc_formatter/agent.py
```

This runs the built-in test in `agent.py:__main__` (sends a sample notes
blob through the graph and prints the formatted Markdown). It only needs
`OPENAI_API_KEY` — no Solace broker required.

## Optional: run the graph in LangGraph Studio / LangSmith

`langgraph.json` is included so you can load this graph in
[LangGraph Studio](https://langchain-ai.github.io/langgraph/cloud/quick_start/)
or trace it via [LangSmith](https://docs.smith.langchain.com/) — useful for
visualising state transitions, replaying turns, or inspecting tool calls
during development. **None of this is required to run the agent on Solace
Agent Mesh** — the A2A path (`python main.py`) ignores `langgraph.json` entirely.

The manifest declares:

```json
{
  "dependencies": ["."],
  "graphs": { "documentation_formatter": "./agent.py:graph" },
  "env": "../../.env",
  "python_version": "3.11"
}
```

- `graphs` exposes the compiled `graph` from `agent.py` under the name
  `documentation_formatter`.
- `env` points back at the repo-root `.env` (relative to this file), so the
  `OPENAI_API_KEY` you already configured is picked up automatically.

### Local Studio

```bash
pip install -U langgraph-cli
langgraph dev          # from examples/doc_formatter/
```

This starts the LangGraph dev server (Studio UI on http://localhost:8123 by
default) using your local Python environment. Trace data is sent to
LangSmith if `LANGCHAIN_API_KEY` / `LANGCHAIN_TRACING_V2=true` are set in
`.env`.

### Caveats

- The Studio path runs the graph **standalone**, not through Solace. It's
  for graph-iteration and tracing only.
- `dependencies: ["."]` tells the LangGraph CLI to install this directory.
  The local `requirements.txt` here just re-exports the top-level one
  (`-r ../../requirements.txt`); if the CLI in your environment doesn't
  follow `-r` references, replace the contents of
  `examples/doc_formatter/requirements.txt` with the explicit pins from
  the top-level file.

## Conversation continuity

The wrapper maps the A2A `contextId` of an incoming request to the
LangGraph `thread_id`, so two requests sharing the same `contextId` should
see each other's message history. But that mapping is only meaningful if
the compiled graph has a **checkpointer** — without one, every invocation
is stateless regardless of `thread_id`.

The example splits that decision across two files on purpose:

- [`agent.py`](agent.py) compiles a **stateless** module-level `graph` so
  `langgraph dev` (which rejects custom checkpointers) can load it. The
  `DocumentationFormatterAgent` class accepts an optional `checkpointer=`
  kwarg so deployment-time code can re-build the graph with persistence.
- [`main.py`](main.py) is where the deployment choice lives. It does:
  ```python
  from langgraph.checkpoint.memory import MemorySaver
  graph = DocumentationFormatterAgent(checkpointer=MemorySaver()).graph
  ```
  Swap `MemorySaver()` for whatever fits your deployment:

| Need | Pick |
| --- | --- |
| Quick A2A demo on one process | [`MemorySaver`](https://langchain-ai.github.io/langgraph/concepts/persistence/#memorysaver) — in-memory, process-local |
| Single host, durable | [`SqliteSaver`](https://langchain-ai.github.io/langgraph/concepts/persistence/#sqlitesaver) — file on disk |
| Multi-replica / shared state | [`PostgresSaver`](https://langchain-ai.github.io/langgraph/concepts/persistence/#postgressaver) |
| Running on LangGraph Platform | Don't add one — platform provides its own |

This split is why `main.py` exists alongside `agent.py`. `agent.py` is the
agent's *definition* — loadable as-is by `langgraph dev`. `main.py` is the
agent's *deployment* — re-wraps the graph with checkpointer (and any
other runtime concerns) before handing it to the server.

## Customising

- **System prompt / formatting rules**: edit `SYSTEM_PROMPT` in `agent.py`.
- **Model**: set `LLM_MODEL_NAME` in `.env` (default `gpt-4o`).
- **Agent name / discovery URL**: edit `agent_card.json`. The `name` field
  controls the request topic (`.../agent/request/<name>`), so renaming it
  changes what callers must address.
- **Checkpointer**: see [Conversation continuity](#conversation-continuity)
  above. Bundled example is stateless by default; pick a checkpointer for
  your own copy based on where you're deploying.
