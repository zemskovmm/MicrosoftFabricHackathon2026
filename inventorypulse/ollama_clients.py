"""Local Ollama transport for Microsoft Agent Framework's actual function-calling loop."""

import copy
import json
import os
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message

from .engine import AGENTS


class OllamaChatClient(FunctionInvocationLayer, BaseChatClient):
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", *, transport=None):
        super().__init__(
            function_invocation_configuration={
                "max_iterations": 8,
                "max_function_calls": 60,
                "max_duration_seconds": 300,
            }
        )
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Local Ollama mode requires a loopback HTTP endpoint")
        self.model = model
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=300, trust_env=False, transport=transport
        )

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if stream:
            raise ValueError("Ollama adapter supports non-streaming agent runs only")
        options = await self._validate_options(options)
        native = []
        tool_names = {}
        stage_result_received = False
        stage_receipt = None
        for message in messages:
            texts = [c.text for c in message.contents if c.type == "text" and c.text]
            calls = []
            for content in message.contents:
                if content.type == "function_call":
                    tool_names[content.call_id] = content.name
                    args = (
                        json.loads(content.arguments)
                        if isinstance(content.arguments, str)
                        else content.arguments
                    )
                    calls.append({"function": {"name": content.name, "arguments": args or {}}})
                elif content.type == "function_result":
                    value = content.result
                    if isinstance(value, list):
                        value = "".join(c.text or "" for c in value if c.type == "text")
                    text = value if isinstance(value, str) else json.dumps(value)
                    try:
                        parsed = json.loads(text)
                        if (
                            isinstance(parsed, dict)
                            and "receipt" in parsed
                            and ("handoff" in parsed or parsed.get("stage_complete") is True)
                        ):
                            stage_result_received = True
                            stage_receipt = parsed
                    except (ValueError, TypeError):
                        pass
                    native.append(
                        {
                            "role": "tool",
                            "tool_name": content.name or tool_names.get(content.call_id, ""),
                            "content": text,
                        }
                    )
            if texts or calls:
                item = {
                    "role": "system" if message.role == "developer" else str(message.role),
                    "content": "\n".join(texts),
                }
                if calls:
                    item["tool_calls"] = calls
                native.append(item)
        instructions = options.get("instructions")
        if instructions:
            native.insert(0, {"role": "system", "content": instructions})
        tools = options.get("tools") or []
        payload = {
            "model": self.model,
            "messages": native,
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 1200},
        }
        if self.model.lower().startswith("gpt-oss"):
            payload["think"] = "low"
            payload["options"]["num_predict"] = 2200
        # Llama 8B is more reliable when tool selection and schema-constrained final output
        # are separate turns. The Microsoft framework executes every returned tool call.
        if tools and not stage_result_received:
            payload["tools"] = [
                t.to_json_schema_spec() if hasattr(t, "to_json_schema_spec") else t for t in tools
            ]
        else:
            schema = options.get("response_format")
            if schema is not None:
                schema = copy.deepcopy(
                    schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema
                )
                # Constrain evidence at generation time as well as validating it afterwards.
                # This avoids 8B models corrupting long SHA-256 strings when copying them.
                if stage_receipt and "handoff" in stage_receipt and "receipt" in schema.get("properties", {}):
                    schema["properties"]["receipt"]["enum"] = [stage_receipt["receipt"]]
                    sources = stage_receipt["handoff"]["source_references"]
                    schema["properties"]["citations"]["items"]["enum"] = sources
                    schema["properties"]["citations"]["maxItems"] = len(sources)
                payload["format"] = schema
        response = await self.http.post("/api/chat", json=payload)
        response.raise_for_status()
        result = response.json()
        if result.get("error"):
            raise ValueError(f"Ollama rejected the model request: {result['error']}")
        if not result.get("done") or result.get("done_reason") == "length":
            raise ValueError("Ollama response was incomplete; no partial agent result accepted")
        reply = result["message"]
        contents = []
        if reply.get("content"):
            contents.append(Content("text", text=reply["content"]))
        for call in reply.get("tool_calls", []):
            function = call["function"]
            contents.append(
                Content(
                    "function_call",
                    call_id=uuid4().hex,
                    name=function["name"],
                    arguments=json.dumps(function.get("arguments", {})),
                )
            )
        if not contents:
            raise ValueError("Ollama returned an empty response")
        return ChatResponse(messages=Message("assistant", contents), model=self.model)

    async def close(self):
        await self.http.aclose()


class OllamaClients:
    def __init__(self, model=None, base_url=None):
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.clients = {}
        self.credentials = {role: None for role in AGENTS}
        self.identity_ids = {}

    async def __aenter__(self):
        try:
            for role in AGENTS:
                self.clients[role] = OllamaChatClient(self.model, self.base_url)
            response = await self.clients[AGENTS[0]].http.get("/api/tags")
            response.raise_for_status()
            available = {row["name"] for row in response.json()["models"]}
            if self.model not in available:
                raise ValueError(
                    f"Ollama model {self.model!r} is not installed; available: {sorted(available)}"
                )
            return self
        except Exception:
            await self.__aexit__(None, None, None)
            raise

    def __call__(self, role):
        return self.clients[role]

    async def __aexit__(self, *args):
        for client in self.clients.values():
            await client.close()
