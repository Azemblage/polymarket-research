"""
Polymarket Research Bot - Main Entry Point
"""
import asyncio
import logging
from pathlib import Path

from config import get_config
from scraper import PolymarketScraper
from researcher import Researcher, send_telegram_alert
from analyzer import Analyzer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main application entry point"""
    config = get_config()

    # Validate configuration
    errors = config.validate()
    if errors:
        for error in errors:
            logger.warning(f"Configuration: {error}")
        logger.info("Continuing anyway - alerts disabled if no Telegram config")

    # Ensure data directories exist (anchored to script location)
    data_dir = Path(__file__).parent.parent / "data"
    for subdir in ["raw", "processed", "cache"]:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)

    logger.info("Starting Polymarket Research Bot")
    logger.info(f"Min volume: ${config.min_volume:,.0f}")

    try:
        async with PolymarketScraper(config) as scraper:
            researcher = Researcher(config)
            
            # Run once (not loop) - can be changed to loop for continuous
            logger.info("Starting research cycle...")
            
            # Scrape market data
            markets = await scraper.scrape_markets(limit=200)
            logger.info(f"Scraped {len(markets)} markets")
            
            # Filter by volume
            filtered = [m for m in markets if m.get("volume", 0) >= config.min_volume]
            logger.info(f"Filtered to {len(filtered)} markets with volume >= ${config.min_volume:,.0f}")
            
            # Sort by volume and take top N (more variety)
            sorted_markets = sorted(filtered, key=lambda x: x.get("volume", 0), reverse=True)
            top_markets = sorted_markets[:50]  # Process top 50 markets for variety
            
            # Research each market with TTL-aware cache
            analyzer = Analyzer(config)
            research_results = []
            for market in top_markets:
                logger.info(f"Researching: {market.get('question', 'N/A')[:50]}...")
                research = await researcher.research_market(market, use_cache=True)
                analysis = analyzer.analyze_market(market, research)
                market_with_research = {
                    **market,
                    "insights": research.get("insights", {}),
                    "analysis": analysis,
                }
                research_results.append(market_with_research)
                await asyncio.sleep(0.5)  # respect Groq rate limits

            logger.info(f"Researched {len(research_results)} markets")

            # Send Telegram alert if configured
            if config.enable_alerts:
                await send_telegram_alert(config, research_results)

            # Console summary — edge zone first, then contrarian, then near-resolved
            edge_markets = [m for m in research_results if 0.55 <= m.get("probability", 0) <= 0.80]
            no_markets = [m for m in research_results if m.get("probability", 0) < 0.30]
            resolved_markets = [m for m in research_results if m.get("probability", 0) > 0.90]

            print("\n" + "="*50)
            print("POLYMARKET RESEARCH RESULTS")
            print("="*50)

            print(f"\nEDGE ZONE 55-80% ({len(edge_markets)} markets — best potential):")
            print("-" * 40)
            for m in sorted(edge_markets, key=lambda x: x.get("volume_24hr", 0), reverse=True)[:10]:
                prob = m.get("probability", 0) * 100
                action = m.get("analysis", {}).get("recommendation", {}).get("action", "")
                end_date = m.get("end_date", "?")[:10] if m.get("end_date") else "?"
                print(f"   {prob:.0f}% | {action} | Ends: {end_date} | {m.get('question', '')[:55]}")

            if no_markets:
                print(f"\nNO OPPORTUNITIES <30% ({len(no_markets)} markets):")
                for m in sorted(no_markets, key=lambda x: x.get("volume", 0), reverse=True)[:5]:
                    prob = m.get("probability", 0) * 100
                    end_date = m.get("end_date", "?")[:10] if m.get("end_date") else "?"
                    print(f"   {prob:.0f}% YES | Ends: {end_date} | {m.get('question', '')[:55]}")

            if resolved_markets:
                print(f"\nNEAR-RESOLVED >90% (low edge — {len(resolved_markets)} markets):")
                for m in sorted(resolved_markets, key=lambda x: x.get("probability", 0), reverse=True)[:3]:
                    prob = m.get("probability", 0) * 100
                    print(f"   {prob:.0f}% — {m.get('question', '')[:55]}")

            print("\n" + "="*50)
            
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1

    return 0


async def run_with_bot():
    """
    Run both the research scheduler AND the Telegram command bot concurrently.
    Used when deployed (GitHub Actions runs main() directly for one-shot runs).
    """
    from bot import main as bot_main
    await asyncio.gather(
        main(),
        bot_main(),
    )


if __name__ == "__main__":
    import sys
    if "--bot" in sys.argv:
        # Run research loop + Telegram bot together
        asyncio.run(run_with_bot())
    else:
        # One-shot research run (default for GitHub Actions)
        exit_code = asyncio.run(main())
        exit(exit_code)
