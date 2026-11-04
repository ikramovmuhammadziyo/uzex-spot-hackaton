from __future__ import annotations

from aiogram import Dispatcher

from .errors import errors_router
from .users import router as users_router


def setup_routers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(users_router)
    dispatcher.include_router(errors_router)
