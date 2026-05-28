# LangGraph A2A Executor for Solace Agent Mesh
This project provides the capability to run a compiled [LangGraph](https://langchain-ai.github.io/langgraph/) as an [A2A](https://github.com/google/A2A) agent on
[Solace Agent Mesh](https://solace.com/products/agent-mesh/) (SAM).

The `solace_agent_mesh_langgraph` package binds a LangGraph application to a Solace
PubSub+ broker: it creates a queue, subscribes to the standard A2A topics
(`{namespace}/a2a/v1/agent/request/{name}` and friends), periodically publishes
the agent card on the discovery topic, and dispatches incoming JSON-RPC
requests through the graph — streaming each AIMessage back to the requester's
`replyTo` topic as an A2A event.

## Requirements

What you need to satisfy to use the wrapper:

- **Python ≥ 3.11.** Set in [pyproject.toml](pyproject.toml).
- **A reachable Solace broker.** The server fails fast at
  `messaging_service.connect()` if no broker is reachable. There is no
  embedded broker and no offline mode.
- **LangGraph contract.** The graph must be **compiled**, its state must
  contain a `messages` key (e.g. `MessagesState`), and it must support
  `astream(..., stream_mode="values")`. Only the latest `AIMessage.content`
  (as a string) is forwarded per chunk — tool calls and structured outputs
  are not surfaced separately.

## Constraints

Limitations of the current implementation. Worth knowing before you wire
this into anything real:

- **Basic authentication to Solace broker only.**
  `broker_properties_from_env()` in
  [src/solace_agent_mesh_langgraph/config.py](src/solace_agent_mesh_langgraph/config.py)
  builds `solace.messaging.authentication.scheme.basic.username` /
  `…password` from env vars. TLS client certificates, OAuth, and Kerberos
  are *not* yet available.
- **Non-durable exclusive queue.** The queue is created when the agent
  connects and disappears when it disconnects — requests sent while the
  agent is offline are not buffered. Auto-acknowledgement is on, so a
  crash mid-execution will *not* re-deliver the in-flight message.
- **Single agent per process.** One `A2ALangchainServer` instance hosts
  exactly one agent card/instance. Run multiple processes for multiple agents.
- **JSON-RPC methods supported: `message/send` and `message/stream` only.**
  Other methods are logged and ignored — no proper JSON-RPC error reply is
  returned today.
- **A2A text parts only.** Incoming `parts` with `kind != "text"` are
  ignored, and responses always carry a single text part. Binary, data,
  and file parts are not handled.
  *Handling files in-message and via reference is planned.*
- **Conversation continuity requires a checkpointed graph.** The server
  maps the A2A `contextId` from the incoming request onto the LangGraph
  `thread_id` (falling back to a fresh UUID if the caller didn't supply
  one), so repeat callers using the same `contextId` will hit the same
  thread. State is retained only if the graph is compiled with a
  checkpointer (e.g. `MemorySaver`, `SqliteSaver`, `PostgresSaver`). Note
  that `langgraph dev` / LangGraph Platform *reject* custom checkpointers.
  In the `examples/doc_formatter/` instance, the checkpointer is specified
  in `main.py`, outside of the graph code.
- **Agent-card discovery interval is hard-coded** at 3 seconds on
  `<namespace>/a2a/v1/discovery/agentcards`. Not currently configurable.

## Layout

```
.
├── src/solace_agent_mesh_langgraph/   # reusable wrapper package
│   ├── adapter.py           # LangChainA2AAdapter (graph -> A2A events)
│   ├── server.py            # A2ALangchainServer (broker + dispatch loop)
│   └── config.py            # broker_properties_from_env() helper
├── examples/
│   └── doc_formatter/       # runnable example
│       ├── agent.py         # the LangGraph (Documentation Formatter)
│       ├── main.py          # canonical entry point — wraps graph w/ MemorySaver
│       ├── agent_card.json  # filled-in A2A card for this example
│       ├── Dockerfile       # bundles wrapper + this agent into one image
│       └── langgraph.json   # filled-in LangGraph CLI manifest
├── templates/               # blank scaffolds to copy when adding your own agent
│   ├── agent_card.json
│   ├── langgraph.json
│   └── main.py              # deployment-script template with TODO markers
├── LICENSE
├── NOTICE
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[examples]"
```

This installs the wrapper in editable mode plus the `langchain-openai`
extra that the bundled example agent needs. Drop the `[examples]` extra if
you only want the wrapper itself (e.g. you're bringing your own agent and
just want to `import solace_agent_mesh_langgraph`).

A plain `pip install -r requirements.txt` works for a strict-dependency
install if you don't need editable mode.

## Configure

```bash
cp .env.example .env
```

Then fill in:

Variable names follow the **Solace Agent Mesh (SAM) convention** — drop in
your existing SAM `.env` settings for the Solace connection and LLM settings and it should work.

| Variable                                          | Purpose                                              |
| ------------------------------------------------- | ---------------------------------------------------- |
| `SOLACE_BROKER_URL`                               | Broker URL, e.g. `tcp://localhost:55555` or `tcps://…:55443` |
| `SOLACE_BROKER_VPN`                               | Message VPN name                                     |
| `SOLACE_BROKER_USERNAME` / `SOLACE_BROKER_PASSWORD` | Basic auth credentials                             |
| `SOLACE_BROKER_TRUST_STORE_DIR`                   | *(TLS only)* Directory of PEM/DER CA certs. Required for `tcps://` on macOS. See [.env.example](.env.example) for the `certifi` recipe. |
| `SOLACE_BROKER_VALIDATE_CERTS`                    | *(TLS only)* `true` (default) or `false`. Set `false` for dev/testing — disables MITM protection. |
| `SAM_NAMESPACE`                                   | A2A namespace (topic prefix), default `sam-demo`     |
| `OPENAI_API_KEY`                                  | Required by the example agent                        |
| `LLM_MODEL_NAME`                                  | Optional, defaults to `gpt-4o`                       |
| `LANGSMITH_TRACING`                               | *(LangSmith, optional)* Set to `true` to send traces to LangSmith. Picked up automatically by langchain/langgraph — no code changes needed. |
| `LANGSMITH_ENDPOINT`                              | *(LangSmith, optional)* Custom endpoint if not using LangSmith SaaS. Defaults to `https://api.smith.langchain.com`. |
| `LANGSMITH_API_KEY`                               | *(LangSmith, optional)* Required when `LANGSMITH_TRACING=true`. |
| `LANGSMITH_PROJECT`                               | *(LangSmith, optional)* Project name traces are attributed to in the LangSmith UI. |

## Run the example

**To simply run the example from a command line using the installed executor:**
```bash
cd examples/doc_formatter
python main.py
```

You should see the server connect, create a temporary queue, and start
publishing the agent card every 3 seconds on
`<namespace>/a2a/v1/discovery/agentcards`. The agent will respond to JSON-RPC
`message/send` and `message/stream` requests on
`<namespace>/a2a/v1/agent/request/doc_formatter`, publishing replies to the
caller's `replyTo` topic.

[`main.py`](examples/doc_formatter/main.py) wraps the bare `graph` from
[`agent.py`](examples/doc_formatter/agent.py) with `MemorySaver` so the
wrapper's `contextId → thread_id` mapping actually retains state across
A2A turns, then runs the server with graceful shutdown handling. It loads
`./.env` and `./agent_card.json` automatically from its own directory.

**Or run it as a container.** The example folder includes a
[`Dockerfile`](examples/doc_formatter/Dockerfile) that bundles the wrapper
+ this agent into a single image. Build from the repo root, then run:

```bash
docker build -t doc-formatter:dev -f examples/doc_formatter/Dockerfile .
docker run --rm --env-file examples/doc_formatter/.env doc-formatter:dev
```

For a `tcps://` broker, add `-v ~/.solace-truststore:/certs:ro
-e SOLACE_BROKER_TRUST_STORE_DIR=/certs` to the `docker run`. See
[examples/doc_formatter/README.md](examples/doc_formatter/README.md#run-it-as-a-container)
for the full container recipe (gotchas: macOS host networking, podman
equivalence, quoted env values).

> **TLS configuration only matters for `tcps://` URLs (CLI *and* container).**
> - **Plain `tcp://` broker** — e.g. a local Solace PubSub+ container —
>   needs no TLS settings at all.
> - **`tcps://` broker** — configure `SOLACE_BROKER_TRUST_STORE_DIR`
>   per [Configure](#configure) above.
> - **`tcps://` sandbox/demo only** — set
>   `SOLACE_BROKER_VALIDATE_CERTS=false` in `.env` to skip the trust store
>   entirely (the container can also drop the `-v` / `-e` flags). **Never
>   use this in production** — it disables TLS's man-in-the-middle
>   protection.

## Host your own LangGraph

Start by gathering the four files every agent needs in a directory:

1. **`agent.py`** — your LangGraph definition. Exports a compiled `graph`
   at module scope (for `langgraph dev` / Studio):
   ```python
   from langgraph.graph import StateGraph, MessagesState, START, END
   # ... build your workflow ...
   graph = workflow.compile(name="my_agent")  # name drives the LangSmith trace label
   ```
   The `name=` argument matters for **LangSmith** observability: without it, every
   run shows up with the name `"LangGraph"`. Note that `langgraph.json`'s
   `graphs.<name>` mapping does *not* propagate to the trace label when
   you run via `python main.py` or the container — `langgraph.json` is
   only read by `langgraph dev` / LangGraph Platform. Keep the string in
   both places identical so traces match across both run paths.
2. **`agent_card.json`** — copy [templates/agent_card.json](templates/agent_card.json)
   and fill in the placeholders.
3. **`.env`** — copy [.env.example](.env.example) and fill in broker
   credentials (plus any keys your graph needs, e.g. `OPENAI_API_KEY`).
4. **`main.py`** — copy [templates/main.py](templates/main.py) and fill in
   the TODO markers. This is where deployment concerns live: which
   checkpointer to use, custom broker properties beyond
   `broker_properties_from_env()`, per-environment config, logging.

Run with:

```bash
python main.py
```

This pattern keeps the agent's *definition* (`agent.py`) separate from
its *deployment* (`main.py`). `agent.py` stays loadable by `langgraph dev`;
`main.py` re-wraps the graph with runtime concerns for the SAM/A2A path.

See [Requirements](#requirements) above for the contract your graph and
broker config must satisfy, and [Constraints](#constraints) for the
behavioural limits you'll want to be aware of.

### Reading env vars: use `env_str`, not `os.getenv`

Anywhere your `agent.py` or `main.py` reads an env var that might come
from `.env`, use `solace_agent_mesh_langgraph.env_str` instead of `os.getenv`:

```python
from solace_agent_mesh_langgraph import env_str

api_key = env_str("OPENAI_API_KEY")          # like os.getenv, but quote-safe
model = env_str("LLM_MODEL_NAME", "gpt-4o")  # default works the same way
```

Why: **python-dotenv strips surrounding `"..."` and `'...'` from values on
load. Docker / Podman's `--env-file` does not.** A `.env` line like
`OPENAI_BASE_URL="https://api.openai.com/v1"` produces a clean URL when
loaded via the dotenv path, but inside a container it produces a URL with
literal `"` characters that fails at the first HTTP request. `env_str()`
strips surrounding straight quotes at the boundary so the same `.env`
behaves identically across both loaders. Signature mirrors `os.getenv`
(unset → returns `default`, defaulting to `None`).

`broker_properties_from_env()` already uses `env_str` internally, so the
broker connection is normalised whether you use the helper directly or
not — this guidance is for any *other* env vars your code reads.

## Configuration files

Three artefacts can ship alongside an agent — one is required, two are
optional, all three have copy-ready scaffolds in [templates/](templates/)
and filled-in examples in [examples/doc_formatter/](examples/doc_formatter/).

### `agent_card.json` — A2A discovery metadata

This is the agent's identity on the mesh. The wrapper's
`A2ALangchainServer` publishes it every 3 seconds on
`<namespace>/a2a/v1/discovery/agentcards` so other agents and gateways can
find it. Your `main.py` reads this file and passes the parsed dict into
the server constructor.

Field reference (template at [templates/agent_card.json](templates/agent_card.json)):

| Field | Required | Notes |
| --- | --- | --- |
| `name` | yes | Used as the agent identifier in topics: `<namespace>/a2a/v1/agent/request/<name>`. Keep it URL/topic-safe (lowercase, hyphens or underscores). |
| `description` | recommended | One-line summary surfaced by orchestrators and discovery UIs. |
| `url` | **required for direct UI calls** | Transport directive read by SAM clients. Use the form `solace:<namespace>/a2a/v1/agent/request/<name>` (no `//` after `solace:`) — this tells the SAM UI / other clients to reach the agent via the Solace broker on the same request topic the wrapper is already subscribed to. **Do not use `a2a://...`** — that scheme tells clients to open a direct A2A-over-HTTP transport to the URL, which the wrapper does not implement; UI-initiated calls will appear to succeed at the broker but render nothing in the UI. Orchestrator-mediated calls work either way because the orchestrator ignores the URL and forwards over its own broker connection. |
| `version` | recommended | Bump when behavior or interface changes. |
| `preferredTransport` | **required for SAM** | Set to `"JSONRPC"`. SAM peer agents register this; without it the agent may be silently dropped from the mesh registry. |
| `protocolVersion` | **required for SAM** | A2A protocol version string the agent speaks. Current SAM peers use `"0.3.0"`. |
| `provider` | optional | If present, must include `organization` (string) and `url` (string) — both required by the A2A `AgentProvider` schema. **Do not use `name`** — SAM rejects the card with `provider.organization Field required` if you do. |
| `capabilities.streaming` | recommended | Set `true` — this wrapper streams every AIMessage chunk back to the caller. |
| `capabilities.pushNotifications` | optional | Not implemented by this wrapper; leave `false`. |
| `capabilities.stateTransitionHistory` | **required for SAM** | SAM peer agents set this to `false`. Including the field is what matters — its absence is what causes SAM to reject the registration. |
| `capabilities.extensions` | **required for SAM** | Array of SAM-specific extension objects. SAM's UI uses these for display and tool discovery. Two extensions are expected (see below). Without `extensions`, the agent connects to the broker but does not appear in the SAM mesh registry / UI. |
| `defaultInputModes` / `defaultOutputModes` | recommended | Currently only `"text"` is honored end-to-end (see constraints). |
| `skills` | recommended | List of `{id, name, description, tags}`. Discovery only — the wrapper doesn't dispatch on skill id. |

**Required `capabilities.extensions` entries** (both):

1. **Display name** — `uri: "https://solace.com/a2a/extensions/display-name"`, `params.display_name: "<UI label>"`. Drives the agent's name in the SAM UI's agent list.
2. **Tools** — `uri: "https://solace.com/a2a/extensions/sam/tools"`, `params.tools: [...]`. List of `{id, name, description, tags}` for each tool the agent exposes. SAM uses this to populate the orchestrator's tool-routing table; at least one entry is expected.

See [templates/agent_card.json](templates/agent_card.json) for the canonical filled-in structure, and [examples/doc_formatter/agent_card.json](examples/doc_formatter/agent_card.json) for a working example.

To add your own agent: copy `templates/agent_card.json` next to your
`agent.py`, fill in the `<placeholders>`. Your `main.py` (copied from
[templates/main.py](templates/main.py)) reads it from there by default.

### `langgraph.json` — LangGraph CLI / Studio / LangSmith manifest

This file is **not used by the A2A Solace path at all**. It exists so you
can also load the same compiled graph in
[LangGraph Studio](https://langchain-ai.github.io/langgraph/cloud/quick_start/),
trace it via [LangSmith](https://docs.smith.langchain.com/), or deploy it
to LangGraph Platform — useful for visualising state transitions and
replaying turns during graph development.

Field reference (template at [templates/langgraph.json](templates/langgraph.json)):

| Field | Required | Notes |
| --- | --- | --- |
| `dependencies` | yes | List of pip-installable paths or package names. `"."` means "install this directory" — works when a `requirements.txt`, `pyproject.toml`, or `setup.py` sits beside the manifest. |
| `graphs` | yes | Mapping of `<exposed-name>` to `<file>:<variable>`. The variable must point at a **compiled** graph at module import time. |
| `env` | optional | Path to a dotenv file, relative to this manifest. The example uses `"../../.env"` to reuse the repo-root `.env`. |
| `python_version` | optional | Drives the runtime image when LangGraph Platform builds your deployment. |

Run locally:

```bash
pip install -U langgraph-cli
cd examples/doc_formatter && langgraph dev
```

This starts the LangGraph dev server (Studio UI on
http://localhost:8123) using your local Python environment. Studio runs
the graph **standalone** — it never touches Solace.

To add `langgraph.json` to a new agent: copy `templates/langgraph.json`,
update the graph entry to point at your `agent.py:graph` (or wherever your
compiled graph lives), and adjust the `env` path if your dotenv file isn't
two directories up.

### `main.py` — deployment script

Required. This is the entry point that runs your agent against Solace
Agent Mesh. The template at [templates/main.py](templates/main.py) is a
working skeleton with TODO markers; the filled-in version at
[examples/doc_formatter/main.py](examples/doc_formatter/main.py)
demonstrates the most common case (wrapping the graph with `MemorySaver`
for A2A conversation continuity).

What lives in `main.py`:

- Importing the agent and **building the deployment-time graph** — most
  commonly, wrapping with a checkpointer (`MemorySaver` / `SqliteSaver` /
  `PostgresSaver`) so the wrapper's `contextId → thread_id` mapping
  actually retains state. See [Constraints](#constraints) for why this
  lives here, not in `agent.py`.
- Custom broker properties beyond what `broker_properties_from_env()`
  builds (TLS client certs, OAuth, Kerberos, multi-broker failover).
- Per-environment runtime config (different checkpointer in dev vs prod;
  different broker; different agent card per region).
- Custom logging, observability hooks, startup tasks.
- Loading `.env` and `agent_card.json` from the agent's directory.
- Constructing `A2ALangchainServer` and running it with graceful
  SIGINT/SIGTERM handling.

The template includes the asyncio + signal-handling scaffolding so you
mainly edit the TODO markers (graph builder, checkpointer choice) and
leave the rest alone.

## Roadmap

Planned next, in order. See [CHANGELOG.md](CHANGELOG.md) for what's
already landed.

- **Wheel release on GitHub** — tag-triggered GitHub Action that builds
  the wheel + sdist and attaches them to a GitHub Release. Lets you
  `pip install <release-url>` from anywhere instead of cloning this repo.
- **Container base image on ghcr.io** — a slim image with Python + the
  wrapper pre-installed. Users extend with their own
  `FROM ghcr.io/.../solace-agent-mesh-langgraph:<tag>`, `COPY` of their `agent.py` /
  `agent_card.json` / `main.py`, and `ENTRYPOINT ["python", "main.py"]`.
- **"Add your own LangGraph" walkthrough** (`docs/getting-started.md`) —
  step-by-step guide written for non-Python audiences.
- **Tests** — adapter-level unit tests with a fake graph, plus a
  container smoke test in CI.
- **Broker authentication beyond basic.** OAuth (OIDC client credentials,
  JWT bearer), TLS client certificates, and Kerberos. Will surface as
  additional `SOLACE_BROKER_AUTH_*` env vars routed through
  `broker_properties_from_env()` in
  [src/solace_agent_mesh_langgraph/config.py](src/solace_agent_mesh_langgraph/config.py),
  plus an "advanced wiring" recipe in `main.py` for cases that don't fit
  env-var config (e.g. dynamically refreshed bearer tokens).
- **A2A file parts (references + embedded data).** Today the adapter
  accepts and emits only `kind: "text"`. Will extend
  [LangChainA2AAdapter](src/solace_agent_mesh_langgraph/adapter.py) to handle
  `kind: "file"` in both forms defined by the A2A spec: the URI-reference
  form (`file.uri`) and the inline-bytes form (`file.bytes`, base64).
  Inbound file parts map to LangChain `HumanMessage` content blocks the
  graph's LLM can consume (e.g. multimodal models); outbound file payloads
  from `AIMessage` are emitted as A2A `file` parts on the response stream.
  `kind: "data"` (structured JSON parts) is out of scope for the first
  pass.
- **Horizontal scaling via shared durable queue + TTL.** Today every
  `A2ALangchainServer` instance binds to its own non-durable exclusive
  queue, so running multiple instances of the same agent name causes
  request duplication (every queue receives a copy of each request).
  Will add config knobs (likely `SAM_QUEUE_NAME`, `SAM_QUEUE_TYPE`,
  `SAM_QUEUE_TTL_MS`) so multiple instances can bind to one **shared
  durable queue**, letting Solace load-balance requests across consumers.
  Per-message TTL prevents stale-message backlog when no consumer is
  attached. Single-instance dev keeps today's throwaway-queue behaviour
  by default. Conversation continuity in this mode requires a shared
  checkpointer (e.g. `PostgresSaver`) so any instance can resume any
  thread.
- **Per-process concurrency limit (semaphore-based backpressure).** The
  receive loop in [server.py](src/solace_agent_mesh_langgraph/server.py) currently
  fires `asyncio.create_task(self._message_handler(...))` unconditionally
  for every incoming message, with no upper bound. Under burst load,
  tasks accumulate until something else gives — typically the httpx
  connection pool (default 100), the LLM provider's rate limit, or
  process file descriptors (`ulimit -n`). Will add a `SAM_MAX_CONCURRENT_REQUESTS`
  env var backed by an `asyncio.Semaphore` — acquire before
  `create_task`, release in a `finally` block. Unset / `0` means
  unbounded (today's behaviour); a finite value gives clean backpressure
  to the broker (messages stay on the queue) instead of degrading at the
  network layer.

Not currently planned (call out so the limits are clear):

- **PyPI publishing.** The release workflow will land with a commented
  placeholder so you can flip it on later.
- **Cookiecutter / scaffolder.** Hand-copying `templates/` is light enough.
- **Bundled local broker** (docker-compose). Users bring their own —
  Solace cloud trial or the open-source broker container.
- **Multiple-graph hosting in one process.** One process, one agent. Run
  more processes if you need more agents.
