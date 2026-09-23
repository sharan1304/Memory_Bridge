"""Loads MENNBridge configuration from environment variables (.env)."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "mennbridge"
    database_url: str = ""
    mennbridge_project: str = ""
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        qdrant_url=os.getenv("QDRANT_URL", ""),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "mennbridge"),
        database_url=os.getenv("DATABASE_URL", ""),
        mennbridge_project=os.getenv("MENNBRIDGE_PROJECT", ""),
        port=int(os.getenv("PORT", "8000")),
    )
