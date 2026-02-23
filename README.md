# Polymarket Research Bot

An automated research bot for analyzing Polymarket prediction markets using MCP browser control and AI-powered analysis.

## Features

- Automated market data collection using Playwright MCP
- Real-time market analysis and sentiment tracking
- AI-driven research and insights
- Docker containerization for easy deployment
- Secure configuration management

## Project Structure

```
polymarket-research/
├── src/
│   ├── main.py           # Main entry point
│   ├── config.py         # Configuration management
│   ├── researcher.py     # Research logic
│   ├── scraper.py        # Browser automation
│   └── analyzer.py       # Data analysis
├── data/
│   ├── raw/             # Raw scraped data
│   ├── processed/       # Processed data
│   └── cache/          # Cached results
├── tests/
│   └── test_scraper.py
├── .env.example         # Environment template
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker image definition
├── docker-compose.yml  # Docker composition
├── .dockerignore      # Docker ignore rules
├── .gitignore         # Git ignore rules
└── README.md          # This file
```

## Setup

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in your credentials
3. Install dependencies: `pip install -r requirements.txt`
4. Run the bot: `python src/main.py`

## Docker Deployment

```bash
# Build the image
docker build -t polymarket-research .

# Run with docker-compose
docker-compose up -d
```

## Security

- Never commit `.env` files
- Use environment variables for sensitive data
- Rotate API keys regularly
- Enable 2FA on all accounts

## License

MIT