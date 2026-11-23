"""Translate replay turns to the local Ollama chat protocol."""

import json
import re

import requests

from .openai_provider import ProviderError


class OllamaProvider:
    def __init__(self):
        self._session = requests.Session()
        self._session.trust_env = False  # Use loopback directly, even with a system proxy.

    def _post(self, endpoint, payload):
        try:
            response = self._session.post(f"http://127.0.0.1:11434/api/{endpoint}", json=payload,
                                          timeout=(5, 120), allow_redirects=False)
        except requests.Timeout as exc:
            raise ProviderError("timeout", "The local Ollama request timed out.") from exc
        except requests.RequestException as exc:
            raise ProviderError("transport", "Could not reach local Ollama. Check that Ollama is running.") from exc
        if not 200 <= response.status_code < 300:
            raise ProviderError("request_rejected", f"Local Ollama returned HTTP {response.status_code}.",
                                http_status=response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("invalid_response", "Ollama did not return readable JSON.") from exc
        if not isinstance(data, dict):
            raise ProviderError("invalid_response", "Ollama did not return a JSON object.")
        return data

    def check_model(self, model):
        if (not re.fullmatch(r"[\w.-]+(?::[\w.-]+)?", model, re.ASCII)
                or re.search(r"(?:^|[-:])cloud(?:$|[-:])", model, re.IGNORECASE)):
            raise ProviderError("configuration", "Choose an installed local Ollama model tag.")
        data = self._post("show", {"model": model})
        capabilities = data.get("capabilities")
        if data.get("remote_model") or data.get("remote_host"):
            raise ProviderError("configuration", "Choose an Ollama model that runs on this laptop.")
        if not isinstance(capabilities, list) or "tools" not in capabilities:
            raise ProviderError("configuration", "The selected Ollama model does not advertise tool calling.")

    def turn(self, model, system, items, tools, max_output_tokens):
        messages = [{"role": "system", "content": system}]
        names = {}
        for item in items:
            if item.get("role") == "user":
                messages.append(item)
            elif item.get("type") == "function_call":
                names[item["call_id"]] = item["name"]
                messages.append({"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {
                    "name": item["name"], "arguments": json.loads(item["arguments"]),
                }}]})
            elif item.get("type") == "function_call_output":
                messages.append({"role": "tool", "tool_name": names[item["call_id"]], "content": item["output"]})

        data = self._post("chat", {
            "model": model, "messages": messages, "stream": False,
            "tools": [{"type": "function", "function": {key: tool[key] for key in ("name", "description", "parameters")}}
                      for tool in tools],
            "options": {"num_predict": max_output_tokens, "temperature": 0},
        })
        reply = data.get("message")
        if data.get("done") is not True or not isinstance(reply, dict) or reply.get("role") != "assistant":
            raise ProviderError("invalid_response", "Ollama did not return a finished assistant response.")
        calls = reply.get("tool_calls", [])
        if not isinstance(calls, list):
            raise ProviderError("invalid_response", "Ollama returned an unreadable tool call list.")
        output = []
        for index, call in enumerate(calls):
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(function, dict) or not isinstance(function.get("name"), str)
                    or not isinstance(function.get("arguments"), dict)):
                raise ProviderError("invalid_response", "Ollama returned an unreadable tool call.")
            output.append({"type": "function_call", "call_id": f"ollama-{len(items)}-{index}",
                           "name": function["name"], "arguments": json.dumps(function["arguments"])})
        if isinstance(reply.get("content"), str) and reply["content"]:
            output.append({"type": "message", "content": [{"type": "output_text", "text": reply["content"]}]})
        usage = {"input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")}
        if not all(type(count) is int and count >= 0 for count in usage.values()):
            usage = None
        limited = data.get("done_reason") == "length"
        return {"items": output, "status": "incomplete" if limited else "completed", "usage": usage,
                "model": data.get("model") or model, "incomplete_reason": "max_output_tokens" if limited else None}
