import os
import logging
import threading
import time
from parser import parse_signal, TP_DISTRIBUTION
from executor import BybitExecutor
import trades_logger

logger = logging.getLogger(__name__)

_executor: BybitExecutor | None = None
_executor_lock = threading.Lock()


def get_executor() -> BybitExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = BybitExecutor()
            _executor.refresh_balance()
    return _executor


def reset_executor() -> None:
    global _executor
    with _executor_lock:
        _executor = None


def compute_preview(signal_text: str) -> tuple | None:
    signal = parse_signal(signal_text)
    if signal is None:
        return None

    risk = signal.risk_pct if signal.risk_pct is not None else float(os.getenv('RISK_PER_TRADE', '3'))
    executor = get_executor()
    preview = executor.preview(signal, risk)
    return signal, preview, risk


def format_preview(signal, preview: dict) -> str:
    base = preview['symbol'].split('/')[0]
    source = "signal" if signal.risk_pct is not None else ".env"
    lines = [
        "📊 *Signal Preview*",
        "",
        f"Pair:      {preview['symbol']:<12}  Direction: {preview['direction']}",
        f"Entry:     ${preview['entry_price']:.6f}  ({signal.entry_type})",
        f"Stop Loss: ${preview['sl_price']:.4f}",
        f"Leverage:  {preview['leverage']}x",
        f"Risk:      {preview['risk_pct']:.1f}% of wallet (from {source})",
        f"Balance:   ${preview['wallet_balance']:.2f}",
        "",
        "Position:",
        f"  Size:  {preview['total_qty']} {base}",
        f"  Value: ${preview['position_value']:.2f} "
        f"(margin ${preview['margin_used']:.2f} × {preview['leverage']}x)",
        "",
        "Targets:",
    ]
    for tp in preview['tps']:
        pct = int(tp['pct'] * 100)
        lines.append(f"  TP{tp['tp']}: ${tp['price']:.4f}  ({pct}% → {tp['qty']} {base})")
    if preview['has_moon']:
        lines.append(f"  TP{preview['tp_count']}: 🚀  (moon bag — no auto-close)")
    return '\n'.join(lines)


def execute_trade(signal_text: str) -> tuple:
    signal = parse_signal(signal_text)
    if signal is None:
        raise ValueError("Could not parse signal")

    risk = signal.risk_pct if signal.risk_pct is not None else float(os.getenv('RISK_PER_TRADE', '3'))
    executor = get_executor()
    wallet_before = executor.wallet_balance
    result = executor.execute(signal, risk)
    trade_id = trades_logger.log_trade(signal, result, risk, wallet_before)
    return signal, result, trade_id


def format_execution_result(signal, result: dict, trade_id: str) -> str:
    entry = result['entry']
    fill = entry.get('price') or result.get('entry_price', 0)
    qty = entry.get('filled') or entry.get('amount') or 0

    lines = [
        "✅ *Trade Executed*",
        "",
        f"Entry: {signal.direction} {qty} {signal.symbol} @ ${fill:.6f}",
        f"Stop Loss set at ${signal.sl_price}",
        "",
        "Take Profits:",
    ]
    for tp in result['tps']:
        if 'error' in tp:
            lines.append(f"  TP{tp['tp']}: ❌ {tp['error']}")
        else:
            o = tp['order']
            lines.append(f"  TP{tp['tp']}: ✅ @ ${o.get('price', '?')}  (ID: {str(o.get('id', '?'))[:10]}..)")

    if signal.has_moon:
        lines.append(f"  TP{signal.tp_count}: 🚀 moon bag — no auto-close")
    if result.get('warnings'):
        lines.append("")
        lines.append("⚠️ Warnings:")
        for w in result['warnings']:
            lines.append(f"  • {w}")
    lines.append("")
    lines.append(f"Trade ID: `{trade_id}`")
    return '\n'.join(lines)


def format_positions() -> tuple[str, list]:
    executor = get_executor()
    positions = executor.fetch_open_positions()
    active = [p for p in positions if float(p.get('contracts', 0)) > 0]

    if not active:
        return "No open positions.", []

    open_orders = executor.fetch_open_orders()
    lines = ["📈 *Open Positions*", ""]
    keyboard = []
    index = 0

    for p in active:
        sym = p.get('symbol', '?')
        side = p.get('side', '?').upper()
        contracts = float(p.get('contracts', 0))
        entry_p = float(p.get('entryPrice', 0))
        mark_p = float(p.get('markPrice', 0))
        upnl = float(p.get('unrealizedPnl', 0))
        lev = int(p.get('leverage', 1))
        liq = float(p.get('liquidationPrice', 0))

        lines.append(f"*{sym}*")
        lines.append(f"  {side} | Size: {contracts} | Lev: {lev}x")
        lines.append(f"  Entry: ${entry_p:.6f} | Mark: ${mark_p:.6f}")
        lines.append(f"  P&L: {'+' if upnl >= 0 else ''}${upnl:.2f}")
        lines.append(f"  Liq: ${liq:.6f}")

        sym_orders = [o for o in open_orders if o.get('symbol') == sym]
        tp_orders = [o for o in sym_orders if o.get('reduceOnly')]
        if tp_orders:
            for o in sorted(tp_orders, key=lambda x: float(x.get('price', 0))):
                rem = float(o.get('remaining', 0))
                if rem > 0:
                    lines.append(f"  TP @ ${float(o.get('price', 0)):.4f} ({rem} left)")
        lines.append("")

        base = sym.split('/')[0].split(':')[0]
        if entry_p > 0:
            keyboard.append([
                {'text': f'🔒 Move SL to entry: {base}', 'callback_data': f'sl:{base}'}
            ])
            index += 1

    return '\n'.join(lines), keyboard


def format_history() -> str:
    trades = trades_logger.get_history()
    if not trades:
        return "No trades logged yet."

    lines = ["📜 *Trade History*", ""]
    for t in reversed(trades[-10:]):
        lines.append(trades_logger.format_trade(t))
        lines.append("")
    lines.append(f"Total trades: {len(trades)} (showing last {min(10, len(trades))})")
    return '\n'.join(lines)


def move_sl_to_entry(base_symbol: str) -> str:
    executor = get_executor()
    positions = executor.fetch_open_positions()
    for p in positions:
        sym = p.get('symbol', '')
        if base_symbol.lower() in sym.lower() and float(p.get('contracts', 0)) > 0:
            entry_p = float(p.get('entryPrice', 0))
            if entry_p > 0:
                executor.set_stop_loss(entry_p, sym)
                return f"✅ SL moved to entry (${entry_p:.4f}) for {sym}"
    return f"❌ No open position found for {base_symbol}"


def watch_worker(bot_token: str, chat_id: str, trade_id: str) -> None:
    logger.info("Watch thread started for trade %s", trade_id)
    try:
        executor = get_executor()
    except Exception as e:
        logger.error("Watch thread: could not create executor: %s", e)
        return

    trades = trades_logger.get_active_trades()
    target = None
    for t in trades:
        if t['id'] == trade_id:
            target = t
            break

    if target is None:
        logger.warning("Watch thread: trade %s not found", trade_id)
        _send_telegram(bot_token, chat_id, "❌ Trade not found in logs.")
        return

    sym = target['symbol']
    base = sym.split('/')[0].split(':')[0]
    entry_price = target.get('entry_price', 0)
    original_qty = target.get('quantity', 0)

    if entry_price <= 0:
        _send_telegram(bot_token, chat_id, "❌ No entry price recorded for this trade.")
        return

    _send_telegram(bot_token, chat_id,
                   f"👀 Watching {sym} — will move SL to entry (${entry_price:.4f}) after TP1 fills.")

    try:
        while True:
            time.sleep(10)
            positions = executor.fetch_open_positions()
            current = None
            for p in positions:
                psym = p.get('symbol', '')
                if base.lower() in psym.lower() and float(p.get('contracts', 0)) > 0:
                    current = p
                    break

            if current is None:
                _send_telegram(bot_token, chat_id, f"🔒 {sym} position closed. Watch ended.")
                trades_logger.update_status(trade_id, 'closed')
                return

            current_qty = float(current.get('contracts', 0))
            mark_p = float(current.get('markPrice', 0))
            upnl = float(current.get('unrealizedPnl', 0))
            reduction = 1 - (current_qty / original_qty) if original_qty > 0 else 0

            logger.info("Watch %s: qty=%.2f mark=%.6f P&L=%.2f reduction=%.0f%%",
                        base, current_qty, mark_p, upnl, reduction * 100)

            if reduction >= 0.35:
                executor.set_stop_loss(entry_price, current.get('symbol'))
                trades_logger.mark_tp_filled(trade_id, 1)
                trades_logger.update_status(trade_id, 'breakeven')
                msg = f"✅ TP1 detected for {sym}! SL moved to entry (${entry_price:.4f})."
                _send_telegram(bot_token, chat_id, msg)
                logger.info("Watch %s: SL moved to entry", base)
                return

    except Exception as e:
        logger.error("Watch thread error: %s", e)
        _send_telegram(bot_token, chat_id, f"⚠️ Watch error: {e}")


def _send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    import json
    import urllib.request
    try:
        data = json.dumps({'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}).encode()
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.warning("Could not send Telegram notification: %s", e)
