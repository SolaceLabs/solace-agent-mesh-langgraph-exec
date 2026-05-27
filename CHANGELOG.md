# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `sam_langgraph_a2a.broker_properties_from_env()` helper. Builds the
  Solace SDK property dict from `SOLACE_BROKER_URL`, `SOLACE_BROKER_VPN`,
  `SOLACE_BROKER_USERNAME`, `SOLACE_BROKER_PASSWORD` — matching the
  Solace Agent Mesh (SAM) env-var convention.
- Optional TLS env vars `SOLACE_BROKER_TRUST_STORE_DIR` and
  `SOLACE_BROKER_VALIDATE_CERTS`, mapped to the corresponding
  `solace.messaging.tls.*` properties.
- `sam_langgraph_a2a.env_str()` — public `os.getenv`-style helper that
  strips surrounding straight quotes from the returned value. Used
  internally by `broker_properties_from_env()` and recommended for any
  env-var reads in user code (`agent.py` / `main.py`). Why: python-dotenv
  strips quotes from `KEY="value"` lines, but Docker / Podman's
  `--env-file` does not — the same `.env` therefore yields different
  values under different loaders, which has bitten users in practice
  (e.g. `OPENAI_BASE_URL` ending up with literal `"` characters inside a
  container). `env_str` normalises both paths.
- `LICENSE` (Apache-2.0) + `NOTICE`, `CHANGELOG.md`, `CONTRIBUTING.md`.

### Changed

- `python-dotenv` is now a runtime dependency (used by the example's
  `main.py`).
- `pyproject.toml`: expanded keywords, classifiers, project URLs.

### Removed

- Dangling `tool.setuptools.package-data` reference to a `py.typed` marker
  that didn't exist.

## [0.1.0] - Initial port

- Ported `lang_a2a.py` and `a2a_server.py` from the upstream `a2a_proxy`
  prototype into the `sam_langgraph_a2a` package.
- Mapped A2A `contextId` to LangGraph `thread_id` so checkpointed graphs
  retain conversation state across requests sharing the same `contextId`.
- Added `examples/doc_formatter/`. `agent.py` exposes a stateless
  module-level `graph` (so `langgraph dev` / LangGraph Platform can load
  it — they reject custom checkpointers) plus a `DocumentationFormatterAgent`
  class that accepts an optional `checkpointer=` kwarg.
  `examples/doc_formatter/main.py` is the SAM/A2A entry point — it
  re-builds the graph with `MemorySaver` so `contextId → thread_id`
  continuity actually persists state across turns.
- Added `templates/main.py` — deployment-script scaffold with TODO markers
  for users adding their own agent: choose the checkpointer, customise the
  broker properties, etc.
- Added blank scaffolds in `templates/` for `agent_card.json` and
  `langgraph.json`.
- Added `examples/doc_formatter/Dockerfile` bundling wrapper + example
  into a single image (transitional until a base image is published to
  ghcr.io).
