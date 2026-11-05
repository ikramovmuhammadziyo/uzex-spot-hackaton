from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from data import config
from services.agent import AgentError
from services.formatting import split_message
from services.language import RU, detect_language
from services.llm import LLMError
from services.messages import (
    BUSY,
    EMPTY,
    GENERIC_ERROR,
    LLM_UNAVAILABLE,
    SERVICE_UNAVAILABLE,
    TIMEOUT,
    TOO_LONG,
)
from services.qa_log import hash_user_id, log_qa
from services.runtime import get_runtime

logger = logging.getLogger(__name__)
router = Router(name="question")


@router.message(F.text & ~F.text.startswith("/"))
async def answer_question(message: Message) -> None:
    text = (message.text or "").strip()
    runtime = get_runtime()
    chat_id = message.chat.id
    language = runtime.languages.get(chat_id) or detect_language(text, RU)

    if not text:
        await message.answer(EMPTY[language], parse_mode=None)
        return
    if len(text) > config.MAX_QUESTION_CHARS:
        await message.answer(TOO_LONG[language], parse_mode=None)
        return

    if not await runtime.locks.try_acquire(chat_id):
        await message.answer(BUSY[language], parse_mode=None)
        return

    user_id = message.from_user.id if message.from_user else None
    log_record = {
        "chat_id": chat_id,
        "user": hash_user_id(user_id),
        "language": language,
        "question": text,
    }

    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=chat_id):
            answer = await asyncio.wait_for(
                runtime.agent.answer(
                    text,
                    language,
                    history=runtime.conversations.history(chat_id),
                ),
                timeout=config.AGENT_TIMEOUT_SECONDS,
            )

        for chunk in split_message(answer.text):
            await message.answer(chunk, parse_mode=None)

        runtime.conversations.add_user(chat_id, text)
        runtime.conversations.add_assistant(chat_id, answer.text)

        log_qa(
            {
                **log_record,
                "answer": answer.text,
                "latency": round(answer.latency, 3),
                "tool_calls": answer.tool_calls,
                "query_count": answer.query_count,
                "tables": answer.tables,
                "sql_queries": answer.sql_queries,
                "rows": answer.rows,
                "guardrail_ok": answer.guardrail_ok,
                "regenerated": answer.regenerated,
                "no_answer": answer.no_answer,
                "outcome": answer.outcome,
                "coverage": answer.coverage,
                "analysis": answer.analysis,
                "metrics": answer.metrics,
                "trace": answer.trace,
                "cache_hits": answer.cache_hits,
                "cache_misses": answer.cache_misses,
                "model": answer.model,
                "usage": answer.usage,
            }
        )
    except asyncio.TimeoutError:
        logger.warning("agent timeout chat=%s", chat_id)
        log_qa({**log_record, "error": "timeout"})
        await message.answer(TIMEOUT[language], parse_mode=None)
    except AgentError as exc:
        logger.exception("agent service error chat=%s", chat_id)
        log_qa({**log_record, "error": "agent_error", "outcome": exc.outcome,
                "trace": getattr(exc, "trace", []), "usage": getattr(exc, "usage", {}),
                "latency": getattr(exc, "latency", None)})
        await message.answer(SERVICE_UNAVAILABLE[language], parse_mode=None)
    except LLMError:
        logger.exception("LLM error chat=%s", chat_id)
        log_qa({**log_record, "error": "llm_error"})
        await message.answer(LLM_UNAVAILABLE[language], parse_mode=None)
    except Exception:
        logger.exception("unhandled error chat=%s", chat_id)
        log_qa({**log_record, "error": "unhandled"})
        await message.answer(GENERIC_ERROR[language], parse_mode=None)
    finally:
        runtime.locks.release(chat_id)
