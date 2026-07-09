import re
import logging
import unicodedata

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    return unicodedata.normalize('NFKC', text)


_RE_SYMBOL = re.compile(
    r'\$?([A-Z0-9]{2,})\s*/\s*(USDT|BTC|ETH)\s*\((LONG|SHORT)\)',
    re.IGNORECASE,
)
_RE_SYMBOL_BARE = re.compile(r'([A-Z0-9]{2,})\s*/\s*(USDT|BTC|ETH)', re.IGNORECASE)
_RE_DIRECTION = re.compile(r'^\s*(LONG|SHORT)\s*$', re.IGNORECASE)
_RE_ENTRY = re.compile(r'entry\s*:\s*(.+)', re.IGNORECASE)
_RE_TP = re.compile(r'TP\s*(\d+)\s*:\s*\$?\s*([\d.]+)', re.IGNORECASE)
_RE_TP_MOON = re.compile(r'TP\s*(\d+)\s*:\s*(🚀)', re.IGNORECASE)
_RE_SL = re.compile(r'stop\s*loss\s*[:=]\s*\$?\s*([\d.]+)', re.IGNORECASE)
_RE_LEVERAGE = re.compile(r'(\d+)\s*x', re.IGNORECASE)
_RE_RISK = re.compile(r'(\d+(?:\.\d+)?)\s*%\s*(?:margin|risk|of)', re.IGNORECASE)

TP_WEIGHTS = [4, 3, 2, 1]


class Signal:
    def __init__(self, raw: str):
        self.raw = raw
        self.symbol: str | None = None
        self.direction: str | None = None
        self.entry_type: str | None = None
        self.tp_prices: dict[int, float] = {}
        self.sl_price: float | None = None
        self.leverage: int | None = None
        self.tp_count: int = 0
        self.has_moon: bool = False
        self.risk_pct: float | None = None

    @property
    def is_valid(self) -> bool:
        return (
            self.symbol is not None
            and self.direction in ('LONG', 'SHORT')
            and self.entry_type is not None
            and len(self.tp_prices) >= 1
            and self.sl_price is not None
            and self.leverage is not None
        )

    def __str__(self) -> str:
        lines = [
            f"Pair:      {self.symbol}",
            f"Direction: {self.direction}",
            f"Entry:     {self.entry_type}",
        ]
        tp_count = len(self.tp_prices)
        weights = list(TP_WEIGHTS)
        while len(weights) < tp_count:
            weights.append(weights[-1])
        weights = weights[:tp_count]
        total_weight = sum(weights)
        for idx, price in sorted(self.tp_prices.items()):
            pct = int(weights[idx - 1] / total_weight * 100)
            lines.append(f"  TP{idx}: ${price} ({pct}%)")
        if self.has_moon:
            lines.append(f"  TP{self.tp_count}: 🚀 (no auto-close)")
        lines.append(f"Stop Loss: ${self.sl_price}")
        lines.append(f"Leverage:  {self.leverage}x")
        return '\n'.join(lines)


def parse_signal(text: str) -> Signal | None:
    normal = _normalize(text)
    signal = Signal(text.strip())

    for line in normal.splitlines():
        line = line.strip()
        if not line:
            continue

        m = _RE_SYMBOL.search(line)
        if m:
            signal.symbol = f"{m.group(1).upper()}/{m.group(2).upper()}"
            signal.direction = m.group(3).upper()
            continue

        if signal.symbol is None:
            m = _RE_SYMBOL_BARE.search(line)
            if m:
                signal.symbol = f"{m.group(1).upper()}/{m.group(2).upper()}"
                continue

        if signal.direction is None:
            m = _RE_DIRECTION.search(line)
            if m:
                signal.direction = m.group(1).upper()
                continue

        m = _RE_ENTRY.search(line)
        if m:
            signal.entry_type = m.group(1).strip()
            continue

        m = _RE_TP_MOON.search(line)
        if m:
            tp_num = int(m.group(1))
            signal.tp_count = max(signal.tp_count, tp_num)
            signal.has_moon = True
            continue

        m = _RE_TP.search(line)
        if m:
            tp_num = int(m.group(1))
            signal.tp_prices[tp_num] = float(m.group(2))
            signal.tp_count = max(signal.tp_count, tp_num)
            continue

        m = _RE_SL.search(line)
        if m:
            signal.sl_price = float(m.group(1))
            continue

        m = _RE_LEVERAGE.search(line)
        if m:
            signal.leverage = int(m.group(1))
            continue

        m = _RE_RISK.search(line)
        if m:
            signal.risk_pct = float(m.group(1))

    # Fallback multi-line regexes for values on the next line
    if signal.sl_price is None:
        m = re.search(r'stop\s*loss\s*[:=]\s*\$?\s*([\d.]+)', normal, re.IGNORECASE)
        if m:
            signal.sl_price = float(m.group(1))

    if not signal.is_valid:
        missing = []
        if signal.symbol is None:
            missing.append("symbol")
        if signal.direction is None:
            missing.append("direction")
        if signal.entry_type is None:
            missing.append("entry_type")
        if not signal.tp_prices:
            missing.append("TPs")
        if signal.sl_price is None:
            missing.append("sl_price")
        if signal.leverage is None:
            missing.append("leverage")
        hex_dump = ' '.join(f'U+{ord(c):04X}' for c in text[:200])
        logger.warning("Parse failed — raw text: %r", text)
        logger.warning("Parse failed — hex dump: %s", hex_dump)
        logger.warning("Parse failed — normalized: %r", normal)
        logger.warning("Parse failed — missing: %s", ", ".join(missing))

    return signal if signal.is_valid else None
