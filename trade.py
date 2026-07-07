#!/usr/bin/env python3
import sys
import os
import json
import time
import urllib.request
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from parser import parse_signal
from executor import BybitExecutor
import trades_logger


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title: str):
    print("=" * 54)
    print(f"  {title}")
    print("=" * 54)


def wait_for_enter():
    input("\nPress Enter to continue...")


def fetch_signal_from_telegram() -> str | None:
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return None

    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        for update in reversed(data.get('result', [])):
            msg = update.get('message', {})
            if str(msg.get('chat', {}).get('id')) == chat_id:
                text = msg.get('text', '')
                if text and text.strip():
                    return text.strip()
        return None
    except Exception as e:
        logger.warning("Telegram fetch failed: %s", e)
        return None


def read_signal() -> str:
    print("Send the signal to your Telegram bot, then press Enter to fetch it...")
    print("(or type 'p' to paste manually)")
    print()
    ch = input("  [Enter=fetch  p=paste]: ").strip().lower()

    if ch == 'p':
        lines = []
        print()
        print("Paste the signal below, then Ctrl+D (Linux) or Ctrl+Z (Windows):")
        print()
        try:
            for line in sys.stdin:
                lines.append(line)
        except KeyboardInterrupt:
            print("\n\nCancelled.")
            return ''
        return ''.join(lines).strip()

    print("  Fetching from Telegram...")
    text = fetch_signal_from_telegram()
    if text:
        print("  ✓ Signal found!")
        return text
    print("  No signal found. Falling back to manual paste.")
    return read_signal()


def trade_flow(executor: BybitExecutor):
    raw = read_signal()
    if not raw:
        print("No input received.")
        return

    signal = parse_signal(raw)
    if signal is None:
        print()
        print("ERROR: Could not parse the signal. Verify the format:")
        print()
        print("  $SYMBOL/USDT (LONG)")
        print("  Entry: MARKET PRICE")
        print("  Take Profit Targets:")
        print("  TP 1: $0.1365")
        print("  TP 5: 🚀")
        print("  Stop Loss: $0.1260")
        print("  Leverage: 10x")
        print()
        return

    risk = signal.risk_pct if signal.risk_pct is not None else float(os.getenv('RISK_PER_TRADE', '3'))

    try:
        preview = executor.preview(signal, risk)
    except Exception as e:
        print(f"\n  ✗ Could not calculate trade preview: {e}")
        return

    clear_screen()
    print_header("Signal Preview — Verify Before Trading")
    print()

    print(f"  Pair:        {preview['symbol']:<12}  Direction: {preview['direction']}")
    print(f"  Entry:       ${preview['entry_price']:.6f}  ({signal.entry_type})")
    print(f"  Stop Loss:   ${preview['sl_price']:<10}")
    print(f"  Leverage:    {preview['leverage']}x")
    source = "from signal" if signal.risk_pct is not None else "from .env"
    print(f"  Risk:        {risk:.1f}% of wallet ({source})")
    print(f"  Balance:     ${preview['wallet_balance']:.2f}")
    print()
    print(f"  Position:")
    print(f"    Size:      {preview['total_qty']} {preview['symbol'].split('/')[0]}")
    print(f"    Value:     ${preview['position_value']:.2f} "
          f"(margin ${preview['margin_used']:.2f} × {preview['leverage']}x)")
    print()
    print("  Targets:")
    for tp in preview['tps']:
        pct_display = int(tp['pct'] * 100)
        print(f"    TP{tp['tp']}: ${tp['price']:.4f}  "
              f"({pct_display}% → {tp['qty']} units)")
    if preview['has_moon']:
        print(f"    TP{preview['tp_count']}: 🚀  (moon bag — no auto-close)")
    print("=" * 54)

    while True:
        choice = input("\nExecute this trade? (y/N): ").strip().lower()
        if choice in ('y', 'yes'):
            break
        elif choice in ('', 'n', 'no'):
            print("Trade cancelled.")
            return
        print("  Please enter 'y' or 'n'.")

    print()
    print("--- Executing Trade ---")
    print()

    try:
        wallet_before = executor.wallet_balance
        result = executor.execute(signal, risk)
        entry = result['entry']
        fill = entry.get('price') or executor.entry_price
        qty = entry.get('filled') or entry.get('amount') or 0

        print(f"  ✓ Entry: {signal.direction} {qty} {signal.symbol} @ ${fill:.6f}")
        print(f"  ✓ Stop Loss set at ${signal.sl_price}")

        for tp in result['tps']:
            if 'error' in tp:
                print(f"  ✗ TP{tp['tp']}: {tp['error']}")
            else:
                tp_order = tp['order']
                print(f"  ✓ TP{tp['tp']}: placed @ ${tp_order.get('price', '?')}  "
                      f"[order: {tp_order.get('id', '?')[:12]}...]")

        if signal.has_moon:
            print(f"  ✓ TP{signal.tp_count}: 🚀 no action (moon bag)")

        if result.get('warnings'):
            print()
            print("  ⚠️  Warnings (trade proceeded):")
            for w in result['warnings']:
                print(f"    • {w}")

        trade_id = trades_logger.log_trade(signal, result, risk, wallet_before)
        print()
        print(f"  Trade logged: {trade_id}")
        print()
        print("Done. Trade is active on Bybit.")
        print()
        print("TIP: Use 'Watch trade' from main menu to auto-move")
        print("     SL to entry price after TP1 fills.")

    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        logger.exception("Trade execution failed")


def show_positions(executor: BybitExecutor):
    clear_screen()
    print_header("Live Positions (Bybit)")

    positions = executor.fetch_open_positions()
    active = [p for p in positions if float(p.get('contracts', 0)) > 0]

    if not active:
        print("\n  No open positions.")
        wait_for_enter()
        return

    open_orders = executor.fetch_open_orders()

    for p in active:
        sym = p.get('symbol', '?')
        side = p.get('side', '?').upper()
        contracts = float(p.get('contracts', 0))
        entry_p = float(p.get('entryPrice', 0))
        mark_p = float(p.get('markPrice', 0))
        upnl = float(p.get('unrealizedPnl', 0))
        leverage = int(p.get('leverage', 1))
        liq = float(p.get('liquidationPrice', 0))

        print(f"\n  {sym}")
        print(f"    Direction:   {side}")
        print(f"    Size:        {contracts}")
        print(f"    Entry:       ${entry_p:.6f}")
        print(f"    Mark:        ${mark_p:.6f}")
        print(f"    Unrealized:  {'+' if upnl >= 0 else ''}${upnl:.2f}")
        print(f"    Leverage:    {leverage}x")
        print(f"    Liquidation: ${liq:.6f}")

        sym_orders = [o for o in open_orders if o.get('symbol') == sym]
        tp_orders = [o for o in sym_orders if o.get('reduceOnly')]
        if tp_orders:
            print(f"    Open TP orders ({len(tp_orders)}):")
            for o in sorted(tp_orders, key=lambda x: float(x.get('price', 0))):
                remaining = float(o.get('remaining', 0))
                if remaining > 0:
                    print(f"      TP @ ${float(o.get('price', 0)):.6f}  "
                          f"({remaining} remaining)")
        else:
            print(f"    Open TP orders: none")

        if entry_p > 0:
            print(f"\n    [M] Move SL to entry (${entry_p:.6f})")

    print()
    ch = input("  Option? (M or Enter): ").strip().lower()
    if ch == 'm':
        for p in active:
            sym = p.get('symbol', '?')
            entry_p = float(p.get('entryPrice', 0))
            if entry_p > 0:
                try:
                    executor.set_stop_loss(entry_p, sym)
                    print(f"  ✓ SL moved to ${entry_p:.6f} for {sym}")
                except Exception as e:
                    print(f"  ✗ Failed: {e}")
        wait_for_enter()


def show_history():
    clear_screen()
    print_header("Trade History")

    trades = trades_logger.get_history()
    if not trades:
        print("\n  No trades logged yet.")
        wait_for_enter()
        return

    print()
    for t in reversed(trades):
        print(trades_logger.format_trade(t))
        print()
    print(f"  Total trades: {len(trades)}")
    wait_for_enter()


def watch_trade(executor: BybitExecutor):
    clear_screen()
    print_header("Watch Trade — Auto Breakeven")

    trades = trades_logger.get_active_trades()
    if not trades:
        print("\n  No active trades to watch.")
        wait_for_enter()
        return

    latest = trades[-1]
    sym = latest['symbol']
    base = sym.split('/')[0]
    entry_price = latest.get('entry_price', 0)
    original_qty = latest.get('quantity', 0)

    if entry_price <= 0:
        print("  No entry price recorded. Cannot watch.")
        wait_for_enter()
        return

    print(f"\n  Watching:    {sym}")
    print(f"  Entry:       ${entry_price:.6f}")
    print(f"  Target TP1:  ${latest.get('tps', [{}])[0].get('price', '?') if latest.get('tps') else '?'}")
    print(f"  Target SL:   ${latest.get('sl_price', '?')}")
    print()
    print("  Waiting for TP1 to fill...")
    print("  Press Ctrl+C to stop watching.")
    print()

    try:
        while True:
            time.sleep(10)

            positions = executor.fetch_open_positions()
            current_pos = None
            for p in positions:
                if p.get('symbol') == sym or base in p.get('symbol', '') or base.upper() in p.get('symbol', ''):
                    if float(p.get('contracts', 0)) > 0:
                        current_pos = p
                        break

            if current_pos is None:
                print(f"  [{time.strftime('%H:%M:%S')}] Position closed. Stopping watch.")
                trades_logger.update_status(latest['id'], 'closed')
                break

            current_qty = float(current_pos.get('contracts', 0))
            mark_p = float(current_pos.get('markPrice', 0))
            upnl = float(current_pos.get('unrealizedPnl', 0))
            reduction = 1 - (current_qty / original_qty) if original_qty > 0 else 0

            print(f"  [{time.strftime('%H:%M:%S')}] Size: {current_qty} | "
                  f"Mark: ${mark_p:.6f} | P&L: ${upnl:.2f} | Reduced: {reduction:.0%}")

            if reduction >= 0.35:
                print(f"  ✓ TP1 detected! Moving SL to entry (${entry_price:.6f})...")
                try:
                    executor.set_stop_loss(entry_price, sym)
                    trades_logger.mark_tp_filled(latest['id'], 1)
                    trades_logger.update_status(latest['id'], 'breakeven')
                    print(f"  ✓ SL moved to ${entry_price:.6f}. Watch complete.")
                except Exception as e:
                    print(f"  ✗ Failed to move SL: {e}")
                break

    except KeyboardInterrupt:
        print("\n  Watch stopped.")


def main_menu() -> str:
    while True:
        clear_screen()
        print_header("CryptoBot Trade Executor")
        print(f"\n  Testnet: {os.getenv('BYBIT_TESTNET', 'true')}")
        print(f"  Risk:    {os.getenv('RISK_PER_TRADE', '3')}%")
        print()
        print("  1. Trade (fetch from Telegram bot)")
        print("  2. View open positions + manage SL")
        print("  3. View trade history")
        print("  4. Watch trade (auto breakeven after TP1)")
        print("  5. Exit")
        print()
        choice = input("  Choose (1-5): ").strip()
        if choice in ('1', '2', '3', '4', '5'):
            return choice
        print("  Invalid choice.")


def main():
    executor = BybitExecutor()
    wallet = executor.refresh_balance()
    logger.info("Wallet balance: %.2f USDT", wallet)

    if wallet <= 0:
        clear_screen()
        print_header("ERROR")
        print("\n  Wallet balance is 0 or negative.")
        print("  Check your Bybit API keys and testnet/live setting.")
        print(f"\n  Testnet mode: {os.getenv('BYBIT_TESTNET', 'true')}")
        print("  Set BYBIT_TESTNET=false in .env for live trading.")
        sys.exit(1)

    while True:
        choice = main_menu()

        if choice == '1':
            trade_flow(executor)
            wait_for_enter()
        elif choice == '2':
            show_positions(executor)
        elif choice == '3':
            show_history()
        elif choice == '4':
            watch_trade(executor)
            wait_for_enter()
        elif choice == '5':
            clear_screen()
            print("Goodbye.")
            sys.exit(0)


if __name__ == '__main__':
    main()
