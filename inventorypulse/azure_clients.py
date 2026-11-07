"""Model clients configured through the deployment environment; no embedded credentials."""

import inspect
import os
from urllib.parse import urlparse
from uuid import UUID

from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

from .engine import AGENTS


class AzureClients:
    def __init__(self):
        self.clients, self.credentials, self.identity_ids = {}, {}, {}

    async def __aenter__(self):
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        deployment = os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"]
        if urlparse(endpoint).scheme != "https":
            raise ValueError("Azure OpenAI endpoint must use HTTPS")
        try:
            for role in AGENTS:
                prefix = f"INVENTORYPULSE_{role.upper().replace('-', '_')}"
                managed_client = os.getenv(prefix + "_MANAGED_IDENTITY_CLIENT_ID")
                identity = os.getenv(prefix + "_AGENT_ID")
                if managed_client:
                    UUID(managed_client)
                if identity:
                    UUID(identity)
                    self.identity_ids[role] = identity
                credential = (
                    ManagedIdentityCredential(client_id=managed_client)
                    if managed_client
                    else DefaultAzureCredential()
                )
                self.credentials[role] = credential
                self.clients[role] = OpenAIChatCompletionClient(
                    azure_endpoint=endpoint,
                    model=deployment,
                    credential=credential,
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                    function_invocation_configuration={
                        "max_iterations": 12,
                        "max_function_calls": 60,
                        "max_duration_seconds": 120,
                    },
                )
            if len(set(self.identity_ids.values())) != len(self.identity_ids):
                raise ValueError("Entra agent identities must be separate")
            return self
        except Exception:
            await self.__aexit__(None, None, None)
            raise

    def __call__(self, role):
        return self.clients[role]

    async def __aexit__(self, *args):
        for client in self.clients.values():
            result = client.close()
            if inspect.isawaitable(result):
                await result
        for credential in self.credentials.values():
            credential.close()
