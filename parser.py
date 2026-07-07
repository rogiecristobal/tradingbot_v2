import re

BOLD_CAPS_START = 0x1D400
BOLD_SMALL_START = 0x1D41A


def _normalize(text: str) -> str:
    result = []
    for ch in text:
        code = ord(ch)
        if BOLD_CAPS_START <= code <= BOLD_CAPS_START + 25:
            result.append(chr(code - BOLD_CAPS_START + ord('A')))
        elif BOLD_SMALL_START <= code <= BOLD_SMALL_START + 25:
            result.append(chr(code - BOLD_SMALL_START + ord('a')))
        else:
            result.append(ch)
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

    return signal if signal.is_valid else None
