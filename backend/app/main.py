from __future__ import annotations

import json
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .store import repository as repo
from .store.db import init_db

DOMAINS_DIR = os.path.join(os.path.dirname(__file__), "data", "domains")
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

app = FastAPI(title="Monetize360 Universal Dynamic Pricing Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _seed_builtin_domains() -> None:
    existing = set(repo.list_domains())
    for filename in sorted(os.listdir(DOMAINS_DIR)):
        if not filename.endswith(".json"):
            continue
        domain = filename[:-5]
        if domain in existing:
            continue
        with open(os.path.join(DOMAINS_DIR, filename)) as f:
            config_dict = json.load(f)
        repo.create_version(domain, config_dict, created_by="seed", note="initial seed", activate=True)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    _seed_builtin_domains()


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
