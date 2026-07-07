import os
import logging
import ccxt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def find_linear_market(exchange, base: str, quote: str = 'USDT') -> str | None:
    for market_id, m in exchange.markets.items():
        if (m.get('base') == base
                and m.get('quote') == quote
                and m.get('linear')):
            return market_id
    return None


class BybitExecutor:
    def __init__(self):
        testnet = os.getenv('BYBIT_TESTNET', 'true').lower() == 'true'
        self.exchange = ccxt.bybit({
            'apiKey': os.getenv('BYBIT_API_KEY'),
            'secret': os.getenv('BYBIT_API_SECRET'),
            'enableRateLimit': True,
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()
        self._wallet_balance: float | None = None
        self._entry_price: float | None = None
        self._market_id: str | None = None

    @property
    def wallet_balance(self) -> float:
        return self._wallet_balance or 0.0

    def _resolve_market(self, symbol: str) -> str:
        base = symbol.split('/')[0]
        market_id = find_linear_market(self.exchange, base)
        if market_id is None:
            raise ValueError(f"Linear market not found for {symbol}")
        self._market_id = market_id
        return market_id

    def _get_precise_qty(self, raw_qty: float) -> float:
        return float(self.exchange.amount_to_precision(self._market_id, raw_qty))

    def _get_precise_price(self, raw_price: float) -> float:
        return float(self.exchange.price_to_precision(self._market_id, raw_price))

    def refresh_balance(self) -> float:
        balance = self.exchange.fetch_balance()
        usdt = balance.get('USDT', {})
        raw = usdt.get('total') or usdt.get('free') or 0
        self._wallet_balance = float(raw) if raw else 0.0
        return self._wallet_balance

    def set_leverage(self, leverage: int) -> None:
        try:
            self.exchange.set_leverage(leverage, self._market_id)
        except Exception as e:
            logger.warning("Could not set leverage to %dx (might already be set): %s", leverage, e)

    def calculate_qty(self, risk_pct: float, leverage: int, entry_price: float) -> float:
        risk_amount = self._wallet_balance * risk_pct / 100.0
        position_value = risk_amount * leverage
        raw_qty = position_value / entry_price
        return self._get_precise_qty(raw_qty)

    def fetch_open_positions(self) -> list:
        try:
            return self.exchange.fetch_positions()
        except Exception as e:
            logger.warning("Could not fetch positions: %s", e)
            return []

    def fetch_open_orders(self, symbol: str | None = None) -> list:
        try:
            return self.exchange.fetch_open_orders(symbol)
        except Exception as e:
            logger.warning("Could not fetch open orders: %s", e)
            return []

    def has_open_position(self, symbol_or_market: str) -> bool:
        positions = self.fetch_open_positions()
        for p in positions:
            cnt = p.get('contracts', 0)
            if p.get('symbol') == symbol_or_market and (float(cnt) if cnt else 0) > 0:
                return True
        return False

    def pre_flight_checks(self, signal, risk_pct: float, entry_price: float,
                          total_qty: float) -> list[str]:
        warnings = []

        market = self.exchange.market(self._market_id)
        if not market.get('active', True):
            warnings.append(f"Market {signal.symbol} is NOT active on Bybit")

        if self.has_open_position(self._market_id):
            warnings.append(f"Already have an open position for {signal.symbol}")

        if self._wallet_balance is None or self._wallet_balance <= 0:
            warnings.append("Wallet balance is 0 or could not be fetched")

        raw_min = market.get('limits', {}).get('cost', {}).get('min')
        min_cost = float(raw_min) if raw_min else 0
        position_value = total_qty * entry_price
        if min_cost > 0 and position_value < min_cost:
            warnings.append(
                f"Position value ${position_value:.2f} is below minimum ${min_cost:.2f}"
            )

        if signal.direction == 'LONG' and signal.sl_price >= entry_price:
            warnings.append(
                f"Stop Loss ${signal.sl_price} is ABOVE entry ${entry_price:.6f} (LONG)"
            )
        elif signal.direction == 'SHORT' and signal.sl_price <= entry_price:
            warnings.append(
                f"Stop Loss ${signal.sl_price} is BELOW entry ${entry_price:.6f} (SHORT)"
            )

        try:
            self.exchange.private_get_v5_market_instruments({
                'category': 'linear',
                'symbol': market['id'],
            })
        except Exception:
            warnings.append(f"Could not verify {signal.symbol} on Bybit")

        return warnings

    def place_entry(self, side: str, qty: float, sl_price: float) -> dict:
        entry_side = 'buy' if side == 'LONG' else 'sell'
        try:
            order = self.exchange.create_order(
                self._market_id,
                'market',
                entry_side,
                qty,
                None,
                {
                    'stopLoss': str(self._get_precise_price(sl_price)),
                    'positionIdx': 0,
                },
            )
            return order
        except Exception:
            order = self.exchange.create_order(
                self._market_id, 'market', entry_side, qty, None,
            )
            self._set_position_sl(sl_price)
            return order

    def _set_position_sl(self, sl_price: float) -> None:
        market = self.exchange.market(self._market_id)
        self.exchange.private_post_v5_position_set_trading_stop({
            'symbol': market['id'],
            'stopLoss': str(self._get_precise_price(sl_price)),
            'slTriggerBy': 'LastPrice',
            'positionIdx': 0,
        })

    @property
    def entry_price(self) -> float:
        if self._entry_price is None:
            return 0.0
        return self._entry_price

    def set_stop_loss(self, sl_price: float, market_id: str | None = None) -> None:
        mid = market_id or self._market_id
        market = self.exchange.market(mid)
        self.exchange.private_post_v5_position_set_trading_stop({
            'symbol': market['id'],
            'stopLoss': str(self._get_precise_price(sl_price)),
            'slTriggerBy': 'LastPrice',
            'positionIdx': 0,
        })

    def place_tp_order(self, side: str, qty: float, price: float) -> dict:
        tp_side = 'sell' if side == 'LONG' else 'buy'
        return self.exchange.create_limit_order(
            self._market_id,
            tp_side,
            qty,
            self._get_precise_price(price),
            {
                'reduceOnly': True,
                'positionIdx': 0,
            },
        )

    def _compute(self, signal, risk_pct: float) -> dict:
        from signal_parser import TP_DISTRIBUTION

        market_id = self._resolve_market(signal.symbol)

        if signal.entry_type.upper() == 'MARKET PRICE':
            ticker = self.exchange.fetch_ticker(market_id)
            entry_price = ticker.get('last')
            if entry_price is None:
                raise ValueError(f"Could not fetch current price for {market_id}")
        else:
            entry_price = float(signal.entry_type)

        total_qty = self.calculate_qty(risk_pct, signal.leverage, entry_price)
        position_value = total_qty * entry_price
        margin_used = position_value / signal.leverage if signal.leverage else 0

        tps = []
        sorted_tps = sorted(signal.tp_prices.items())
        for idx, (tp_num, tp_price) in enumerate(sorted_tps):
            if idx >= len(TP_DISTRIBUTION):
                break
            pct = TP_DISTRIBUTION[idx]
            tp_qty = self._get_precise_qty(total_qty * pct)
            if tp_qty > 0:
                tps.append({'tp': tp_num, 'price': tp_price, 'qty': tp_qty, 'pct': pct})

        return {
            'market_id': market_id,
            'entry_price': entry_price,
            'total_qty': total_qty,
            'position_value': position_value,
            'margin_used': margin_used,
            'tps': tps,
            'has_moon': signal.has_moon,
            'tp_count': signal.tp_count,
        }

    def preview(self, signal, risk_pct: float) -> dict:
        self._resolve_market(signal.symbol)
        self.refresh_balance()
        info = self._compute(signal, risk_pct)
        info['wallet_balance'] = self._wallet_balance
        info['risk_pct'] = risk_pct
        info['leverage'] = signal.leverage
        info['sl_price'] = signal.sl_price
        info['direction'] = signal.direction
        info['symbol'] = signal.symbol
        return info

    def execute(self, signal, risk_pct: float = 3.0) -> dict:
        from signal_parser import TP_DISTRIBUTION

        market_id = self._resolve_market(signal.symbol)
        logger.info("Market resolved: %s", market_id)

        self.refresh_balance()
        logger.info("Wallet USDT balance: %.2f", self._wallet_balance)

        self.set_leverage(signal.leverage)

        if signal.entry_type.upper() == 'MARKET PRICE':
            ticker = self.exchange.fetch_ticker(market_id)
            entry_price = ticker.get('last')
            if entry_price is None:
                raise ValueError(f"Could not fetch current price for {market_id}")
        else:
            entry_price = float(signal.entry_type)

        self._entry_price = entry_price
        logger.info("Entry price: %.8f", entry_price)

        total_qty = self.calculate_qty(risk_pct, signal.leverage, entry_price)
        logger.info("Position qty: %s", total_qty)

        warnings = self.pre_flight_checks(signal, risk_pct, entry_price, total_qty)
        if warnings:
            logger.warning("Pre-flight checks found %d issue(s)", len(warnings))

        entry_result = self.place_entry(signal.direction, total_qty, signal.sl_price)
        logger.info("Entry order placed: %s", entry_result.get('id', 'unknown'))

        results = {'entry': entry_result, 'tps': [], 'warnings': warnings,
                   'entry_price': entry_price}

        sorted_tps = sorted(signal.tp_prices.items())

        for idx, (tp_num, tp_price) in enumerate(sorted_tps):
            if idx >= len(TP_DISTRIBUTION):
                break
            pct = TP_DISTRIBUTION[idx]
            tp_qty_raw = total_qty * pct
            tp_qty = self._get_precise_qty(tp_qty_raw)

            if tp_qty <= 0:
                continue

            try:
                tp_order = self.place_tp_order(signal.direction, tp_qty, tp_price)
                results['tps'].append({'tp': tp_num, 'order': tp_order})
                logger.info("TP%d order placed: %s", tp_num, tp_order.get('id', 'unknown'))
            except Exception as e:
                logger.warning("TP%d order failed: %s", tp_num, e)
                results['tps'].append({'tp': tp_num, 'error': str(e)})

        if signal.has_moon:
            logger.info("TP5 🚀 moon bag — no automatic order placed")

        return results
