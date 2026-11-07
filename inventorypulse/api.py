"""Loopback-only demonstrator. Real deployment must replace the local key with Entra authentication."""

import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse

from .models import Decision
from .store import Store


def create_app(store: Store, approval_key: str) -> FastAPI:
    app = FastAPI(title="InventoryPulse local demonstrator", version="0.1.0")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.get("/")
    def dashboard():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/api/run")
    def latest():
        try:
            return store.get()
        except KeyError as error:
            raise HTTPException(404, "No run yet. Run the analysis command first.") from error

    @app.get("/api/audit")
    def audit():
        return store.audit()

    @app.post("/api/runs/{run_id}/decisions")
    def decide(run_id: str, decision: Decision, x_approval_key: str = Header(default="")):
        if not secrets.compare_digest(x_approval_key, approval_key):
            raise HTTPException(403, "A valid local approval key is required")
        try:
            return store.decide(run_id, decision)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    return app
