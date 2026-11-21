"""Small, stateless Responses API client for the synthetic shipment replay."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

import requests


RESPONSES_URL = "https://api.openai.com/v1/responses"
REASONING_EFFORT = "low"
REQUESTED_SERVICE_TIER = "default"
RESPONSE_STATUSES = frozenset({"completed", "incomplete", "failed", "cancelled", "queued", "in_progress"})
INCOMPLETE_REASONS = frozenset({"max_output_tokens", "content_filter"})


class ProviderError(RuntimeError):
    """A safe failure to record in a replay log, without the request body or key."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        http_status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.request_id = request_id


class OpenAIProvider:
    """Make one synchronous call per model turn. Failures are never retried here."""

    def __init__(self, api_key: str, timeout: float = 60) -> None:
        key = api_key.strip() if isinstance(api_key, str) else ""
        if not key or not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
            raise ProviderError("configuration", "Set OPENAI_API_KEY to a valid API credential.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ProviderError("configuration", "OpenAI timeout must be between zero and 300 seconds.")
        self._key = key
        self._timeout = (min(10, timeout), timeout)

    def turn(
        self,
        model: str,
        system: str,
        items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        max_output_tokens: int,
    ) -> dict[str, Any]:
        if not isinstance(model, str) or not model.strip():
            raise ProviderError("configuration", "An OpenAI model ID is required.")
        if type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise ProviderError("configuration", "max_output_tokens must be a positive integer.")
        if any(not isinstance(tool, dict) or tool.get("type") != "function" for tool in tools):
            raise ProviderError("configuration", "The replay accepts local function tools only.")
        payload = {
            "model": model,
            "instructions": system,
            "input": list(items),
            "tools": list(tools),
            "max_output_tokens": max_output_tokens,
            "parallel_tool_calls": False,
            "reasoning": {"effort": REASONING_EFFORT},
            "service_tier": REQUESTED_SERVICE_TIER,
            "store": False,
            # Retain encrypted reasoning for a stateless follow-up after a tool call.
            "include": ["reasoning.encrypted_content"],
        }
        network_error = None
        try:
            response = requests.post(
                RESPONSES_URL,
                headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"},
                json=payload,
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.Timeout:
            network_error = ProviderError("timeout", "OpenAI did not return a response before the timeout.")
        except requests.RequestException:
            network_error = ProviderError("transport", "The OpenAI request could not be completed.")
        # Raise outside the except block so the underlying request is not attached.
        if network_error is not None:
            raise network_error
        http_status = response.status_code
        request_tag = response.headers.get("x-request-id")
        request_id = (
            request_tag
            if isinstance(request_tag, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", request_tag)
            and self._key not in request_tag
            else None
        )
        if not 200 <= http_status < 300:
            kind, hint = _http_error(http_status)
            raise ProviderError(
                kind, f"OpenAI returned HTTP {http_status}. {hint}",
                http_status=http_status, request_id=request_id,
            )

        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise ProviderError(
                "invalid_response", "OpenAI returned an unreadable response.",
                http_status=http_status, request_id=request_id,
            )
        return _normalize(data, model, http_status, request_id)


def _http_error(status: int) -> tuple[str, str]:
    if status in (401, 403):
        return "authorization", "Check the project key and model permissions."
    if status == 429:
        return "rate_limit", "Check the project's quota, rate limits, and paid API access."
    if status >= 500:
        return "provider_unavailable", "The provider did not complete this request."
    return "request_rejected", "Check the requested model and the Responses API request shape."


def _normalize(
    data: dict[str, Any], model: str, http_status: int, request_id: str | None,
) -> dict[str, Any]:
    def invalid(message: str) -> ProviderError:
        return ProviderError("invalid_response", message, http_status=http_status, request_id=request_id)

    status = data.get("status")
    if not isinstance(status, str) or status not in RESPONSE_STATUSES:
        raise invalid("OpenAI returned an unknown response status.")
    items = data.get("output")
    if items is None and status != "completed":
        items = []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise invalid("OpenAI did not return a usable output item list.")
    usage = data.get("usage")
    if usage is not None or status == "completed":
        if not isinstance(usage, dict) or not all(
            type(usage.get(key)) is int and usage[key] >= 0 for key in ("input_tokens", "output_tokens")
        ):
            raise invalid("OpenAI did not report valid input and output token counts.")
    resolved = data.get("model")
    response_id = data.get("id")
    service_tier = data.get("service_tier")
    details = data.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else None
    return {
        "items": items,
        "usage": None if usage is None else {
            "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
        },
        # Preserve the billing breakdown for a later invoice reconciliation.
        "usage_details": usage,
        "model": resolved if isinstance(resolved, str) and resolved else model,
        "response_id": response_id if isinstance(response_id, str) and response_id else None,
        "service_tier": service_tier if isinstance(service_tier, str) and service_tier else None,
        "status": status,
        "incomplete_reason": reason if isinstance(reason, str) and reason in INCOMPLETE_REASONS else None,
    }
