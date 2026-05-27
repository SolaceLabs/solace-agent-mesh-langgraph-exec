# syntax=docker/dockerfile:1
#
# Bundled image for the doc_formatter EXAMPLE only.
# -------------------------------------------------
#
# This Dockerfile installs the sam-langgraph-a2a wrapper AND the bundled
# Documentation Formatter agent into a single image, as a convenience for
# smoke-testing the container deployment path end-to-end without needing a
# published base image.
#
# Build context must be the repo ROOT (so the wrapper source under ../../src
# and ../../pyproject.toml are reachable). From the repo root:
#
#     docker build -t doc-formatter:dev -f examples/doc_formatter/Dockerfile .
#
# Once a base image of the wrapper is published to ghcr.io (Stage 3 of the
# deployability roadmap), this file will collapse to roughly:
#
#     FROM ghcr.io/dennis-brinley/sam-langgraph-a2a:<tag>
#     COPY agent.py agent_card.json main.py ./
#     ENTRYPOINT ["python", "main.py"]
#
# At that point the repo root will hold a *separate* base-image Dockerfile
# that installs only the wrapper and stops bundling any agent code.

FROM python:3.12-slim

WORKDIR /app

# Install the wrapper + the example agent's extras (langchain-openai).
# The bundled doc_formatter agent uses ChatOpenAI; without [examples] you'd
# get "No module named 'langchain_openai'" at import time.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir ".[examples]"

# Bundle the example agent (agent + card + deployment script)
COPY examples/doc_formatter/agent.py \
     examples/doc_formatter/agent_card.json \
     examples/doc_formatter/main.py \
     ./

# Non-root + entrypoint
RUN useradd -m -u 1000 sam && chown -R sam:sam /app
USER sam

ENTRYPOINT ["python", "main.py"]
