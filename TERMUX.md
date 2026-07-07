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
On your phone, you have two options:

### Option A — Copy files manually
Use a USB cable or file-sharing app to copy the `CryptoBot` folder to your phone's storage, then in Termux:
```bash
cp -r /storage/emulated/0/CryptoBot ~/
cd ~/CryptoBot
```

### Option B — Use Git (if you push to a private repo)
```bash
cd ~
git clone <your-repo-url> CryptoBot
cd CryptoBot
```

## 4. Install Dependencies
```bash
pip install -r requirements.txt
```

## 5. Configure .env
Edit `.env` to match your Bybit credentials:
```bash
nano .env
```

Set these values:
```
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret
BYBIT_TESTNET=true
RISK_PER_TRADE=3
```

- **First time:** Keep `BYBIT_TESTNET=true` and test with play money
- **Live trading:** Change to `BYBIT_TESTNET=false` when you're ready

## 6. Run the Bot
```bash
cd ~/CryptoBot
python trade.py
```

## 7. How to Use (Quick Flow)
1. See a signal in your Telegram group
2. **Copy the entire signal text** (long-press → Copy)
3. Switch to Termux (the bot should be waiting)
4. **Long-press** in Termux to paste the text
5. Press **Enter**, then **Ctrl+D**
6. Review the parsed signal preview
7. Type `y` + Enter to execute the trade
8. Done — the position is open on Bybit

## 8. Keeping the Bot Open (Optional)
Instead of re-running `python trade.py` for each signal, you can keep it running:

```bash
# Run once, then paste new signals each time it prompts
python trade.py
```

Every time a trade completes, the script exits. Just run `python trade.py` again for the next signal.

## 9. Bybit API Key Setup
1. Go to Bybit → **API Management** → **Create API Key**
2. Enable: **Read-Write**
3. Enable: **Contract Trading**
4. Save the API Key and Secret to `.env`

## 10. Testnet (for testing)
1. Go to https://testnet.bybit.com
2. Create an account (separate from main Bybit)
3. Create API keys from testnet dashboard
4. Use those keys with `BYBIT_TESTNET=true`
5. Get free test USDT from the faucet
