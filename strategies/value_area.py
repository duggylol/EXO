"""
Value-Area Mean Reversion (Auction Market Theory / Market Profile).

Builds a DEVELOPING volume profile for each RTH session, derives POC / VAH / VAL
(value area = ~70% of session volume, expanded outward from the POC), and fades
the value-area extremes back toward value — but ONLY on balanced/rotational days.

The trade (per the research):
  * Short: a bar pokes ABOVE VAH but closes back inside  -> rejection short
  * Long : a bar pokes BELOW VAL but closes back inside  -> rejection long
  * Target = POC.  Stop = just beyond the value-area extreme.  Flat by session end.

The critical risk control is the DAY-TYPE FILTER: if the session range has extended
well beyond the Initial Balance (first hour) the longer-term trader is in control
(trend day) and we DO NOT fade — that's where mean reversion gets steamrolled.

Honest note baked into the design: mean reversion wins often but with negative
skew (rare large losers). The hard stop beyond the VA extreme caps that tail, and
the day-type filter avoids the worst of it. Validate with purged CV + Deflated
Sharpe before trusting the win rate.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from core.instruments import get_instrument
from core.strategy import Strategy, StrategyContext, register
from core.models import Bar


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@register
class ValueAreaReversion(Strategy):
    key = "value_area"
    display_name = "Value-Area Mean Reversion"
    description = "Auction-market fade of VAH/VAL back to POC on balanced days, with a day-type filter."
    params = {
        "value_pct": 0.70,
        "ib_minutes": 60,            # Initial Balance length
        "rth_start": "09:30", "rth_end": "16:00", "flatten": "15:55",
        "tz": "America/New_York",
        "max_range_ext": 2.0,        # suppress fade if session range > this x IB range (trend day)
        "stop_buffer_ticks": 4,      # stop beyond the VA extreme (small risk)
        "target_mode": "opposite",   # "opposite" = full traversal to far VA edge (big win);
                                     # "poc" = revert to POC (uses target_frac)
        "target_frac": 1.0,          # for target_mode="poc": 1.0 = POC, <1 = partial
    }

    def setup(self) -> None:
        self.instr = get_instrument(self.symbol)
        self.tick = self.instr.tick_size
        self._tz = ZoneInfo(self.params["tz"])
        self.rth_start = _parse_hhmm(self.params["rth_start"])
        self.rth_end = _parse_hhmm(self.params["rth_end"])
        self.flatten_t = _parse_hhmm(self.params["flatten"])
        self._reset_session(None)
        self.prior = {}             # prior-day poc/vah/val (reference)

    # --- session bookkeeping ---------------------------------------------
    def _reset_session(self, date) -> None:
        self._date = date
        self._bins: dict[int, float] = defaultdict(float)
        self._sess_hi = self._sess_lo = None
        self._ib_hi = self._ib_lo = None
        self._ib_open_dt = None
        self.poc = self.vah = self.val = None
        self._prev = None           # previous bar (for rejection detection)
        self._entry_target = self._entry_stop = None

    def _et(self, ts: float) -> datetime:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(self._tz)

    @property
    def viz_state(self) -> dict | None:
        """Live levels + day-type for the cockpit dashboard panel."""
        if self.poc is None:
            return None
        day_type = "forming"
        if self._ib_hi is not None and self._sess_hi is not None:
            ib_range = self._ib_hi - self._ib_lo
            sess_range = self._sess_hi - self._sess_lo
            day_type = ("trend" if ib_range > 0 and sess_range > self.params["max_range_ext"] * ib_range
                        else "balanced")
        return {
            "poc": self.poc, "vah": self.vah, "val": self.val,
            "ib_high": self._ib_hi, "ib_low": self._ib_lo,
            "prior": self.prior or None, "day_type": day_type,
            "last": self._prev.close if self._prev else None,
        }

    # --- volume profile ---------------------------------------------------
    def _add_volume(self, low: float, high: float, vol: float) -> None:
        lo_b = round(low / self.tick)
        hi_b = round(high / self.tick)
        n = max(1, hi_b - lo_b + 1)
        share = vol / n
        for b in range(lo_b, hi_b + 1):
            self._bins[b] += share

    def _recompute_va(self) -> None:
        if not self._bins:
            return
        prices = sorted(self._bins)
        n = len(prices)
        vols = [self._bins[p] for p in prices]
        total = sum(vols)
        if total <= 0:
            return
        poc_i = max(range(n), key=lambda i: vols[i])
        target = total * self.params["value_pct"]
        acc = vols[poc_i]
        lo, hi = poc_i, poc_i           # inclusive value-area index bounds
        up, dn = poc_i + 1, poc_i - 1   # next rows to consider
        while acc < target and (dn >= 0 or up < n):
            vol_up = (vols[up] + (vols[up + 1] if up + 1 < n else 0)) if up < n else -1.0
            vol_dn = (vols[dn] + (vols[dn - 1] if dn - 1 >= 0 else 0)) if dn >= 0 else -1.0
            if vol_up < 0 and vol_dn < 0:
                break
            if vol_up >= vol_dn:        # add up to two rows above
                for _ in range(2):
                    if up < n:
                        acc += vols[up]; hi = up; up += 1
            else:                        # add up to two rows below
                for _ in range(2):
                    if dn >= 0:
                        acc += vols[dn]; lo = dn; dn -= 1
        self.poc = prices[poc_i] * self.tick
        self.vah = prices[hi] * self.tick
        self.val = prices[lo] * self.tick

    # --- main -------------------------------------------------------------
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> None:
        et = self._et(bar.ts)
        t = et.time()

        # New RTH session? carry prior levels, reset.
        if et.date() != self._date:
            if self.poc is not None:
                self.prior = {"poc": self.poc, "vah": self.vah, "val": self.val}
            self._reset_session(et.date())

        in_rth = self.rth_start <= t < self.rth_end
        if not in_rth:
            return                       # v1: trade RTH only

        # Update session profile + extremes.
        self._add_volume(bar.low, bar.high, bar.volume)
        self._sess_hi = bar.high if self._sess_hi is None else max(self._sess_hi, bar.high)
        self._sess_lo = bar.low if self._sess_lo is None else min(self._sess_lo, bar.low)

        # Initial Balance (first ib_minutes of RTH).
        if self._ib_open_dt is None:
            self._ib_open_dt = et
        ib_age = (et - self._ib_open_dt).total_seconds() / 60.0
        if ib_age <= self.params["ib_minutes"]:
            self._ib_hi = bar.high if self._ib_hi is None else max(self._ib_hi, bar.high)
            self._ib_lo = bar.low if self._ib_lo is None else min(self._ib_lo, bar.low)

        self._recompute_va()
        prev = self._prev
        self._prev = bar

        # Manage an open position first (target / stop / session-end flat).
        if not ctx.is_flat:
            if t >= self.flatten_t:
                ctx.close("session end"); return
            if ctx.is_long:
                if self._entry_target and bar.close >= self._entry_target:
                    ctx.close("target POC")
                elif self._entry_stop and bar.close <= self._entry_stop:
                    ctx.close("stop below VAL")
            else:
                if self._entry_target and bar.close <= self._entry_target:
                    ctx.close("target POC")
                elif self._entry_stop and bar.close >= self._entry_stop:
                    ctx.close("stop above VAH")
            return

        # --- entries: only post-IB, balanced day, VA established ---
        if prev is None or self.vah is None or t >= self.flatten_t:
            return
        if ib_age <= self.params["ib_minutes"] or self._ib_hi is None:
            return                       # wait until IB completes
        ib_range = self._ib_hi - self._ib_lo
        sess_range = self._sess_hi - self._sess_lo
        if ib_range <= 0 or sess_range > self.params["max_range_ext"] * ib_range:
            return                       # trend day / big extension -> stand aside

        buf = self.params["stop_buffer_ticks"] * self.tick
        frac = self.params["target_frac"]
        mode = self.params["target_mode"]
        # Rejection short: this bar poked above VAH but closed back inside value.
        if bar.high > self.vah and bar.close < self.vah:
            self._entry_target = self.val if mode == "opposite" else bar.close + frac * (self.poc - bar.close)
            self._entry_stop = self.vah + buf      # small risk just above the extreme
            ctx.sell(f"reject VAH {self.vah:.2f} -> {self._entry_target:.2f}")
        # Rejection long: poked below VAL but closed back inside.
        elif bar.low < self.val and bar.close > self.val:
            self._entry_target = self.vah if mode == "opposite" else bar.close + frac * (self.poc - bar.close)
            self._entry_stop = self.val - buf
            ctx.buy(f"reject VAL {self.val:.2f} -> {self._entry_target:.2f}")
