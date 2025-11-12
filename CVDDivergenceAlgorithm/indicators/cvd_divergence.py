"""
CVD Divergence Indicator
Detects bullish and bearish divergences between price and Cumulative Volume Delta.
"""
from AlgorithmImports import *
from collections import deque


class CVDDivergenceIndicator:
    """
    Tracks Cumulative Volume Delta and detects divergences with price fractals.

    Args:
        cvd_period: Period for summing volume delta
        fractal_periods: Number of bars on each side for fractal detection
        ema_period: Period for trend-following EMA filter
        max_bars_between_fractals: Maximum bars between fractals for divergence
    """

    def __init__(self, cvd_period=21, fractal_periods=2, ema_period=50, max_bars_between_fractals=30):
        self.cvd_period = cvd_period
        self.fractal_periods = fractal_periods
        self.ema_period = ema_period
        self.max_bars_between_fractals = max_bars_between_fractals

        # Store recent bars for fractal and CVD calculation
        self.bars = deque(maxlen=max(cvd_period, fractal_periods * 2 + 1, ema_period) + 10)
        self.cvd_values = deque(maxlen=max_bars_between_fractals + 50)

        # Track fractals
        self.bullish_fractals = []  # (bar_index, price, cvd_value)
        self.bearish_fractals = []  # (bar_index, price, cvd_value)

        # Divergence tracking
        self.last_bull_divergence_bar = -100
        self.last_bear_divergence_bar = -100
        self.consecutive_bull_divergences = 0
        self.consecutive_bear_divergences = 0

        self.bar_index = 0
        self.is_ready = False

    def update(self, bar):
        """
        Update indicator with new bar data.

        Args:
            bar: TradeBar object with OHLCV data

        Returns:
            dict with 'signal' (None, 'bullish', 'bearish'), 'strength', and 'cvd'
        """
        self.bar_index += 1

        # Store bar
        bar_data = {
            'index': self.bar_index,
            'time': bar.Time,
            'open': bar.Open,
            'high': bar.High,
            'low': bar.Low,
            'close': bar.Close,
            'volume': bar.Volume
        }
        self.bars.append(bar_data)

        # Calculate volume delta for this bar
        price_range = bar.High - bar.Low
        if price_range > 0:
            buying_volume = bar.Volume * ((bar.Close - bar.Low) / price_range)
            selling_volume = bar.Volume * ((bar.High - bar.Close) / price_range)
            delta = buying_volume - selling_volume
        else:
            delta = 0

        # Calculate periodic CVD (sum of last cvd_period deltas)
        cvd_value = self._calculate_periodic_cvd(delta)
        self.cvd_values.append({'index': self.bar_index, 'value': cvd_value})

        # Check if we have enough data
        if len(self.bars) < max(self.cvd_period, self.fractal_periods * 2 + 1, self.ema_period):
            return {'signal': None, 'strength': None, 'cvd': cvd_value}

        self.is_ready = True

        # Detect fractals
        self._detect_fractals()

        # Detect divergences
        signal = self._detect_divergences()

        return {
            'signal': signal['type'],
            'strength': signal['strength'],
            'cvd': cvd_value
        }

    def _calculate_periodic_cvd(self, current_delta):
        """Calculate sum of deltas over the period."""
        # Store delta in a temporary list
        if not hasattr(self, '_deltas'):
            self._deltas = deque(maxlen=self.cvd_period)
        self._deltas.append(current_delta)
        return sum(self._deltas)

    def _get_ema(self, offset=0):
        """Calculate EMA at the given offset from current bar."""
        if len(self.bars) < self.ema_period + offset:
            return None

        # Simple EMA calculation
        bars_slice = list(self.bars)[-(self.ema_period + offset + 1):len(self.bars) - offset if offset > 0 else None]
        closes = [b['close'] for b in bars_slice]

        multiplier = 2 / (self.ema_period + 1)
        ema = closes[0]
        for close in closes[1:]:
            ema = (close - ema) * multiplier + ema
        return ema

    def _detect_fractals(self):
        """Detect pivot highs (bearish fractal) and pivot lows (bullish fractal)."""
        n = self.fractal_periods

        # Need enough bars to look back
        if len(self.bars) < n * 2 + 1:
            return

        # Check the bar at position -n-1 (n bars ago)
        bars_list = list(self.bars)
        check_index = -(n + 1)
        center_bar = bars_list[check_index]

        # Get EMA for trend filter
        ema = self._get_ema(n)
        if ema is None:
            return

        # Check for pivot high (bearish fractal) - requires uptrend
        is_pivot_high = True
        if center_bar['close'] > ema:  # Uptrend
            for i in range(1, n + 1):
                if bars_list[check_index - i]['high'] >= center_bar['high'] or \
                   bars_list[check_index + i]['high'] >= center_bar['high']:
                    is_pivot_high = False
                    break

            if is_pivot_high:
                # Get CVD value at this fractal
                cvd_at_fractal = self._get_cvd_at_index(center_bar['index'])
                if cvd_at_fractal is not None and cvd_at_fractal > 0:
                    self.bearish_fractals.append((center_bar['index'], center_bar['high'], cvd_at_fractal))
                    # Keep only recent fractals
                    if len(self.bearish_fractals) > 10:
                        self.bearish_fractals.pop(0)

        # Check for pivot low (bullish fractal) - requires downtrend
        is_pivot_low = True
        if center_bar['close'] < ema:  # Downtrend
            for i in range(1, n + 1):
                if bars_list[check_index - i]['low'] <= center_bar['low'] or \
                   bars_list[check_index + i]['low'] <= center_bar['low']:
                    is_pivot_low = False
                    break

            if is_pivot_low:
                # Get CVD value at this fractal
                cvd_at_fractal = self._get_cvd_at_index(center_bar['index'])
                if cvd_at_fractal is not None and cvd_at_fractal < 0:
                    self.bullish_fractals.append((center_bar['index'], center_bar['low'], cvd_at_fractal))
                    # Keep only recent fractals
                    if len(self.bullish_fractals) > 10:
                        self.bullish_fractals.pop(0)

    def _get_cvd_at_index(self, bar_index):
        """Get CVD value at a specific bar index."""
        for cvd_data in self.cvd_values:
            if cvd_data['index'] == bar_index:
                return cvd_data['value']
        return None

    def _detect_divergences(self):
        """
        Detect bullish and bearish divergences.

        Returns:
            dict with 'type' (None, 'bullish', 'bearish') and 'strength' (Normal, Good, Strong)
        """
        current_bar = self.bar_index

        # Check for bullish divergence (price lower low, CVD higher low)
        if len(self.bullish_fractals) >= 2:
            last_fractal = self.bullish_fractals[-1]
            prev_fractal = self.bullish_fractals[-2]

            last_idx, last_price, last_cvd = last_fractal
            prev_idx, prev_price, prev_cvd = prev_fractal

            # Check conditions
            bars_apart = last_idx - prev_idx
            time_valid = (current_bar - last_idx) <= self.max_bars_between_fractals

            if bars_apart < self.max_bars_between_fractals and time_valid:
                # Price lower low AND CVD higher low = bullish divergence
                if last_price < prev_price and last_cvd > prev_cvd:
                    # Check if this is a new divergence
                    if last_idx != self.last_bull_divergence_bar:
                        self.last_bull_divergence_bar = last_idx
                        self.consecutive_bull_divergences += 1
                        self.consecutive_bear_divergences = 0  # Reset bear count

                        strength = self._get_divergence_strength(self.consecutive_bull_divergences)
                        return {'type': 'bullish', 'strength': strength}

        # Check for bearish divergence (price higher high, CVD lower high)
        if len(self.bearish_fractals) >= 2:
            last_fractal = self.bearish_fractals[-1]
            prev_fractal = self.bearish_fractals[-2]

            last_idx, last_price, last_cvd = last_fractal
            prev_idx, prev_price, prev_cvd = prev_fractal

            # Check conditions
            bars_apart = last_idx - prev_idx
            time_valid = (current_bar - last_idx) <= self.max_bars_between_fractals

            if bars_apart < self.max_bars_between_fractals and time_valid:
                # Price higher high AND CVD lower high = bearish divergence
                if last_price > prev_price and last_cvd < prev_cvd:
                    # Check if this is a new divergence
                    if last_idx != self.last_bear_divergence_bar:
                        self.last_bear_divergence_bar = last_idx
                        self.consecutive_bear_divergences += 1
                        self.consecutive_bull_divergences = 0  # Reset bull count

                        strength = self._get_divergence_strength(self.consecutive_bear_divergences)
                        return {'type': 'bearish', 'strength': strength}

        # Reset consecutive counts if no divergence for a while
        if current_bar - self.last_bull_divergence_bar > self.max_bars_between_fractals:
            self.consecutive_bull_divergences = 0
        if current_bar - self.last_bear_divergence_bar > self.max_bars_between_fractals:
            self.consecutive_bear_divergences = 0

        return {'type': None, 'strength': None}

    def _get_divergence_strength(self, consecutive_count):
        """Determine divergence strength based on consecutive occurrences."""
        if consecutive_count == 1:
            return "Normal"
        elif consecutive_count == 2:
            return "Good"
        else:
            return "Strong"
