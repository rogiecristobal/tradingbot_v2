import re
import logging

logger = logging.getLogger(__name__)

# Unicode mathematical / special letter ranges (start, count, offset from 'A' or 'a')
# CAPS = starts are uppercase, SMALL = lowercase, both handled with same offset logic
_EXTRA_RANGES = [
    # Mathematical Bold (A-Z: 0x1D400, a-z: 0x1D41A) — already in dedicated code
    # Mathematical Italic (A-Z: 0x1D434, a-z: 0x1D44E)
    (0x1D434, 26, ord('A') - 0x1D434),
    (0x1D44E, 26, ord('a') - 0x1D44E),
    # Mathematical Bold Italic (A-Z: 0x1D468, a-z: 0x1D482)
    (0x1D468, 26, ord('A') - 0x1D468),
    (0x1D482, 26, ord('a') - 0x1D482),
    # Mathematical Script (A-Z: 0x1D49C, a-z: 0x1D4B6) — skip gaps inside
    # Mathematical Fraktur (A-Z: 0x1D504, a-z: 0x1D51E) — skip gaps
    # Mathematical Double-Struck (A-Z: 0x1D538, a-z: 0x1D552)
    (0x1D538, 26, ord('A') - 0x1D538),
    (0x1D552, 26, ord('a') - 0x1D552),
    # Mathematical Sans-Serif Bold (A-Z: 0x1D5D4, a-z: 0x1D5EE)
    (0x1D5D4, 26, ord('A') - 0x1D5D4),
    (0x1D5EE, 26, ord('a') - 0x1D5EE),
    # Mathematical Monospace (A-Z: 0x1D670, a-z: 0x1D68A)
    (0x1D670, 26, ord('A') - 0x1D670),
    (0x1D68A, 26, ord('a') - 0x1D68A),
    # Fullwidth (A-Z: 0xFF21, a-z: 0xFF41)
    (0xFF21, 26, ord('A') - 0xFF21),
    (0xFF41, 26, ord('a') - 0xFF41),
]


def _normalize(text: str) -> str:
    result = []
    for ch in text:
        code = ord(ch)
        c = None
        if 0x1D400 <= code <= 0x1D419:
            c = chr(code - 0x1D400 + ord('A'))
        elif 0x1D41A <= code <= 0x1D433:
            c = chr(code - 0x1D41A + ord('a'))
        else:
            for start, count, offset in _EXTRA_RANGES:
                if start <= code < start + count:
                    c = chr(code + offset)
                    break
        # Also normalize common symbol lookalikes
        if code == 0xFF04:  # Fullwidth dollar sign ＄
            c = '$'
        result.append(c if c else ch)
    return ''.join(result)


_RE_SYMBOL = re.compile(
    r'\$?([A-Z0-9]{2,})\s*/\s*(USDT|BTC|ETH)\s*\((LONG|SHORT)\)',
    re.IGNORECASE,
)
_RE_ENTRY = re.compile(r'entry\s*:\s*(.+)', re.IGNORECASE)
_RE_TP = re.compile(r'TP\s*(\d+)\s*:\s*\$?\s*([\d.]+)', re.IGNORECASE)
_RE_TP_MOON = re.compile(r'TP\s*(\d+)\s*:\s*(🚀)', re.IGNORECASE)
_RE_SL = re.compile(r'stop\s*loss\s*:\s*\$?\s*([\d.]+)', re.IGNORECASE)
_RE_LEVERAGE = re.compile(r'(\d+)\s*x', re.IGNORECASE)
_RE_RISK = re.compile(r'(\d+(?:\.\d+)?)\s*%\s*(?:margin|risk|of)', re.IGNORECASE)

TP_DISTRIBUTION = [0.40, 0.30, 0.20, 0.10]


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
        for idx, price in sorted(self.tp_prices.items()):
            pct = int(TP_DISTRIBUTION[idx - 1] * 100) if idx <= len(TP_DISTRIBUTION) else 0
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
        logger.warning("Parse failed — raw text: %r", text)
        logger.warning("Parse failed — normalized: %r", normal)
        logger.warning("Parse failed — missing: %s", ", ".join(missing))

    return signal if signal.is_valid else None
