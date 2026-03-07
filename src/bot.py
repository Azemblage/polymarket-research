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
from researcher import Researcher, send_telegram_alert, _build_market_card, _fmt_vol
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


def _enrich_with_cache(markets: list) -> list:
    """
    Merge cached AI research into each market dict (if available).
    Returns list sorted by AI edge descending; unresearched markets go last.
    """
    import json
    from pathlib import Path
    cache_dir = Path(__file__).parent.parent / "data" / "cache"
    enriched = []
    for m in markets:
        market_id = m.get("id", "")
        cache_file = cache_dir / f"research_{market_id}.json"
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    research = json.load(f)
                m = {**m, "insights": research.get("insights", {}), "_has_ai": True}
            except Exception:
                m = {**m, "_has_ai": False}
        else:
            m = {**m, "_has_ai": False}
        enriched.append(m)

    def sort_key(m):
        groq = m.get("insights", {}).get("groq_analysis", {})
        edge = abs(groq.get("edge", 0))
        has_ai = 1 if m.get("_has_ai") else 0
        return (has_ai, edge)

    return sorted(enriched, key=sort_key, reverse=True)


def _is_high_confidence(m: dict, min_edge: float = 0.05, min_conf: float = 0.60) -> bool:
    groq = m.get("insights", {}).get("groq_analysis", {})
    return (
        abs(groq.get("edge", 0)) > min_edge
        and groq.get("confidence", 0) > min_conf
        and groq.get("direction", "HOLD") != "HOLD"
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top AI-backed BUY YES opportunities, falling back to raw data if no cache."""
    if not _authorized(update):
        return
    await update.message.reply_text("Fetching markets — checking AI research cache...")
    try:
        import html as html_lib
        markets = await _fetch_live_markets(200)
        enriched = _enrich_with_cache(markets)

        # Priority 1: AI-backed high-confidence BUY YES
        ai_plays = [
            m for m in enriched
            if _is_high_confidence(m)
            and m.get("insights", {}).get("groq_analysis", {}).get("direction") == "BUY_YES"
        ][:8]

        divider = "<code>─────────────────────────────</code>"

        if ai_plays:
            lines = [
                "🎯 <b>Top BUY YES Plays — AI Backed</b>",
                f"<i>{len(ai_plays)} high-confidence opportunities from last scan</i>",
                divider, "",
            ]
            for m in ai_plays:
                lines.append(_build_market_card(m))
                lines.append("")
            lines.append(divider)
            lines.append("<i>Run /scan to refresh AI analysis. /no for BUY NO plays.</i>")
        else:
            # Fallback: raw edge zone with disclaimer
            raw_edge = [m for m in enriched if 0.55 <= m.get("probability", 0) <= 0.80][:10]
            if not raw_edge:
                await update.message.reply_text("No edge markets found right now (55-80% YES).")
                return
            lines = [
                "🎯 <b>Edge Zone Markets — 55–80% YES</b>",
                "<i>No AI analysis cached yet — run /scan first for high-confidence signals</i>",
                divider, "",
            ]
            for m in raw_edge:
                prob = m.get("probability", 0)
                vol = _fmt_vol(m.get("volume_24hr", 0))
                end = (m.get("end_date", "") or "")[:10] or "?"
                q = html_lib.escape(m.get("question", "")[:80])
                url = m.get("url", "")
                lines.append(f"<b><a href='{url}'>{q}</a></b>")
                lines.append(f"YES: <b>{prob:.0%}</b> | Vol 24h: {vol} | Ends: {end}")
                lines.append("")
            lines.append(divider)
            lines.append("<i>Run /scan for AI-backed signals with reasoning. /no for BUY NO plays.</i>")

        msg = "\n".join(lines)
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"cmd_top error: {e}")
        await update.message.reply_text("Error fetching markets. Try again.")


async def cmd_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show AI-backed BUY NO opportunities, falling back to raw <30% YES if no cache."""
    if not _authorized(update):
        return
    await update.message.reply_text("Fetching markets — checking AI research cache...")
    try:
        import html as html_lib
        markets = await _fetch_live_markets(200)
        enriched = _enrich_with_cache(markets)

        # Priority 1: AI-backed high-confidence BUY NO
        ai_plays = [
            m for m in enriched
            if _is_high_confidence(m)
            and m.get("insights", {}).get("groq_analysis", {}).get("direction") == "BUY_NO"
        ][:8]

        divider = "<code>─────────────────────────────</code>"

        if ai_plays:
            lines = [
                "🔴 <b>BUY NO Plays — AI Backed</b>",
                f"<i>{len(ai_plays)} high-confidence NO opportunities from last scan</i>",
                divider, "",
            ]
            for m in ai_plays:
                lines.append(_build_market_card(m))
                lines.append("")
            lines.append(divider)
            lines.append("<i>Run /scan to refresh AI analysis. /top for BUY YES plays.</i>")
        else:
            # Fallback: raw <30% YES with payout math
            raw_no = [m for m in enriched if m.get("probability", 0) < 0.30]
            raw_no.sort(key=lambda x: x.get("volume_24hr", x.get("volume", 0)), reverse=True)
            raw_no = raw_no[:8]
            if not raw_no:
                await update.message.reply_text("No strong NO opportunities right now.")
                return
            lines = [
                "🔴 <b>NO Signals — &lt;30% YES</b>",
                "<i>No AI analysis cached yet — run /scan first for evidence-backed signals</i>",
                divider, "",
            ]
            for m in raw_no:
                prob = m.get("probability", 0)
                no_cents = int((1 - prob) * 100)
                payout = round(1 / (1 - prob), 2) if prob < 1 else 0
                vol = _fmt_vol(m.get("volume_24hr", m.get("volume", 0)))
                end = (m.get("end_date", "") or "")[:10] or "?"
                q = html_lib.escape(m.get("question", "")[:80])
                url = m.get("url", "")
                lines.append(f"🔴 <b>BUY NO</b> — YES: {prob:.0%} | Buy NO at <b>{no_cents}¢</b> → pays $1.00")
                lines.append(f"<b><a href='{url}'>{q}</a></b>")
                lines.append(f"Vol 24h: {vol} | Ends: {end}")
                lines.append("")
            lines.append(divider)
            lines.append("<i>Run /scan for AI-backed signals with news reasoning. /top for BUY YES plays.</i>")

        msg = "\n".join(lines)
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
