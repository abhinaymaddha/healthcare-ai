"""Application entry point — run with: uvicorn main:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.graph.main_graph import build_graph
from app.core.classifier import get_classifier
from app.api.routes.triage import router as triage_router
from app.api.routes.health import router as health_router

load_dotenv()

_log_formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_formatter)
_file_handler = logging.FileHandler("eval/server_latest.log", mode="w", encoding="utf-8")
_file_handler.setFormatter(_log_formatter)
logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pre-loading local classifier...")
    get_classifier()
    logger.info("Building LangGraph...")
    app.state.graph = build_graph()
    logger.info("Ready.")
    yield


app = FastAPI(
    title="Healthcare AI Triage Concierge",
    description=(
        "Multi-agent patient triage system. "
        "Covers symptom check (UC1), prescription refill (UC2), and appointment booking (UC3)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(triage_router)
app.include_router(health_router)
