"""
Incremental technical indicators.

Each indicator updates one bar at a time and exposes `.value` (and sometimes
extra fields). They return None until enough data has accumulated (`ready`).
Incremental design keeps live trading O(1) per bar instead of recomputing
over a window every tick.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional


class SMA:
    """Simple moving average."""

    def __init__(self, period: int):
        self.period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._sum = 0.0
        self.value: Optional[float] = None

    @property
    def ready(self) -> bool:
        return len(self._buf) == self.period

    def update(self, x: float) -> Optional[float]:
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]
        self._buf.append(x)
        self._sum += x
        if self.ready:
            self.value = self._sum / self.period
        return self.value


class EMA:
    """Exponential moving average."""

    def __init__(self, period: int):
        self.period = period
        self.k = 2.0 / (period + 1)
        self.value: Optional[float] = None
        self._count = 0
        self._seed_sum = 0.0

    @property
    def ready(self) -> bool:
        return self.value is not None and self._count >= self.period

    def update(self, x: float) -> Optional[float]:
        self._count += 1
        if self.value is None:
            # Seed with an SMA over the first `period` points for stability.
            self._seed_sum += x
            if self._count >= self.period:
                self.value = self._seed_sum / self.period
            return self.value
        self.value = x * self.k + self.value * (1 - self.k)
        return self.value


class RollingStd:
    """Rolling standard deviation (population)."""

    def __init__(self, period: int):
        self.period = period
        self._buf: deque[float] = deque(maxlen=period)
        self.value: Optional[float] = None
        self.mean: Optional[float] = None

    @property
    def ready(self) -> bool:
        return len(self._buf) == self.period

    def update(self, x: float) -> Optional[float]:
        self._buf.append(x)
        if self.ready:
            m = sum(self._buf) / self.period
            var = sum((v - m) ** 2 for v in self._buf) / self.period
            self.mean = m
            self.value = math.sqrt(var)
        return self.value


class RSI:
    """Wilder's Relative Strength Index."""

    def __init__(self, period: int = 14):
        self.period = period
        self._prev: Optional[float] = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._count = 0
        self.value: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, close: float) -> Optional[float]:
        if self._prev is None:
            self._prev = close
            return None
        change = close - self._prev
        self._prev = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self._count += 1
        if self._count <= self.period:
            self._avg_gain += gain / self.period
            self._avg_loss += loss / self.period
            if self._count == self.period:
                self._set_rsi()
        else:
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
            self._set_rsi()
        return self.value

    def _set_rsi(self) -> None:
        if self._avg_loss == 0:
            self.value = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self.value = 100.0 - (100.0 / (1.0 + rs))


class ATR:
    """Average True Range (Wilder smoothing). Update with full OHLC bars."""

    def __init__(self, period: int = 14):
        self.period = period
        self._prev_close: Optional[float] = None
        self.value: Optional[float] = None
        self._count = 0
        self._seed = 0.0

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        self._count += 1
        if self._count <= self.period:
            self._seed += tr
            if self._count == self.period:
                self.value = self._seed / self.period
        else:
            self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


class MACD:
    """MACD line, signal line, histogram."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.ema_fast = EMA(fast)
        self.ema_slow = EMA(slow)
        self.ema_signal = EMA(signal)
        self.macd: Optional[float] = None
        self.signal: Optional[float] = None
        self.hist: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.hist is not None

    def update(self, close: float) -> Optional[float]:
        f = self.ema_fast.update(close)
        s = self.ema_slow.update(close)
        if f is None or s is None:
            return None
        self.macd = f - s
        sig = self.ema_signal.update(self.macd)
        if sig is not None:
            self.signal = sig
            self.hist = self.macd - sig
        return self.macd


class Bollinger:
    """Bollinger Bands."""

    def __init__(self, period: int = 20, mult: float = 2.0):
        self.std = RollingStd(period)
        self.mult = mult
        self.upper: Optional[float] = None
        self.lower: Optional[float] = None
        self.mid: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.upper is not None

    def update(self, close: float) -> Optional[float]:
        sd = self.std.update(close)
        if sd is None:
            return None
        self.mid = self.std.mean
        self.upper = self.mid + self.mult * sd
        self.lower = self.mid - self.mult * sd
        return self.mid


class Keltner:
    """Keltner Channels (EMA mid +/- ATR multiple)."""

    def __init__(self, period: int = 20, atr_period: int = 10, mult: float = 2.0):
        self.ema = EMA(period)
        self.atr = ATR(atr_period)
        self.mult = mult
        self.upper: Optional[float] = None
        self.lower: Optional[float] = None
        self.mid: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.upper is not None

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        mid = self.ema.update(close)
        a = self.atr.update(high, low, close)
        if mid is None or a is None:
            return None
        self.mid = mid
        self.upper = mid + self.mult * a
        self.lower = mid - self.mult * a
        return self.mid


class Donchian:
    """Donchian channel (highest high / lowest low over period)."""

    def __init__(self, period: int = 20):
        self.period = period
        self._highs: deque[float] = deque(maxlen=period)
        self._lows: deque[float] = deque(maxlen=period)
        self.upper: Optional[float] = None
        self.lower: Optional[float] = None
        self.mid: Optional[float] = None

    @property
    def ready(self) -> bool:
        # True only once `upper`/`lower` are actually populated (one bar after
        # the window first fills), so strategies never see None bands.
        return self.upper is not None

    def update(self, high: float, low: float) -> Optional[float]:
        # Channel is computed on PRIOR bars (exclude current) for breakout use.
        if len(self._highs) == self.period:
            self.upper = max(self._highs)
            self.lower = min(self._lows)
            self.mid = (self.upper + self.lower) / 2
        self._highs.append(high)
        self._lows.append(low)
        return self.upper


class Supertrend:
    """Supertrend (ATR-band trend follower). direction: +1 up, -1 down."""

    def __init__(self, period: int = 10, mult: float = 3.0):
        self.atr = ATR(period)
        self.mult = mult
        self.value: Optional[float] = None
        self.direction: int = 0
        self._final_upper: Optional[float] = None
        self._final_lower: Optional[float] = None
        self._prev_close: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.direction != 0

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        a = self.atr.update(high, low, close)
        if a is None:
            self._prev_close = close
            return None
        hl2 = (high + low) / 2
        basic_upper = hl2 + self.mult * a
        basic_lower = hl2 - self.mult * a

        if self._final_upper is None:
            self._final_upper = basic_upper
            self._final_lower = basic_lower
            self.direction = 1
            self.value = self._final_lower
            self._prev_close = close
            return self.value

        pc = self._prev_close if self._prev_close is not None else close
        self._final_upper = (
            basic_upper if (basic_upper < self._final_upper or pc > self._final_upper)
            else self._final_upper
        )
        self._final_lower = (
            basic_lower if (basic_lower > self._final_lower or pc < self._final_lower)
            else self._final_lower
        )

        if close > self._final_upper:
            self.direction = 1
        elif close < self._final_lower:
            self.direction = -1
        self.value = self._final_lower if self.direction == 1 else self._final_upper
        self._prev_close = close
        return self.value


class ROC:
    """Rate of change over `period` bars, as a percentage."""

    def __init__(self, period: int = 10):
        self.period = period
        self._buf: deque[float] = deque(maxlen=period + 1)
        self.value: Optional[float] = None

    @property
    def ready(self) -> bool:
        return len(self._buf) == self.period + 1

    def update(self, close: float) -> Optional[float]:
        self._buf.append(close)
        if self.ready and self._buf[0] != 0:
            self.value = (close - self._buf[0]) / self._buf[0] * 100.0
        return self.value


class VWAP:
    """Session VWAP. Call reset() at session start to anchor it."""

    def __init__(self):
        self._pv = 0.0
        self._vol = 0.0
        self.value: Optional[float] = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def reset(self) -> None:
        self._pv = 0.0
        self._vol = 0.0
        self.value = None

    def update(self, high: float, low: float, close: float, volume: float) -> Optional[float]:
        typical = (high + low + close) / 3.0
        vol = volume if volume > 0 else 1.0
        self._pv += typical * vol
        self._vol += vol
        if self._vol > 0:
            self.value = self._pv / self._vol
        return self.value
