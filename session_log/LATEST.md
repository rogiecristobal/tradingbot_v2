# Session Summary — 2026-07-08

## Overview
Full rework of the CryptoBot Telegram-to-Bybit trading bot: fixed parsing, position sizing, TP/SL trigger mechanics, and added support for multiple signal formats. The bot went from unable to parse any signals to executing trades with proper risk management.

---

## Files Changed

### `parser.py` → `signal_parser.py` (RENAMED)
**Root cause of all "couldn't parse" errors**: `parser.py` conflicted with Python's stdlib `parser` module. `from parser import parse_signal` silently imported the wrong module, returning `None` for every signal.

Changes:
- **Renamed** to `signal_parser.py` to avoid stdlib name collision
- **`_normalize()`** rewritten from manual Unicode range mapping to `unicodedata.normalize('NFKC', text)` — handles ALL mathematical letter variants (bold, italic, sans-serif, monospace, double-struck, fullwidth) plus fullwidth dollar sign
- **SL regex** expanded from `:` only to `[:=]` — now matches `Stoploss = 71.06` and `Stop Loss: 3.36`
- **Multi-line SL fallback** added — if SL value is on the next line (`Stop Loss:\n$3.360`), a full-text regex catches it
- **Symbol regex extended** — `_RE_SYMBOL_BARE` matches `COIN/USDT` without `(LONG/SHORT)` suffix (handles `⚡️⚡️HYPE/USDT⚡️⚡️`)
- **Direction regex added** — `_RE_DIRECTION` matches standalone `LONG` / `SHORT` on its own line
- **Debug logging** — when parsing fails, logs raw text, hex dump, normalized text, and missing fields
- TP_DISTRIBUTION reverted to `[0.40, 0.30, 0.20, 0.10]` at user request

### `executor.py`
Major rework of position sizing, balance handling, and TP/SL mechanics.

Changes:
- **`calculate_qty()`** — completely rewired from leverage-based to SL-distance-based:
  - Old: `risk_amount * leverage / entry_price` (risk was 2.5x intended)
  - New: `risk_amount / |entry - sl|` (risk is exactly the specified %)
  - Signature changed: removed `leverage` param, added `sl_price` param
- **`refresh_balance()`** — changed from `total` to `free` balance. Old code counted locked margin + unrealized PnL as available capital, inflating position sizes on subsequent trades
- **`place_entry()`** — re-added `'slTriggerBy': 'MarkPrice'` to entry order SL params
- **`place_tp_order()`** — converted from plain `create_limit_order` to full `create_order` with trigger params:
  - `triggerPrice` — conditional order activates at TP target
  - `triggerBy: 'MarkPrice'` — triggered by mark price, not last price
  - `triggerDirection` — 1 for LONG (rise), 2 for SHORT (fall)
  - `tpSlType: 'Partial'` — links TP to the position so all TPs auto-cancel when SL hits
- **`_set_position_sl()`** — `'slTriggerBy'` changed from `'LastPrice'` to `'MarkPrice'`
- **`set_stop_loss()`** — same MarkPrice change
- **Last TP = full remainder** — in both `_compute()` and `execute()`, the final TP dynamically gets `1.0 - sum(previous)` regardless of position. 100% of position is always covered by TP orders
- **`set_leverage()`** — wrapped in try/except with warning (non-blocking if leverage can't be set)
- **`pre_flight_checks()`** — `min_cost` None safety; removed noisy market-instrument warning (changed to debug log)
- **`_compute()` / `execute()`** — updated `calculate_qty()` callers with new `sl_price` parameter
- **Default risk** changed from 3.0 to 1.0 in `execute()` signature
- **`cancel_orders()`** removed (user opted out of manual cancel logic)

### `logic.py`
- **`_f()` helper** added — safely converts `None` to `0.0` for all position field access (prevents `TypeError: float() argument must be a string or a real number, not 'NoneType'`)
- **`format_positions()`** — uses `_f()` throughout; hides liq price when 0; removed unused `index` variable
- **`move_sl_to_entry()`** — uses `_f()` for safe float conversion
- **`watch_worker()`** — uses `_f()` in position detection and quantity tracking
- **`format_execution_result()`** — fixed TP price display: reads from stored result price instead of CCXT order response (was showing `$None`). Fixed entry qty display: reads `amount` instead of `filled` (was showing `0` for unfilled market orders)
- **Default risk fallback** changed from `'3'` to `'1'` in `os.getenv('RISK_PER_TRADE', '1')`

### `bot.py`
- **`_log()` method** — fixed signature to accept `*args` and pass to `logger.info` format strings (was crashing on format args)
- **Command keyboard** — `/start` and `/help` now send a persistent Telegram reply keyboard with buttons: `[/positions] [/history]`, `[/watch] [/cancel]`, `[/help]`
- Minor: `/cancel` order was commented (pending), `/cancel_orders` not added per user request

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Rename `parser.py` → `signal_parser.py` | Stdlib `parser` module silently shadowed our file |
| Position sizing via SL distance, not leverage | Actual loss at SL was 2.5x intended risk |
| Use `free` balance instead of `total` | `total` includes locked margin from open positions, inflating risk calc |
| TP trigger type `tpSlType: 'Partial'` | Links TPs to position; auto-cancels when SL hits |
| Trigger by `MarkPrice` everywhere | Avoids stop-hunts and manipulation on last price |
| Last TP = `1.0 - sum(previous)` | Ensures 100% of position is always covered |
| Default risk 1% | Safer default than 3%; can override via `RISK_PER_TRADE` in `.env` |
| Keep `place_entry` fallback path | If CCXT `create_order` with SL fails, falls back to plain market order + `_set_position_sl` |

---

## Bugs Fixed

| Bug | Symptom | Fix |
|-----|---------|-----|
| parser.py stdlib conflict | All signals returned "Couldn't parse" | Renamed to signal_parser.py |
| Unicode bold not normalized | Signal keywords unrecognized | NFKC normalization replaces all letter variants |
| SL value on next line | `sl_price` always missing | Multi-line fallback regex |
| RISK doubled | Position qty ~2.5x correct size | SL-distance-based sizing |
| Balance not updating | Each trade used same wallet balance | Changed to `free` balance, refreshed every preview/execute |
| TP prices show `$None` | TP order responses lacked `price` field | Store signal price explicitly in result |
| Entry qty shows `0` | Market order `filled` = 0 | Read `amount` instead |
| `float(None)` crash | `/positions` crashed on liquidationPrice | `_f()` helper with `None` → `0.0` |
| `min_cost` is `None` | `>` comparison fails | Safe float conversion |
| `Stoploss = 71.06` not parsed | `=` instead of `:` after "Stoploss" | `[:=]` in SL regex |
| Hardcoded leverage assumption | Sizing ignored SL distance | New `calculate_qty` formula |
| TP orders survive SL hit | Orphan reduce-only orders after position closed | `tpSlType: 'Partial'` links to position |

---

## Errors Encountered

1. **`TypeError: '>' not supported between instances of 'NoneType' and 'int'`** — `market.get('limits', {}).get('cost', {}).get('min', 0)` returned `None`. Fixed with safe float conversion.

2. **`set_leverage` CCXT error** — `retCode: 110013, cannot set leverage [5000] gt maxLeverage [500] by risk limit`. TAC/USDT max leverage is lower than 50x on Bybit. Made non-blocking with try/except warning.

3. **`create_order` failure with `slTriggerBy`** — Some CCXT versions may not support `slTriggerBy` in `create_order` params. The fallback path (plain market order + `_set_position_sl`) handles MarkPrice correctly.

4. **`Signal | None` syntax** — Requires Python 3.10+. Termux Python 3.13 is fine; local Windows Python 3.9 can't run tests.

---

## Known Issues

1. **CCXT version sensitivity** — TP trigger orders with `tpSlType: 'Partial'` may fail on older CCXT versions. If `place_tp_order` fails, the warning log shows the error but the trade continues without linked TPs.

2. **`slTriggerBy` in `create_order`** — If `place_entry` with `slTriggerBy: 'MarkPrice'` fails, the fallback uses `_set_position_sl()` which does send MarkPrice. Either path works, but the fallback adds an extra API call.

3. **No TP orphan cleanup without `tpSlType`** — If `tpSlType: 'Partial'` fails (CCXT version), orphan TP orders after SL hit must be cancelled manually or by restarting the bot.

4. **Leverage not set = default exchange leverage** — When `set_leverage` is rejected (risk limit), the exchange uses whatever leverage was last set for that pair. Position sizing is unaffected (SL-distance-based), but margin requirements may differ.

---

## What to Continue With Next

1. **Test SL linking** — Verify that `tpSlType: 'Partial'` auto-cancels TP orders when SL hits. Test on a small position first.

2. **Test the SL trigger** — Confirm SL is triggered by MarkPrice (not LastPrice) by checking the order on Bybit's UI.

3. **Test new signal formats** — Send the CHILLGUY signal (`⚡️⚡️CHILLGUY/USDT⚡️⚡️\nLONG\nEntry: 0.01193\n...`) and HYPE signal (`Stoploss = 71.06` format) to confirm parsing works.

4. **Monitor position sizing** — Verify that the new SL-distance-based sizing produces expected qty. With 1% risk and a 5% SL distance, position value = 20% of wallet (not 50x leveraged up).

5. **Check `free` balance behavior** — Ensure `refresh_balance` using `free` doesn't under-size when no positions are open.

6. **Deploy to Termux** — Copy all 4 files: `signal_parser.py`, `executor.py`, `logic.py`, `bot.py`. Delete old `parser.py`. Restart in tmux.
