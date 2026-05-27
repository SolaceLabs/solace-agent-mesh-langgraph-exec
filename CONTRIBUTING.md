# Contributing

Thanks for your interest. This is a small project; the goal is to keep the
wrapper minimal and the example obvious.

## Development setup

```bash
git clone <repo>
cd solace-agent-mesh-langgraph-exec
python -m venv .venv && source .venv/bin/activate
pip install -e ".[examples,dev]"
```

This installs the package in editable mode together with the example agent's
extra deps (`langchain-openai`) and the dev toolchain (`build`, `ruff`).

## Running the example

```bash
cp .env.example examples/doc_formatter/.env   # fill in broker + OPENAI_API_KEY
cd examples/doc_formatter
python main.py
```

Smoke-test the graph in isolation (no broker needed):

```bash
python examples/doc_formatter/agent.py
```

## Code style

- `ruff check .` for lint. Configuration is in `pyproject.toml` once a
  `[tool.ruff]` section is added — for now defaults are fine.
- Keep server logic minimal. The wrapper deliberately stays close to the
  upstream A2A protocol shape; behaviour changes should be discussed in an
  issue first.
- Comments explain *why*, not *what*. Identifier names should carry the
  *what*.

## Filing issues

Open a GitHub issue at the project's Issues page (see `project.urls` in
`pyproject.toml`). Helpful issue contents:

- Solace broker version (open-source / appliance / cloud)
- Python version
- The exact command you ran
- Logs at `--log-level DEBUG`
- Minimal reproducer if applicable

## Releasing

(See `CHANGELOG.md` for the format.) Once GitHub Actions for release are in
place (Stage 2 of the deployability plan):

1. Update `version` in `pyproject.toml` and `src/sam_langgraph_a2a/__init__.py`.
2. Move the "Unreleased" section in `CHANGELOG.md` under a dated version
   heading.
3. Commit, tag `vX.Y.Z`, push tag.
4. The release workflow builds the wheel + sdist and publishes them as
   GitHub Release assets.
