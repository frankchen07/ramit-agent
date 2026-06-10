"""Standalone Telegram bot for Ramit agent."""
import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.agent import build_graph, chat
from src.tools import load_knowledge
import src.invite_system as invite_system

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_UNAUTHORIZED_MSG = "You need an invite code to use this bot. Use: /start <code>"


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if await invite_system.is_authorized(user_id):
        await update.message.reply_text("You're already set up. Ask me about money.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(_UNAUTHORIZED_MSG)
        return

    code = args[0].strip()
    if await invite_system.redeem_code(user_id, code):
        await update.message.reply_text(
            "You're in. Ask me anything about money — budgeting, investing, negotiating, all of it."
        )
    else:
        await update.message.reply_text("That code is invalid or already used.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if not await invite_system.is_authorized(user_id):
        await update.message.reply_text(_UNAUTHORIZED_MSG)
        return

    graph = context.application.bot_data["graph"]
    chat_id = update.effective_chat.id
    text = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        response = await chat(graph, chat_id, text)
    except Exception:
        logger.exception("Agent error for chat_id=%s", chat_id)
        response = "Something went wrong on my end. Try again."

    await update.message.reply_text(response)


async def post_init(app: Application) -> None:
    logger.info("Pre-warming knowledge index...")
    await asyncio.to_thread(load_knowledge)

    logger.info("Building agent graph...")
    db_url = os.environ["DATABASE_URL"]
    graph, pool = await build_graph(db_url)
    app.bot_data["graph"] = graph

    logger.info("Setting up invite system...")
    await invite_system.setup(pool)

    logger.info("Ramit agent ready.")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Starting Ramit bot (long polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
