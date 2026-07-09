# CryptoBot — Agent Guide

## First thing every session
Read `session_log/LATEST.md` — contains full session history, all decisions, bugs, and next steps.

## Project
Telegram-controlled crypto trading bot. User pastes signals into a Telegram bot PM, which parses them and executes trades on Bybit via CCXT. Runs persistently on Termux (Android) in tmux.

## Files & Ownership

| File | Purpose |
|------|---------|
| `bot.py` | Telegram bot — long-polling loop, message/callback routing, inline keyboards |
| `executor.py` | CCXT Bybit wrapper — market entry, trigger TP orders, SL management, pre-flight checks |
| `logic.py` | Shared business logic — preview, execute, positions, history, watch worker |
| `signal_parser.py` | Signal parser — NFKC normalization, regex extraction for symbol/direction/TPs/SL/leverage/risk |
| `trades_logger.py` | JSON trade logging to `trades.json` |
| `TERMUX.md` | Termux deployment + tmux setup instructions |
| `session_log/LATEST.md` | Detailed session history |

**Key:** `parser.py` was renamed to `signal_parser.py` because Python's stdlib has a `parser` module that silently shadows local files.

## Critical Architecture

### Entrypoint
`bot.py` — starts a polling loop. Must be run in tmux on Termux for persistence.

### Position sizing (counterintuitive)
`executor.py:calculate_qty()` uses **SL distance**, not leverage:
```
qty = (wallet * risk%) / |entry - sl|
```
Leverage only affects margin requirement. This was changed from a leverage-based formula that caused risk to be ~2.5x intended.

### TP mechanics
- Each TP is a conditional reduce-only limit order triggered by **MarkPrice** (not LastPrice)
- `tpSlType: 'Partial'` links TPs to the position — when SL hits, all TPs auto-cancel
- Last TP always gets `1.0 - sum(previous)` so 100% of position is covered
- TP5 (moon bag) has no order — held manually

### Balance
Uses `free` balance (not `total`) for position sizing. `total` includes locked margin from open positions and inflated risk. Refreshed every preview/execute.

## Signal Format Support
Parser handles these variations automatically via NFKC normalization:

| Field | Format A | Format B |
|-------|----------|----------|
| Symbol | `$ORDI/USDT (LONG)` | `⚡️⚡️HYPE/USDT⚡️⚡️` |
| Direction | In parentheses | Standalone `LONG` / `SHORT` line |
| SL | `Stop Loss:\n$3.360` | `Stoploss = 71.06` |
| Leverage | `50x` | `Leverage: 50X` |
| TP distance | `TP 1: $3.655` | `TP1: 0.01225` |

## Running

```bash
# Termux only (terminal-based, no GUI)
tmux new -s cryptobot
cd ~/tradingbot_v2
python bot.py
# Ctrl+B, D to detach
# tmux attach -t cryptobot to reattach
```

No `trade.py` (CLI) exists — all interaction via Telegram inline buttons.

## Environment (`.env` — gitignored)
```
BYBIT_API_KEY=
BYBIT_API_SECRET=
BYBIT_TESTNET=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
RISK_PER_TRADE=1
```

## Key Gotchas

- **`signal_parser.py`** name is deliberate — `parser.py` conflicts with stdlib
- **Risk % from signal text** (`Use 3% margin`) overrides `.env` `RISK_PER_TRADE`. If missing, falls back to env var (default 1%).
- **SL validation** pre-flight checks: LONG requires SL < entry, SHORT requires SL > entry
- **One position at a time** — pre-flight rejects if position already open for that symbol
- **`set_leverage` can fail** — wrapped in try/except; leverage may already be set correctly
- **`/watch` spawns daemon thread** — auto-moves SL to entry when TP1 fills (~35% qty reduction detected)
- **Telegram only responds to authorized `TELEGRAM_CHAT_ID`** — other chats ignored
- **Bybit API key** must have Contract Trading + USDT perpetual permissions
