"""
Session Point of Control (POC) Indicator

Tracks volume at each price level during the session and calculates
the developing Point of Control - the price with highest volume.
"""
from datetime import time


class SessionPOCIndicator:
    """
    Tracks volume-at-price (VAP) for the current session and computes
    the developing Point of Control (POC) - the price with highest volume.

    Resets daily at session start (configurable).

    Args:
        tick_size: Price granularity for volume bucketing (default: 0.25 for MES)
        value_area_pct: Percentage for Value Area calculation (default: 0.70)
        session_start_hour: Hour when session starts (default: 9)
        session_start_minute: Minute when session starts (default: 30)
    """

    def __init__(self, tick_size=0.25, value_area_pct=0.70,
                 session_start_hour=9, session_start_minute=30):
        self.tick_size = tick_size
        self.value_area_pct = value_area_pct
        self.session_start = time(session_start_hour, session_start_minute)

        # Volume at Price dictionary: {price_level: volume}
        self._volume_profile = {}
        self._total_volume = 0
        self._session_date = None

        # Output values
        self._poc = None       # Point of Control price
        self._poc_volume = 0   # Volume at POC
        self._vah = None       # Value Area High
        self._val = None       # Value Area Low
        self._is_ready = False

        # Tracking for bar count
        self._bar_count = 0

    @property
    def is_ready(self) -> bool:
        """Returns True when indicator has enough data."""
        return self._is_ready

    @property
    def poc(self) -> float:
        """Returns the current Point of Control price."""
        return self._poc

    @property
    def poc_volume(self) -> float:
        """Returns the volume at POC."""
        return self._poc_volume

    @property
    def vah(self) -> float:
        """Returns the Value Area High."""
        return self._vah

    @property
    def val(self) -> float:
        """Returns the Value Area Low."""
        return self._val

    @property
    def total_volume(self) -> float:
        """Returns total session volume."""
        return self._total_volume

    def reset(self):
        """Reset indicator for new session."""
        self._volume_profile = {}
        self._total_volume = 0
        self._poc = None
        self._poc_volume = 0
        self._vah = None
        self._val = None
        self._is_ready = False
        self._bar_count = 0

    def update(self, bar, current_time):
        """
        Update volume profile with new bar data.

        Args:
            bar: TradeBar with OHLCV data
            current_time: DateTime for session tracking (in NY timezone)

        Returns:
            dict with 'poc', 'vah', 'val', 'poc_volume', 'is_ready'
        """
        current_date = current_time.date()
        time_of_day = current_time.time()

        # Check for new session (date change and after session start)
        if self._session_date != current_date:
            if time_of_day >= self.session_start:
                self.reset()
                self._session_date = current_date

        # Only process bars during regular session
        if time_of_day < self.session_start:
            return self._get_result()

        # Increment bar count
        self._bar_count += 1

        # Distribute volume across price levels touched by the bar
        self._distribute_bar_volume(bar)

        # Calculate POC and Value Area
        self._calculate_poc()
        self._calculate_value_area()

        # Mark ready after minimum bars
        if self._bar_count >= 5 and self._poc is not None:
            self._is_ready = True

        return self._get_result()

    def _get_result(self):
        """Get current indicator values as dict."""
        return {
            'poc': self._poc,
            'vah': self._vah,
            'val': self._val,
            'poc_volume': self._poc_volume,
            'is_ready': self._is_ready
        }

    def _round_to_tick(self, price):
        """Round price to nearest tick size."""
        return round(price / self.tick_size) * self.tick_size

    def _distribute_bar_volume(self, bar):
        """
        Distribute bar volume across price levels.

        Uses a weighted distribution that assigns more volume near
        the typical price (OHLC average).
        """
        if bar.Volume <= 0:
            return

        low_bucket = self._round_to_tick(bar.Low)
        high_bucket = self._round_to_tick(bar.High)

        # Get all price levels in the bar's range
        price_levels = []
        current_price = low_bucket
        while current_price <= high_bucket:
            price_levels.append(current_price)
            current_price = self._round_to_tick(current_price + self.tick_size)

        if len(price_levels) == 0:
            return

        # Calculate typical price for weighted distribution
        typical_price = (bar.High + bar.Low + bar.Close) / 3
        typical_bucket = self._round_to_tick(typical_price)

        # Distribute volume with weight toward typical price
        total_weight = 0
        weights = {}

        for price in price_levels:
            # Weight decreases with distance from typical price
            distance = abs(price - typical_bucket)
            weight = 1.0 / (1.0 + distance / self.tick_size)
            weights[price] = weight
            total_weight += weight

        # Normalize and assign volume
        for price in price_levels:
            volume_share = (weights[price] / total_weight) * bar.Volume
            self._volume_profile[price] = self._volume_profile.get(price, 0) + volume_share

        self._total_volume += bar.Volume

    def _calculate_poc(self):
        """Calculate Point of Control (price with highest volume)."""
        if not self._volume_profile:
            return

        max_volume = 0
        poc_price = None

        for price, volume in self._volume_profile.items():
            if volume > max_volume:
                max_volume = volume
                poc_price = price

        self._poc = poc_price
        self._poc_volume = max_volume

    def _calculate_value_area(self):
        """
        Calculate Value Area High and Low.

        Value Area is the price range where value_area_pct (default 70%)
        of total volume traded.
        """
        if not self._volume_profile or self._total_volume == 0 or self._poc is None:
            return

        target_volume = self._total_volume * self.value_area_pct

        # Start from POC and expand outward
        sorted_prices = sorted(self._volume_profile.keys())
        poc_index = None

        for i, price in enumerate(sorted_prices):
            if price == self._poc:
                poc_index = i
                break

        if poc_index is None:
            # POC not in sorted list (shouldn't happen)
            self._vah = max(self._volume_profile.keys())
            self._val = min(self._volume_profile.keys())
            return

        # Expand from POC
        accumulated_volume = self._volume_profile[self._poc]
        low_index = poc_index
        high_index = poc_index

        while accumulated_volume < target_volume:
            # Compare volume one step up vs one step down
            can_go_up = high_index + 1 < len(sorted_prices)
            can_go_down = low_index - 1 >= 0

            if not can_go_up and not can_go_down:
                break

            volume_up = 0
            volume_down = 0

            if can_go_up:
                volume_up = self._volume_profile[sorted_prices[high_index + 1]]
            if can_go_down:
                volume_down = self._volume_profile[sorted_prices[low_index - 1]]

            # Expand toward higher volume
            if volume_up >= volume_down and can_go_up:
                high_index += 1
                accumulated_volume += volume_up
            elif can_go_down:
                low_index -= 1
                accumulated_volume += volume_down
            elif can_go_up:
                high_index += 1
                accumulated_volume += volume_up

        self._vah = sorted_prices[high_index]
        self._val = sorted_prices[low_index]

    def get_distance_to_poc(self, current_price) -> float:
        """
        Calculate distance from current price to POC.

        Args:
            current_price: Current market price

        Returns:
            Distance in points (positive if price > POC)
        """
        if self._poc is None:
            return None
        return current_price - self._poc

    def is_price_in_value_area(self, price) -> bool:
        """
        Check if price is within the Value Area.

        Args:
            price: Price to check

        Returns:
            True if price is between VAL and VAH
        """
        if self._val is None or self._vah is None:
            return False
        return self._val <= price <= self._vah
