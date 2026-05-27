# SPDX-License-Identifier: Apache-2.0
"""Helpers for building Solace broker connection properties from env vars."""

from __future__ import annotations

import os
from typing import Dict


def _unquote(value: str) -> str:
    """Strip a matching pair of surrounding straight quotes if present.

    Curly/typographic quotes are not stripped — they don't function as
    delimiters in either parser, so leaving them alone preserves user intent.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def env_str(name: str, default=None):
    """``os.getenv``-style reader that strips surrounding straight quotes.

    Always prefer this over a naked ``os.getenv`` when reading env vars
    that might come from a ``.env`` file. Why: python-dotenv strips
    surrounding ``"..."`` / ``'...'`` from values on load, but Docker /
    Podman's ``--env-file`` does *not*. The same ``.env`` therefore yields
    different runtime values depending on how the program is invoked —
    e.g. ``OPENAI_BASE_URL="https://api.openai.com/v1"`` ends up as a URL
    that includes literal double-quote characters inside a container,
    blowing up at the first HTTP request. ``env_str`` normalises both
    paths at the boundary.

    Signature mirrors ``os.getenv``: ``default`` is returned unchanged
    when the variable is unset (defaults to ``None``).
    """
    value = os.environ.get(name, default)
    if not isinstance(value, str):
        return value
    return _unquote(value)


def broker_properties_from_env() -> Dict[str, str]:
    """Build a Solace SDK broker_properties dict from standard env vars.

    Variable names match the Solace Agent Mesh (SAM) convention so a SAM
    user's existing ``.env`` works without renames.

    Required (with defaults shown):
        SOLACE_BROKER_URL       (default: tcp://localhost:55555)
        SOLACE_BROKER_VPN       (default: default)
        SOLACE_BROKER_USERNAME  (default: default)
        SOLACE_BROKER_PASSWORD  (default: default)

    Optional TLS settings (only used when set; needed for ``tcps://`` brokers):
        SOLACE_BROKER_TRUST_STORE_DIR   directory of PEM/DER CA certs.
                                        Maps to solace.messaging.tls.trust-store-path.
        SOLACE_BROKER_VALIDATE_CERTS    "true" / "false" (default true).
                                        Maps to solace.messaging.tls.cert-validated.
                                        Set "false" for dev/testing only.

    Returns a dict using the property keys that
    ``MessagingService.builder().from_properties(...)`` expects.

    Basic auth only. For client-cert auth, OAuth, or Kerberos, extend the
    returned dict (or build your own) with the appropriate
    ``solace.messaging.authentication.*`` keys.
    """
    props: Dict[str, str] = {
        "solace.messaging.transport.host": env_str("SOLACE_BROKER_URL", "tcp://localhost:55555"),
        "solace.messaging.service.vpn-name": env_str("SOLACE_BROKER_VPN", "default"),
        "solace.messaging.authentication.scheme.basic.username": env_str(
            "SOLACE_BROKER_USERNAME", "default"
        ),
        "solace.messaging.authentication.scheme.basic.password": env_str(
            "SOLACE_BROKER_PASSWORD", "default"
        ),
    }

    # Only set TLS properties when the user explicitly provides them — let
    # the SDK fall back to its own defaults otherwise.
    trust_store_dir = env_str("SOLACE_BROKER_TRUST_STORE_DIR")
    if trust_store_dir:
        props["solace.messaging.tls.trust-store-path"] = trust_store_dir

    validate_certs_raw = os.getenv("SOLACE_BROKER_VALIDATE_CERTS")
    if validate_certs_raw is not None:
        # The underlying Solace C library rejects "true"/"false" strings —
        # the documented SESSION_SSL_VALIDATE_CERTIFICATE values are the
        # C-API constants "1" (enable) and "0" (disable). We accept common
        # human spellings here and map to the wire format.
        truthy = _unquote(validate_certs_raw).strip().lower() in (
            "true", "1", "yes", "on",
        )
        props["solace.messaging.tls.cert-validated"] = "1" if truthy else "0"

    return props
