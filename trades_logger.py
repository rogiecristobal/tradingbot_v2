import json
import os
from datetime import datetime

TRADES_FILE = os.path.join(os.path.dirname(__file__), 'trades.json')


def _load() -> list:
    if not os.path.exists(TRADES_FILE):
        return []
    try:
        with open(TRADES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(trades: list) -> None:
    with open(TRADES_FILE, 'w', encoding='utf-8') as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)


def log_trade(signal, result, risk_pct: float, wallet_balance: float) -> str:
    trades = _load()
    entry = result['entry']
    base = signal.symbol.split('/')[0].lower()
    ts = datetime.now()
    trade_id = f"{ts.strftime('%Y%m%d_%H%M%S')}_{base}"

    tps_log = []
    for tp in result['tps']:
        if 'error' in tp:
            tps_log.append({'tp': tp['tp'], 'error': tp['error']})
        else:
            tps_log.append({
                'tp': tp['tp'],
                'price': tp['order'].get('price', 0),
                'qty': tp['order'].get('amount', 0),
                'order_id': tp['order'].get('id', ''),
                'filled': False,
            })

    fill_price = entry.get('price') or result.get('entry_price', 0)
    fill_qty = entry.get('filled') or entry.get('amount', 0)

    trade_record = {
        'id': trade_id,
        'datetime': ts.strftime('%Y-%m-%d %H:%M:%S'),
        'symbol': signal.symbol,
        'direction': signal.direction,
        'entry_type': signal.entry_type,
        'entry_price': fill_price,
        'quantity': fill_qty,
        'entry_order_id': entry.get('id', ''),
        'sl_price': signal.sl_price,
        'leverage': signal.leverage,
        'risk_pct': risk_pct,
        'wallet_balance': wallet_balance,
        'tps': tps_log,
        'has_moon': signal.has_moon,
        'status': 'active',
    }
    trades.append(trade_record)
    _save(trades)
    return trade_id


def get_history() -> list:
    return _load()


def get_active_trades() -> list:
    return [t for t in _load() if t.get('status') == 'active']


def update_status(trade_id: str, status: str) -> None:
    trades = _load()
    for t in trades:
        if t['id'] == trade_id:
            t['status'] = status
            break
    _save(trades)


def mark_tp_filled(trade_id: str, tp_num: int) -> None:
    trades = _load()
    for t in trades:
        if t['id'] == trade_id:
            for tp in t.get('tps', []):
                if tp.get('tp') == tp_num:
                    tp['filled'] = True
                    break
            break
    _save(trades)


def format_trade(t: dict) -> str:
    lines = [
        f"  {t.get('datetime', '?')}  |  {t['symbol']:<12} | {t['direction']:<5} | "
        f"Entry: ${t.get('entry_price', 0):<8} | Qty: {t.get('quantity', 0):<8} | "
        f"SL: ${t.get('sl_price', 0):<8} | {t.get('leverage', '?')}x | {t.get('status', '?')}"
    ]
    tp_parts = []
    for tp in t.get('tps', []):
        if 'error' in tp:
            tp_parts.append(f"TP{tp['tp']}:ERR")
        else:
            icon = '✅' if tp.get('filled') else '⏳'
            tp_parts.append(f"TP{tp['tp']} {icon} ${tp.get('price', 0)}")
    if tp_parts:
        lines.append("    TPs: " + ' | '.join(tp_parts))
    return '\n'.join(lines)
