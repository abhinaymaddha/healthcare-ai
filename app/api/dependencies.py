"""FastAPI dependency — provides the compiled LangGraph instance."""
from __future__ import annotations
from fastapi import Request


def get_graph(request: Request):
    return request.app.state.graph
