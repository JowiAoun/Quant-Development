"""
Candle Pattern Detector

Detects candlestick patterns for entry confirmation signals.
"""
from collections import deque


class CandlePatternDetector:
    """
    Detects candlestick patterns for entry confirmation.

    Patterns Detected:
    - Rejection Candles (Hammer/Shooting Star)
    - Engulfing Patterns (Bullish/Bearish)
    - Volume Climax with Reversal

    Args:
        wick_body_ratio: Minimum wick-to-body ratio for rejection candles (default: 2.0)
        lookback: Bars to store for pattern detection (default: 5)
        volume_lookback: Bars for volume average calculation (default: 20)
        volume_climax_mult: Multiplier for volume climax detection (default: 2.0)
    """

    def __init__(self, wick_body_ratio=2.0, lookback=5,
                 volume_lookback=20, volume_climax_mult=2.0):
        self.wick_body_ratio = wick_body_ratio
        self.volume_climax_mult = volume_climax_mult
        self._bars = deque(maxlen=lookback)
        self._volumes = deque(maxlen=volume_lookback)

        # Last detected patterns (for external access)
        self._last_patterns = self._empty_patterns()

    def _empty_patterns(self):
        """Return empty patterns dict."""
        return {
            'bullish_rejection': False,
            'bearish_rejection': False,
            'bullish_engulfing': False,
            'bearish_engulfing': False,
            'volume_climax_bullish': False,
            'volume_climax_bearish': False,
            'any_bullish': False,
            'any_bearish': False
        }

    @property
    def last_patterns(self):
        """Returns last detected patterns."""
        return self._last_patterns

    def has_bullish_confirmation(self) -> bool:
        """Check if any bullish confirmation signal was detected."""
        return self._last_patterns['any_bullish']

    def has_bearish_confirmation(self) -> bool:
        """Check if any bearish confirmation signal was detected."""
        return self._last_patterns['any_bearish']

    def update(self, bar):
        """
        Update with new bar and detect patterns.

        Args:
            bar: TradeBar with OHLCV data

        Returns:
            dict with detected patterns
        """
        # Store bar data
        bar_data = {
            'open': bar.Open,
            'high': bar.High,
            'low': bar.Low,
            'close': bar.Close,
            'volume': bar.Volume
        }
        self._bars.append(bar_data)
        self._volumes.append(bar.Volume)

        # Reset patterns
        patterns = self._empty_patterns()

        # Need at least 2 bars for pattern detection
        if len(self._bars) < 2:
            self._last_patterns = patterns
            return patterns

        current = self._bars[-1]
        previous = self._bars[-2]

        # Detect rejection candles
        rejection = self._detect_rejection_candle(current)
        if rejection == 'bullish':
            patterns['bullish_rejection'] = True
        elif rejection == 'bearish':
            patterns['bearish_rejection'] = True

        # Detect engulfing patterns
        engulfing = self._detect_engulfing(current, previous)
        if engulfing == 'bullish':
            patterns['bullish_engulfing'] = True
        elif engulfing == 'bearish':
            patterns['bearish_engulfing'] = True

        # Detect volume climax
        climax = self._detect_volume_climax(current)
        if climax == 'bullish':
            patterns['volume_climax_bullish'] = True
        elif climax == 'bearish':
            patterns['volume_climax_bearish'] = True

        # Aggregate signals
        patterns['any_bullish'] = (
            patterns['bullish_rejection'] or
            patterns['bullish_engulfing'] or
            patterns['volume_climax_bullish']
        )
        patterns['any_bearish'] = (
            patterns['bearish_rejection'] or
            patterns['bearish_engulfing'] or
            patterns['volume_climax_bearish']
        )

        self._last_patterns = patterns
        return patterns

    def _detect_rejection_candle(self, bar):
        """
        Detect rejection candle (hammer or shooting star).

        Args:
            bar: Bar data dict

        Returns:
            'bullish' for hammer, 'bearish' for shooting star, None otherwise
        """
        body = abs(bar['close'] - bar['open'])
        upper_wick = bar['high'] - max(bar['close'], bar['open'])
        lower_wick = min(bar['close'], bar['open']) - bar['low']

        # Avoid division by zero
        if body < 0.0001:
            # Doji-like candle - check dominant wick
            if lower_wick > upper_wick * 2:
                return 'bullish'  # Dragonfly doji
            elif upper_wick > lower_wick * 2:
                return 'bearish'  # Gravestone doji
            return None

        # Hammer (bullish rejection)
        # Lower wick >= 2x body, small upper wick
        if lower_wick >= body * self.wick_body_ratio and upper_wick < body:
            return 'bullish'

        # Shooting Star (bearish rejection)
        # Upper wick >= 2x body, small lower wick
        if upper_wick >= body * self.wick_body_ratio and lower_wick < body:
            return 'bearish'

        return None

    def _detect_engulfing(self, current, previous):
        """
        Detect engulfing pattern.

        Args:
            current: Current bar data dict
            previous: Previous bar data dict

        Returns:
            'bullish' or 'bearish' if pattern found, None otherwise
        """
        prev_body = abs(previous['close'] - previous['open'])
        curr_body = abs(current['close'] - current['open'])

        # Current body should be larger
        if curr_body <= prev_body:
            return None

        # Bullish Engulfing
        # Previous: bearish (close < open)
        # Current: bullish (close > open)
        # Current opens at/below prev close, closes at/above prev open
        if (previous['close'] < previous['open'] and  # Prev was bearish
            current['close'] > current['open'] and    # Current is bullish
            current['open'] <= previous['close'] and  # Opens at/below prev close
            current['close'] >= previous['open']):    # Closes at/above prev open
            return 'bullish'

        # Bearish Engulfing
        # Previous: bullish (close > open)
        # Current: bearish (close < open)
        # Current opens at/above prev close, closes at/below prev open
        if (previous['close'] > previous['open'] and  # Prev was bullish
            current['close'] < current['open'] and    # Current is bearish
            current['open'] >= previous['close'] and  # Opens at/above prev close
            current['close'] <= previous['open']):    # Closes at/below prev open
            return 'bearish'

        return None

    def _detect_volume_climax(self, bar):
        """
        Detect volume climax with potential reversal.

        Args:
            bar: Current bar data dict

        Returns:
            'bullish' or 'bearish' if climax detected, None otherwise
        """
        if len(self._volumes) < 10:
            return None

        # Calculate average volume
        volumes_list = list(self._volumes)
        avg_volume = sum(volumes_list[-10:]) / 10

        # Check for climax (volume > 2x average)
        if bar['volume'] <= avg_volume * self.volume_climax_mult:
            return None

        # Climax detected - determine direction based on candle
        if bar['close'] > bar['open']:
            return 'bullish'
        elif bar['close'] < bar['open']:
            return 'bearish'

        return None

    def get_pattern_strength(self) -> str:
        """
        Get overall pattern strength.

        Returns:
            'strong', 'moderate', or 'weak' based on patterns detected
        """
        bullish_count = sum([
            self._last_patterns['bullish_rejection'],
            self._last_patterns['bullish_engulfing'],
            self._last_patterns['volume_climax_bullish']
        ])
        bearish_count = sum([
            self._last_patterns['bearish_rejection'],
            self._last_patterns['bearish_engulfing'],
            self._last_patterns['volume_climax_bearish']
        ])

        max_count = max(bullish_count, bearish_count)

        if max_count >= 2:
            return 'strong'
        elif max_count == 1:
            return 'moderate'
        else:
            return 'weak'

    def get_signal_direction(self) -> str:
        """
        Get signal direction if any patterns detected.

        Returns:
            'bullish', 'bearish', 'mixed', or None
        """
        has_bullish = self._last_patterns['any_bullish']
        has_bearish = self._last_patterns['any_bearish']

        if has_bullish and has_bearish:
            return 'mixed'
        elif has_bullish:
            return 'bullish'
        elif has_bearish:
            return 'bearish'
        else:
            return None

    def reset(self):
        """Reset indicator state."""
        self._bars.clear()
        self._volumes.clear()
        self._last_patterns = self._empty_patterns()
