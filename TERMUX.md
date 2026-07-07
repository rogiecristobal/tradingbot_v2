# Termux Setup for CryptoBot

## 1. Install Termux
- Download from **F-Droid** (recommended) or GitHub Releases
- **DO NOT** use the Play Store version (it's outdated)

## 2. Install Python & Git
```bash
pkg update && pkg upgrade
pkg install python git
```

## 3. Get the Bot Files
```bash
cd ~
git clone <your-repo-url> tradingbot_v2
cd tradingbot_v2
```

## 4. Install Dependencies
```bash
pip install -r requirements.txt
```

## 5. Configure .env
```bash
nano .env
```

Set these values:
```
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret
BYBIT_TESTNET=false
RISK_PER_TRADE=3
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## 6. Run the Bot (in tmux — stays running in background)
```bash
tmux new -s cryptobot
python bot.py
```

- **Detach** (bot keeps running): `Ctrl+B`, then `D`
- **Re-attach**: `tmux attach -t cryptobot`
- **Stop**: Re-attach then `Ctrl+C`

## 7. How to Use (Telegram)

| You send... | Bot responds... |
|---|---|
| Signal text | Preview with **[Execute] [Cancel]** buttons |
| Tap **Execute** | Trade placed on Bybit, confirmation shown |
| Tap **Cancel** | Preview dismissed |
| `/positions` | Live positions + **[Move SL to entry]** button |
| `/history` | Trade history from logs |
| `/watch` | Auto-move SL to entry after TP1 (background thread) |
| `/cancel` | Cancel pending trade |
| `/help` | Command list |

## 8. Bybit API Key Setup
1. Go to Bybit → **API Management** → **Create API Key**
2. Enable: **Read-Write**
3. Enable: **Contract Trading** and **USDT perpetual**
4. Save the API Key and Secret to `.env`
