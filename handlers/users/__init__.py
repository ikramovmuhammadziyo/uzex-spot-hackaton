from __future__ import annotations

from aiogram import Router

from .health import router as health_router
from .help import router as help_router
from .language import router as language_router
from .question import router as question_router
from .reset import router as reset_router
from .start import router as start_router

router = Router(name="users")
# Commands first; the free-text question router must be last.
router.include_routers(
    start_router,
    help_router,
    language_router,
    reset_router,
    health_router,
    question_router,
)
