from __future__ import annotations

from aiogram import Dispatcher

from .throttling import ThrottlingMiddleware


def setup_middlewares(dispatcher: Dispatcher) -> None:
    dispatcher.message.outer_middleware(ThrottlingMiddleware())
