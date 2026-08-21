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
import merge
import metrics
import research
import watch

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
        "/ask <question> answers from what is already stored, no fetching.\n\n"
        "/watch <name> tells you when a new link touches that name.\n"
        "/unwatch <name> stops it. /watching lists them.\n\n"
        "/merges shows duplicate names waiting for a decision.\n"
        "/status shows what is running. /stats shows the totals.\n\n"
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


async def cmd_watch(update, context):
    if not await guard(update):
        return
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Usage: /watch Adani Ports")
        return
    _, message = watch.add(name)
    await update.message.reply_text(message)


async def cmd_unwatch(update, context):
    if not await guard(update):
        return
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Usage: /unwatch Adani Ports")
        return
    _, message = watch.remove(name)
    await update.message.reply_text(message)


async def cmd_watching(update, context):
    if not await guard(update):
        return
    items = watch.listing()
    if not items:
        await update.message.reply_text(
            "Not following anything. Add one with /watch <name>.")
        return
    lines = ["<b>Following</b>", ""]
    for item in items:
        hits = int(item.get("hits") or 0)
        lines.append(f"{research._esc(item['name'])} - "
                     f"{hits} link{'' if hits == 1 else 's'} so far")
    await send(str(update.effective_chat.id), "\n".join(lines))


async def cmd_stats(update, context):
    if not await guard(update):
        return
    snap = metrics.snapshot()
    box = snap.get("machine", {})
    lines = ["<b>Totals</b>", "", research._esc(snap.get("summary", "")), ""]
    mem = box.get("memory") or {}
    cpu = box.get("cpu") or {}
    if mem or cpu:
        lines.append(f"machine: {cpu.get('busy_pct', '?')}% processor, "
                     f"{mem.get('used_gb', '?')} of {mem.get('total_gb', '?')} GB memory")
    archive = snap.get("archive") or {}
    lines.append(f"archive: {archive.get('documents', 0)} documents, "
                 f"{archive.get('size_mb', 0)} MB")
    dead = [s for s in snap.get("sources", []) if not s["items"]]
    lines.append(f"sources: {len(snap.get('sources', []))} tried, "
                 f"{len(dead)} returned nothing last time")
    lines.append(f"following: {snap.get('watching', 0)} names")
    lines.append(f"merges waiting: {snap.get('merges_waiting', 0)}")
    await send(str(update.effective_chat.id), "\n".join(lines))


async def cmd_merges(update, context):
    """Show duplicate names the rules were not confident enough to fold."""
    if not await guard(update):
        return
    args = context.args or []
    if len(args) >= 2 and args[0] in ("yes", "no"):
        message = merge.resolve(args[1], args[0] == "yes")
        await update.message.reply_text(message)
        return

    waiting = merge.reviews()[:8]
    if not waiting:
        recent = merge.merges(5)
        text = "Nothing waiting. "
        if recent:
            text += "Folded recently: " + ", ".join(
                f"{r['removed']} into {r['kept']}" for r in recent)
        await update.message.reply_text(text)
        return
    lines = ["<b>Possible duplicates</b>",
             "Reply with /merges yes &lt;id&gt; or /merges no &lt;id&gt;.", ""]
    for item in waiting:
        lines.append(f"{research._esc(item['a']['name'])}  +  "
                     f"{research._esc(item['b']['name'])}")
        lines.append(f"  {research._esc(item['reason'])}")
        lines.append(f"  id: {item['pair']}")
        lines.append("")
    await send(str(update.effective_chat.id), "\n".join(lines))


async def alert_loop():
    """Send queued watchlist alerts.

    Claims are written by a worker thread, which cannot touch the event loop,
    so alerts are left on a Redis list and picked up here.
    """
    target = config.TELEGRAM_ALLOWED_USER or config.TELEGRAM_CHANNEL
    if not target:
        return
    while True:
        try:
            items = await asyncio.to_thread(watch.take_alerts, 5)
            for item in items:
                await send(str(target), watch.as_message(item))
        except Exception as exc:
            log.warning("alert send failed: %s", str(exc)[:120])
        await asyncio.sleep(20)


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
    _app.add_handler(CommandHandler("watch", cmd_watch))
    _app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    _app.add_handler(CommandHandler("watching", cmd_watching))
    _app.add_handler(CommandHandler("stats", cmd_stats))
    _app.add_handler(CommandHandler("merges", cmd_merges))
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
                BotCommand("watch", "Tell me when a new link touches a name"),
                BotCommand("unwatch", "Stop following a name"),
                BotCommand("watching", "List the names being followed"),
                BotCommand("stats", "Totals and machine load"),
                BotCommand("merges", "Duplicate names waiting for a decision"),
                BotCommand("status", "Show service status"),
            ])
        except Exception as exc:
            log.warning("command menu not set: %s", str(exc)[:80])
        db.activity("telegram", "bot online")
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        asyncio.create_task(alert_loop())
        while True:
            await asyncio.sleep(60)
