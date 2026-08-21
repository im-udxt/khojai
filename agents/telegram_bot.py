"""Telegram interface.

Only the configured user id may run anything. The bot is reachable by anyone
who finds it, so every handler checks the sender first.
"""
import asyncio
import logging

from telegram import BotCommand, LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import config
import db
import health
import research

log = logging.getLogger("khoj.telegram")

_app = None


def allowed(update):
    user = update.effective_user
    if not user or not config.TELEGRAM_ALLOWED_USER:
        return False
    return str(user.id) == str(config.TELEGRAM_ALLOWED_USER)


async def guard(update):
    if allowed(update):
        return True
    if update.message:
        await update.message.reply_text(
            "This bot is private. Ask the owner for access.")
    log.warning("blocked user %s",
                update.effective_user.id if update.effective_user else "?")
    return False


async def send(chat_id, text, **kw):
    """Send in chunks, falling back to plain text if the markup is rejected."""
    if not _app:
        return
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    chunks.append(current)
    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            await _app.bot.send_message(
                chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True), **kw)
        except TelegramError as exc:
            log.warning("html send rejected: %s", str(exc)[:100])
            import re
            await _app.bot.send_message(chat_id=chat_id,
                                        text=re.sub(r"<[^>]+>", "", chunk))


async def cmd_start(update, context):
    if not await guard(update):
        return
    await update.message.reply_text(
        "KhojAI\n\n"
        "/investigate <question> goes and reads new articles about your "
        "question, then answers with sources.\n"
        "  /investigate Adani Ports\n"
        "  /investigate link between SEBI and Adani\n\n"
        "/ask <question> answers from what is already stored, no fetching.\n"
        "/status shows what is running.\n\n"
        "Every answer carries the source links it came from.")


async def cmd_status(update, context):
    if not await guard(update):
        return
    snap = health.publish()
    lines = ["<b>Status</b>", ""]
    for name, info in snap["services"].items():
        mark = "ok" if info["state"] == "up" else "DOWN"
        lines.append(f"{name}: {mark} ({research._esc(info['note'])})")
    lines.append("")
    lines.append(f"queue: {snap['queue_depth']} waiting")
    await send(str(update.effective_chat.id), "\n".join(lines))


async def cmd_ask(update, context):
    if not await guard(update):
        return
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Usage: /ask who runs Adani Ports")
        return
    await update.effective_chat.send_action(ChatAction.TYPING)
    loop = asyncio.get_running_loop()
    try:
        answer = await asyncio.wait_for(
            loop.run_in_executor(None, research.report, question), timeout=180)
    except asyncio.TimeoutError:
        answer = "That took too long. Try a shorter question."
    except Exception as exc:
        log.error("ask failed: %s", exc)
        answer = "Something went wrong. It has been logged."
    await send(str(update.effective_chat.id), answer)


async def cmd_investigate(update, context):
    if not await guard(update):
        return
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text(
            "Usage: /investigate <question>\n"
            "Example: /investigate link between SEBI and Adani")
        return

    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        f"Looking into: {question}\nThis takes a few minutes. "
        "I will post progress as it goes.")
    loop = asyncio.get_running_loop()

    def progress(msg):
        asyncio.run_coroutine_threadsafe(
            _app.bot.send_message(chat_id=chat_id, text=msg), loop)

    try:
        answer = await asyncio.wait_for(
            loop.run_in_executor(None, research.investigate, question, progress),
            timeout=900)
    except asyncio.TimeoutError:
        answer = "Still working. Results will appear on the site when ready."
    except Exception as exc:
        log.error("investigate failed: %s", exc)
        answer = "The investigation failed. It has been logged."
    await send(chat_id, answer)


async def on_text(update, context):
    if not await guard(update):
        return
    context.args = (update.message.text or "").split()
    await cmd_ask(update, context)


def build():
    global _app
    if not config.TELEGRAM_TOKEN:
        log.warning("no telegram token set, bot disabled")
        return None
    if not config.TELEGRAM_ALLOWED_USER:
        log.error("TELEGRAM_ALLOWED_USER_ID is empty, refusing to start an open bot")
        return None
    _app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("help", cmd_start))
    _app.add_handler(CommandHandler("status", cmd_status))
    _app.add_handler(CommandHandler("ask", cmd_ask))
    _app.add_handler(CommandHandler("investigate", cmd_investigate))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return _app


async def idle():
    """Keep the process alive so the crawler and worker threads keep running."""
    while True:
        await asyncio.sleep(3600)


async def run():
    """Start the bot. A bad token must never take the rest of the system down.

    The crawler and the worker are threads inside this process, so an
    exception here used to kill collection entirely. A revoked token now
    disables Telegram and leaves everything else running.
    """
    try:
        app = build()
    except Exception as exc:
        log.error("telegram could not start, continuing without it: %s", str(exc)[:160])
        await idle()
        return
    if app is None:
        await idle()
        return
    try:
        await _serve(app)
    except InvalidToken:
        log.error("the telegram token was rejected, continuing without telegram")
        db.activity("telegram", "token rejected, telegram is off")
        await idle()
    except Exception as exc:
        log.error("telegram stopped, continuing without it: %s", str(exc)[:160])
        db.activity("telegram", "stopped, the rest of the system keeps running")
        await idle()


async def _serve(app):
    async with app:
        await app.start()
        try:
            await app.bot.set_my_commands([
                BotCommand("investigate", "Research a question and answer with sources"),
                BotCommand("ask", "Answer from what is already stored"),
                BotCommand("status", "Show service status"),
            ])
        except Exception as exc:
            log.warning("command menu not set: %s", str(exc)[:80])
        db.activity("telegram", "bot online")
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        while True:
            await asyncio.sleep(60)
