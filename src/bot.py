"""
Polymarket Research Bot — Telegram Command Handler
Runs alongside the scheduled research loop.

Commands:
  /start       — Welcome message
  /status      — Bot status
  /top         — Top edge markets right now (55-80% YES)
  /no          — Strong NO opportunities (<30% YES)
  /scan        — Trigger a fresh research run
  /help        — Full command list
"""
import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

from config import get_config
from scraper import PolymarketScraper
from researcher import Researcher, send_telegram_alert
from analyzer import Analyzer

logger = logging.getLogger(__name__)


def _authorized(update: Update) -> bool:
    raw = os.getenv("TELEGRAM_CHAT_ID", "0")
    try:
        allowed = int(raw)
    except ValueError:
        return False
    return allowed != 0 and update.effective_chat.id == allowed


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "<b>Polymarket Research Bot</b>\n\n"
        "Monitors prediction markets and finds pricing inefficiencies.\n\n"
        "/top — Edge zone markets (55-80% YES, best opportunity)\n"
        "/no — Strong NO opportunities (&lt;30% YES)\n"
        "/scan — Run fresh research cycle now\n"
        "/status — Bot status\n"
        "/help — Full command list",
        parse_mode='HTML'
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    config = get_config()
    groq_ok = "✅" if config.groq_api_key else "❌ missing"
    tg_ok = "✅" if config.telegram_bot_token else "❌ missing"
    await update.message.reply_text(
        "<b>Polymarket Bot Status</b>\n\n"
        f"Groq AI: {groq_ok}\n"
        f"Telegram: {tg_ok}\n"
        f"Min volume: ${config.min_volume:,.0f}\n"
        f"Max markets/run: {config.max_markets_per_run}\n"
        f"Alerts: {'on' if config.enable_alerts else 'off'}",
        parse_mode='HTML'
    )


async def _fetch_live_markets(limit: int = 100):
    """Shared helper — scrape markets and return sorted list."""
    config = get_config()
    async with PolymarketScraper(config) as scraper:
        markets = await scraper.scrape_markets(limit=limit)
    filtered = [m for m in markets if m.get("volume", 0) >= 50000]
    return sorted(filtered, key=lambda x: x.get("volume_24hr", 0), reverse=True)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top edge markets (55-80% YES probability)."""
    if not _authorized(update):
        return
    await update.message.reply_text("Fetching live markets...")
    try:
        markets = await _fetch_live_markets(200)
        edge = [m for m in markets if 0.55 <= m.get("probability", 0) <= 0.80][:10]
        if not edge:
            await update.message.reply_text("No edge markets found right now (55-80% YES).")
            return
        msg = "<b>Edge Zone Markets — 55-80% YES</b>\n<i>Highest mispricing potential</i>\n\n"
        for m in edge:
            prob = m.get("probability", 0) * 100
            vol = m.get("volume_24hr", 0)
            end = m.get("end_date", "")[:10] if m.get("end_date") else "?"
            q = m.get("question", "")[:60]
            url = m.get("url", "")
            msg += f"<b>{prob:.0f}% YES</b> | Vol 24h: ${vol:,.0f} | Ends: {end}\n"
            msg += f"<a href='{url}'>{q}</a>\n\n"
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"cmd_top error: {e}")
        await update.message.reply_text("Error fetching markets. Try again.")


async def cmd_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show strong NO opportunities (<30% YES)."""
    if not _authorized(update):
        return
    await update.message.reply_text("Fetching NO opportunities...")
    try:
        markets = await _fetch_live_markets(200)
        no_mkts = [m for m in markets if m.get("probability", 0) < 0.30][:8]
        if not no_mkts:
            await update.message.reply_text("No strong NO opportunities right now.")
            return
        msg = "<b>NO Opportunities — &lt;30% YES</b>\n<i>Buy NO tokens for contrarian edge</i>\n\n"
        for m in no_mkts:
            prob = m.get("probability", 0) * 100
            no_price = (1 - m.get("probability", 0)) * 100
            vol = m.get("volume", 0)
            end = m.get("end_date", "")[:10] if m.get("end_date") else "?"
            q = m.get("question", "")[:60]
            url = m.get("url", "")
            msg += f"<b>{prob:.0f}% YES → {no_price:.0f}% NO</b> | Vol: ${vol:,.0f} | Ends: {end}\n"
            msg += f"<a href='{url}'>{q}</a>\n\n"
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"cmd_no error: {e}")
        await update.message.reply_text("Error fetching markets.")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger a full research + alert cycle."""
    if not _authorized(update):
        return
    await update.message.reply_text("Starting fresh research cycle...")
    try:
        config = get_config()
        async with PolymarketScraper(config) as scraper:
            markets = await scraper.scrape_markets(limit=200)
        filtered = [m for m in markets if m.get("volume", 0) >= config.min_volume]
        sorted_mkts = sorted(filtered, key=lambda x: x.get("volume", 0), reverse=True)[:50]
        researcher = Researcher(config)
        analyzer = Analyzer(config)
        results = []
        for market in sorted_mkts:
            research = await researcher.research_market(market, use_cache=False)
            analysis = analyzer.analyze_market(market, research)
            results.append({**market, "insights": research.get("insights", {}), "analysis": analysis})
            await asyncio.sleep(0.5)
        if config.enable_alerts:
            await send_telegram_alert(config, results)
        edge = [m for m in results if 0.55 <= m.get("probability", 0) <= 0.80]
        await update.message.reply_text(
            f"Research complete.\n"
            f"Scanned: {len(results)} markets\n"
            f"Edge zone (55-80%): {len(edge)}\n"
            f"Alerts sent: {'yes' if config.enable_alerts else 'no'}"
        )
    except Exception as e:
        logger.error(f"cmd_scan error: {e}")
        await update.message.reply_text(f"Scan failed: {str(e)[:100]}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "<b>Polymarket Bot Commands</b>\n\n"
        "/top — Edge zone markets (55-80% YES)\n"
        "/no — Strong NO opportunities (&lt;30% YES)\n"
        "/scan — Run fresh AI research cycle\n"
        "/status — Bot configuration status\n"
        "/help — This message\n\n"
        "<i>Alerts sent automatically every hour via scheduler.</i>",
        parse_mode='HTML'
    )


async def main():
    """Start the Polymarket command bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        return

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("no",     cmd_no))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("help",   cmd_help))

    logger.info("Polymarket bot started")
    async with app:
        await app.initialize()
        await app.start()

        commands = [
            BotCommand("top",    "Edge zone markets (55-80% YES)"),
            BotCommand("no",     "Strong NO opportunities (<30%)"),
            BotCommand("scan",   "Run fresh research now"),
            BotCommand("status", "Bot status"),
            BotCommand("help",   "Command list"),
        ]
        await app.bot.set_my_commands(commands)

        await app.updater.start_polling()
        while True:
            await asyncio.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    asyncio.run(main())
