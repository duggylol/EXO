"""
Futures contract specifications.

Each spec carries the tick size and the dollar value of one tick, which is what
makes P/L math correct. Point value = tick_value / tick_size.

Sources: CME contract specs. Verify against your broker before trading real size,
because micro/mini multipliers and tick values do occasionally change.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    tick_size: float       # minimum price increment
    tick_value: float      # dollar value of one tick (per contract)
    margin_day: float      # rough intraday margin (informational only)
    exchange: str = "CME"

    @property
    def point_value(self) -> float:
        """Dollar value of a full 1.0 move in price, per contract."""
        return self.tick_value / self.tick_size

    def ticks(self, price_delta: float) -> float:
        return price_delta / self.tick_size

    def pnl(self, price_delta: float, qty: int) -> float:
        """Signed dollar P/L for `qty` contracts over a price move."""
        return price_delta * self.point_value * qty


# Common CME products traded at prop firms. Add your own freely.
INSTRUMENTS: dict[str, Instrument] = {
    # Equity index
    "ES":  Instrument("ES",  "E-mini S&P 500",      0.25, 12.50, 13000, "CME"),
    "MES": Instrument("MES", "Micro E-mini S&P 500", 0.25, 1.25,  1300, "CME"),
    "NQ":  Instrument("NQ",  "E-mini Nasdaq 100",   0.25, 5.00,  17000, "CME"),
    "MNQ": Instrument("MNQ", "Micro E-mini Nasdaq",  0.25, 0.50,  1700, "CME"),
    "RTY": Instrument("RTY", "E-mini Russell 2000", 0.10, 5.00,  8000, "CME"),
    "M2K": Instrument("M2K", "Micro E-mini Russell", 0.10, 0.50,  800, "CME"),
    "YM":  Instrument("YM",  "E-mini Dow",          1.0,  5.00,  10000, "CBOT"),
    "MYM": Instrument("MYM", "Micro E-mini Dow",    1.0,  0.50,  1000, "CBOT"),
    # Metals
    "GC":  Instrument("GC",  "Gold",                0.10, 10.00, 12000, "COMEX"),
    "MGC": Instrument("MGC", "Micro Gold",          0.10, 1.00,  1200, "COMEX"),
    "SI":  Instrument("SI",  "Silver",              0.005, 25.00, 16000, "COMEX"),
    # Energy
    "CL":  Instrument("CL",  "Crude Oil",           0.01, 10.00, 6000, "NYMEX"),
    "MCL": Instrument("MCL", "Micro Crude Oil",     0.01, 1.00,  600, "NYMEX"),
    "NG":  Instrument("NG",  "Natural Gas",         0.001, 10.00, 5000, "NYMEX"),
    # Financials
    "ZB":  Instrument("ZB",  "30-Year T-Bond",      0.03125, 31.25, 4000, "CBOT"),
    "ZN":  Instrument("ZN",  "10-Year T-Note",      0.015625, 15.625, 2000, "CBOT"),
    # FX
    "6E":  Instrument("6E",  "Euro FX",             0.00005, 6.25, 3000, "CME"),
    "6J":  Instrument("6J",  "Japanese Yen",        0.0000005, 6.25, 3000, "CME"),
}


def get_instrument(symbol: str) -> Instrument:
    sym = symbol.upper()
    if sym not in INSTRUMENTS:
        # Unknown symbol: fall back to a generic 0.25 tick / $1 spec so the
        # engine still runs, but warn loudly via the name.
        return Instrument(sym, f"UNKNOWN ({sym})", 0.25, 1.0, 1000, "?")
    return INSTRUMENTS[sym]
