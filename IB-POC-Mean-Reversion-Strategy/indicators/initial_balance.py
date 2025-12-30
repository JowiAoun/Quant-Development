"""
Initial Balance (IB) Indicator

Tracks the Initial Balance (first 60 minutes of trading) for futures,
maintains a rolling average, and classifies IB width.
"""
from collections import deque
from datetime import time


class InitialBalanceIndicator:
    """
    Tracks the Initial Balance (9:30-10:30 AM EST) for futures trading.

    Maintains:
    - Current session IBH, IBL, IB Range, IB Midpoint
    - IB Volume during formation period
    - 20-day rolling average of IB ranges
    - IB width classification (Narrow/Medium/Wide)

    Args:
        ib_start_hour: IB start hour in local timezone (default: 9)
        ib_start_minute: IB start minute (default: 30)
        ib_end_hour: IB end hour (default: 10)
        ib_end_minute: IB end minute (default: 30)
        rolling_period: Days for average calculation (default: 20)
        narrow_threshold: Ratio below which IB is narrow (default: 0.70)
        wide_threshold: Ratio above which IB is wide (default: 1.30)
    """

    def __init__(self, ib_start_hour=9, ib_start_minute=30,
                 ib_end_hour=10, ib_end_minute=30, rolling_period=20,
                 narrow_threshold=0.70, wide_threshold=1.30):
        self.ib_start = time(ib_start_hour, ib_start_minute)
        self.ib_end = time(ib_end_hour, ib_end_minute)
        self.rolling_period = rolling_period
        self.narrow_threshold = narrow_threshold
        self.wide_threshold = wide_threshold

        # Current session data
        self._current_date = None
        self._ibh = None          # IB High
        self._ibl = None          # IB Low
        self._ib_volume = 0       # Total volume during IB
        self._ib_complete = False

        # Historical data
        self._ib_ranges = deque(maxlen=rolling_period)

        self._is_ready = False

    @property
    def is_ready(self) -> bool:
        """Returns True when we have enough historical data."""
        return self._is_ready

    @property
    def ibh(self) -> float:
        """Returns the Initial Balance High."""
        return self._ibh

    @property
    def ibl(self) -> float:
        """Returns the Initial Balance Low."""
        return self._ibl

    @property
    def ib_range(self) -> float:
        """Returns the IB Range (IBH - IBL)."""
        if self._ibh is not None and self._ibl is not None:
            return self._ibh - self._ibl
        return None

    @property
    def ib_midpoint(self) -> float:
        """Returns the IB Midpoint."""
        if self._ibh is not None and self._ibl is not None:
            return (self._ibh + self._ibl) / 2
        return None

    @property
    def ib_volume(self) -> float:
        """Returns total volume during IB formation."""
        return self._ib_volume

    @property
    def ib_complete(self) -> bool:
        """Returns True if IB formation is complete for today."""
        return self._ib_complete

    @property
    def average_ib_range(self) -> float:
        """Returns the 20-day average IB range."""
        if len(self._ib_ranges) == 0:
            return None
        return sum(self._ib_ranges) / len(self._ib_ranges)

    @property
    def ib_ratio(self) -> float:
        """Returns ratio of current IB to 20-day average."""
        if self.ib_range is None or self.average_ib_range is None:
            return None
        if self.average_ib_range == 0:
            return 1.0
        return self.ib_range / self.average_ib_range

    def get_ib_classification(self) -> str:
        """
        Classify current IB as Narrow, Medium, or Wide.

        Returns:
            str: 'narrow', 'medium', or 'wide' (or None if insufficient data)
        """
        ratio = self.ib_ratio
        if ratio is None:
            return None

        if ratio < self.narrow_threshold:
            return 'narrow'
        elif ratio > self.wide_threshold:
            return 'wide'
        else:
            return 'medium'

    def reset_session(self):
        """Reset for new trading session."""
        self._ibh = None
        self._ibl = None
        self._ib_volume = 0
        self._ib_complete = False

    def update(self, bar, current_time):
        """
        Update IB tracking with new bar.

        Args:
            bar: TradeBar with OHLCV data
            current_time: DateTime in local timezone (NY)

        Returns:
            dict with IB status and values
        """
        current_date = current_time.date()
        time_of_day = current_time.time()

        # Reset for new session
        if self._current_date != current_date:
            # Save previous IB range before reset (if valid and complete)
            if self._ib_complete and self.ib_range is not None and self.ib_range > 0:
                self._ib_ranges.append(self.ib_range)

            # Reset for new day
            self._current_date = current_date
            self.reset_session()

        # Check if within IB formation period
        if self.ib_start <= time_of_day < self.ib_end:
            # Update IB high/low
            if self._ibh is None or bar.High > self._ibh:
                self._ibh = bar.High
            if self._ibl is None or bar.Low < self._ibl:
                self._ibl = bar.Low
            self._ib_volume += bar.Volume

        elif time_of_day >= self.ib_end and not self._ib_complete:
            # IB formation complete
            self._ib_complete = True
            # Need at least 5 days of history to be ready
            self._is_ready = len(self._ib_ranges) >= 5

        return self._get_result()

    def _get_result(self):
        """Get current indicator values as dict."""
        return {
            'ibh': self._ibh,
            'ibl': self._ibl,
            'ib_range': self.ib_range,
            'ib_midpoint': self.ib_midpoint,
            'ib_volume': self._ib_volume,
            'ib_complete': self._ib_complete,
            'ib_classification': self.get_ib_classification(),
            'ib_ratio': self.ib_ratio,
            'avg_ib_range': self.average_ib_range,
            'is_ready': self._is_ready
        }

    def get_extension_amount(self, current_price, direction) -> float:
        """
        Calculate how far price has extended beyond IB.

        Args:
            current_price: Current market price
            direction: 'long' (below IBL) or 'short' (above IBH)

        Returns:
            Extension in IB Range multiples (e.g., 0.5 = half IB range)
            Returns 0 if price is still within IB
        """
        if self.ib_range is None or self.ib_range == 0:
            return None

        if direction == 'long' and self._ibl is not None:
            extension = self._ibl - current_price
        elif direction == 'short' and self._ibh is not None:
            extension = current_price - self._ibh
        else:
            return None

        return extension / self.ib_range if extension > 0 else 0

    def is_price_extended(self, current_price, min_extension=0.25) -> tuple:
        """
        Check if price is extended beyond IB.

        Args:
            current_price: Current market price
            min_extension: Minimum extension in IB multiples (default: 0.25)

        Returns:
            tuple (direction, extension_amount) or (None, 0) if not extended
        """
        if self.ib_range is None or self._ibh is None or self._ibl is None:
            return (None, 0)

        # Check extension above IBH (short opportunity)
        if current_price > self._ibh:
            extension = (current_price - self._ibh) / self.ib_range
            if extension >= min_extension:
                return ('short', extension)

        # Check extension below IBL (long opportunity)
        if current_price < self._ibl:
            extension = (self._ibl - current_price) / self.ib_range
            if extension >= min_extension:
                return ('long', extension)

        return (None, 0)

    def get_target_levels(self, direction):
        """
        Get target levels for a trade.

        Args:
            direction: 'long' or 'short'

        Returns:
            dict with 'midpoint', 'ib_high', 'ib_low' levels
        """
        return {
            'midpoint': self.ib_midpoint,
            'ib_high': self._ibh,
            'ib_low': self._ibl
        }

    def get_stop_distance(self, multiplier=0.5) -> float:
        """
        Calculate stop distance based on IB range.

        Args:
            multiplier: Fraction of IB range for stop (default: 0.5)

        Returns:
            Stop distance in points
        """
        if self.ib_range is None:
            return None
        return self.ib_range * multiplier
