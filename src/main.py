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

    # Ensure data directories exist
    data_dir = Path("data")
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
            
            # Sort by volume and take top N
            sorted_markets = sorted(filtered, key=lambda x: x.get("volume", 0), reverse=True)
            top_markets = sorted_markets
            
            # Research each market
            research_results = []
            for market in top_markets:
                logger.info(f"Researching: {market.get('question', 'N/A')[:50]}...")
                
                # Combine market data with research
                research = await researcher.research_market(market)
                market_with_research = {**market, "insights": research.get("insights", {})}
                research_results.append(market_with_research)
                
                # Brief delay to be nice to APIs
                await asyncio.sleep(0.5)
            
            logger.info(f"Researched {len(research_results)} markets")
            
            # Send Telegram alert if configured
            if config.enable_alerts:
                await send_telegram_alert(config, research_results)
            
            # Categorize markets
            green_markets = [m for m in research_results if m.get("probability", 0) >= 0.70 and m.get("probability", 0) <= 0.90]  # 70-90% = good value
            yellow_markets = [m for m in research_results if 0.60 < m.get("probability", 0) <= 0.80]  # 60-80% = likely
            red_markets = [m for m in research_results if m.get("probability", 0) <= 0.40]  # <40% = likely NO
            
            # Print summary
            print("\n" + "="*50)
            print("🎯 POLYMARKET RESEARCH RESULTS")
            print("="*50)
            
            # GREEN - HIGH PROBABILITY (BUY YES)
            if green_markets:
                print("\n🟢 SURE BETS (BUY YES - >80%):")
                print("-" * 40)
                for m in sorted(green_markets, key=lambda x: x.get("probability", 0), reverse=True):
                    prob = m.get("probability", 0) * 100
                    print(f"   ✅ {prob:.0f}% | ${m.get('volume', 0):,.0f}")
                    print(f"      {m.get('question', '')[:55]}")
                    print(f"      🔗 {m.get('url', '')[:50]}")
            
            # YELLOW - LIKELY
            if yellow_markets:
                print(f"\n🟡 LIKELY ({len(yellow_markets)} markets)")
                for m in sorted(yellow_markets, key=lambda x: x.get("probability", 0), reverse=True)[:3]:
                    prob = m.get("probability", 0) * 100
                    print(f"   {prob:.0f}% | {m.get('question', '')[:50]}...")
            
            print("\n" + "="*50)
            
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
