"""Shared runtime objects for handlers."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .agent import Agent
from .conversation import ChatLocks, ConversationStore, LanguageStore
from .database import Database
from .llm import LLMClient


@dataclass(slots=True)
class Runtime:
    database: Database
    llm: LLMClient
    agent: Agent
    conversations: ConversationStore
    languages: LanguageStore
    locks: ChatLocks
    started_at: float


_runtime: Runtime | None = None


def set_runtime(runtime: Runtime) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> Runtime:
    if _runtime is None:
        raise RuntimeError("runtime is not initialised")
    return _runtime


def create_runtime(database: Database, llm: LLMClient) -> Runtime:
    runtime = Runtime(
        database=database,
        llm=llm,
        agent=Agent(database, llm),
        conversations=ConversationStore(),
        languages=LanguageStore(),
        locks=ChatLocks(),
        started_at=time.monotonic(),
    )
    set_runtime(runtime)
    return runtime
