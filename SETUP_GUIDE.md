# Polymarket Research Bot - Setup Guide

## Prerequisites

1. **Telegram Bot Setup**
   - Talk to @BotFather on Telegram
   - Send `/newbot` and follow instructions
   - Save your bot token
   - Add your bot to a group or start a chat with it
   - Get your chat ID (can be found via `https://api.telegram.org/bot{TOKEN}/getUpdates`)

2. **Groq API Key**
   - Sign up at https://console.groq.com/
   - Create an API key
   - Copy the key for use in .env

## Setup Instructions

1. **Copy Environment Template**
   ```bash
   cp .env.example .env
   ```

2. **Fill in .env File**
   ```bash
   # Edit .env with your actual credentials
   TELEGRAM_BOT_TOKEN=your_actual_bot_token_here
   TELEGRAM_CHAT_ID=your_actual_chat_id_here
   GROQ_API_KEY=your_actual_groq_api_key_here
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Test the Bot**
   ```bash
   python src/main.py
   ```

## Docker Setup

```bash
# Build the image
docker build -t polymarket-research .

# Run with environment variables
docker run --env-file .env polymarket-research
```

## Troubleshooting

### Telegram Not Working
- Verify your bot token is correct
- Ensure your bot is added to the chat
- Check that your chat ID is correct
- Test with a simple curl request:
  ```bash
  curl "https://api.telegram.org/botYOUR_TOKEN/sendMessage" -d "chat_id=YOUR_CHAT_ID&text=Test"
  ```

### Groq API Issues
- Verify your API key is correct
- Check your rate limits
- Ensure you have internet connectivity

## Security Notes

- Never commit `.env` files to git
- Use strong, unique API keys
- Rotate keys regularly
- Enable 2FA on all accounts