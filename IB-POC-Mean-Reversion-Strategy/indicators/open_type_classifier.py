"""
Open Type Classifier

Analyzes the first 30 minutes of trading to classify the market open type.
This helps identify trend day probability and whether to trade the session.
"""
from collections import deque
from datetime import time


class OpenTypeClassifier:
    """
    Classifies the market open type based on first 30 minutes of price action.

    Open Types:
    - OPEN_DRIVE: Strong directional move from open with no pullback
      (HIGH trend probability - SKIP session)
    - OPEN_TEST_DRIVE: Brief test opposite direction, then sustained move
      (Moderate trend risk - Proceed with caution)
    - OPEN_REJECTION_REVERSE: Tests one direction, rejected, reverses
      (Balanced day likely - PROCEED)
    - OPEN_AUCTION: Rotational price discovery, no clear direction
      (Balanced day likely - PROCEED)

    Args:
        analysis_period_minutes: Minutes from open to analyze (default: 30)
        market_open_hour: Market open hour (default: 9)
        market_open_minute: Market open minute (default: 30)
    """

    # Open type constants
    OPEN_DRIVE = 'open_drive'
    OPEN_TEST_DRIVE = 'open_test_drive'
    OPEN_REJECTION_REVERSE = 'open_rejection_reverse'
    OPEN_AUCTION = 'open_auction'
    UNKNOWN = 'unknown'

    def __init__(self, analysis_period_minutes=30,
                 market_open_hour=9, market_open_minute=30):
        self.analysis_minutes = analysis_period_minutes
        self.market_open = time(market_open_hour, market_open_minute)

        # Calculate analysis end time
        total_minutes = market_open_hour * 60 + market_open_minute + analysis_period_minutes
        end_hour = total_minutes // 60
        end_minute = total_minutes % 60
        self.analysis_end = time(end_hour, end_minute)

        # Session tracking
        self._current_date = None
        self._open_price = None
        self._bars = deque(maxlen=analysis_period_minutes + 5)
        self._classification = None
        self._classification_complete = False

        # Market structure tracking
        self._first_move_direction = None  # 'up' or 'down'
        self._max_high = None
        self._min_low = None
        self._first_bar_close = None

    @property
    def classification(self) -> str:
        """Returns the classified open type."""
        return self._classification

    @property
    def is_ready(self) -> bool:
        """Returns True when classification is complete."""
        return self._classification_complete

    @property
    def is_trend_day_likely(self) -> bool:
        """Returns True if Open Drive detected (skip trading)."""
        return self._classification == self.OPEN_DRIVE

    @property
    def is_balanced_day_likely(self) -> bool:
        """Returns True if balanced day patterns detected."""
        return self._classification in [self.OPEN_REJECTION_REVERSE, self.OPEN_AUCTION]

    def reset(self):
        """Reset for new session."""
        self._open_price = None
        self._bars.clear()
        self._classification = None
        self._classification_complete = False
        self._first_move_direction = None
        self._max_high = None
        self._min_low = None
        self._first_bar_close = None

    def update(self, bar, current_time):
        """
        Update classifier with new bar data.

        Args:
            bar: TradeBar with OHLCV data
            current_time: DateTime in local timezone (NY)

        Returns:
            dict with classification status
        """
        current_date = current_time.date()
        time_of_day = current_time.time()

        # Reset for new session
        if self._current_date != current_date:
            self.reset()
            self._current_date = current_date

        # Before market open
        if time_of_day < self.market_open:
            return self._get_result()

        # Classification already complete
        if self._classification_complete:
            return self._get_result()

        # After analysis period - finalize classification
        if time_of_day >= self.analysis_end:
            if not self._classification_complete:
                self._classify()
            return self._get_result()

        # Within analysis period - collect data
        self._collect_bar_data(bar, current_time)

        return self._get_result()

    def _get_result(self):
        """Get current classification result as dict."""
        return {
            'classification': self._classification,
            'is_ready': self._classification_complete,
            'is_trend_day_likely': self.is_trend_day_likely,
            'is_balanced_day_likely': self.is_balanced_day_likely,
            'first_move_direction': self._first_move_direction
        }

    def _collect_bar_data(self, bar, current_time):
        """Collect and process bar data during analysis period."""
        # Record first bar data
        if self._open_price is None:
            self._open_price = bar.Open
            self._max_high = bar.High
            self._min_low = bar.Low
            self._first_bar_close = bar.Close

        # Store bar data
        bar_data = {
            'open': bar.Open,
            'high': bar.High,
            'low': bar.Low,
            'close': bar.Close,
            'volume': bar.Volume,
            'time': current_time
        }
        self._bars.append(bar_data)

        # Update session extremes
        if bar.High > self._max_high:
            self._max_high = bar.High
        if bar.Low < self._min_low:
            self._min_low = bar.Low

        # Determine first significant move direction (after 5 bars)
        if self._first_move_direction is None and len(self._bars) >= 5:
            bars_list = list(self._bars)
            fifth_bar_close = bars_list[4]['close']

            # Need 0.1% move from open to determine direction
            threshold = self._open_price * 0.001

            if fifth_bar_close > self._open_price + threshold:
                self._first_move_direction = 'up'
            elif fifth_bar_close < self._open_price - threshold:
                self._first_move_direction = 'down'
            else:
                # No significant move yet - might be auction
                self._first_move_direction = 'neutral'

    def _classify(self):
        """Perform classification based on collected data."""
        if len(self._bars) < 15:
            self._classification = self.UNKNOWN
            self._classification_complete = True
            return

        bars_list = list(self._bars)
        final_close = bars_list[-1]['close']

        # Calculate key metrics
        total_range = self._max_high - self._min_low
        if total_range == 0:
            self._classification = self.OPEN_AUCTION
            self._classification_complete = True
            return

        # Net move from open
        net_move = final_close - self._open_price
        net_move_pct = abs(net_move) / self._open_price if self._open_price > 0 else 0

        # Calculate where close is relative to range
        if self._first_move_direction == 'up':
            # For up move, end_position is how close we are to high
            end_position = (final_close - self._min_low) / total_range
        elif self._first_move_direction == 'down':
            # For down move, end_position is how close we are to low
            end_position = (self._max_high - final_close) / total_range
        else:
            # Neutral - use distance from midpoint
            midpoint = (self._max_high + self._min_low) / 2
            end_position = 0.5 + (final_close - midpoint) / total_range

        # Count directional bars
        up_bars = sum(1 for b in bars_list if b['close'] > b['open'])
        down_bars = sum(1 for b in bars_list if b['close'] < b['open'])
        total_bars = len(bars_list)
        directional_ratio = max(up_bars, down_bars) / total_bars if total_bars > 0 else 0.5

        # Check for pullback in first 10 bars
        had_early_pullback = self._check_early_pullback(bars_list[:10])

        # Check for rejection pattern
        had_rejection = self._check_rejection(bars_list)

        # Classification logic
        self._classification = self._determine_open_type(
            directional_ratio, end_position, net_move_pct,
            had_early_pullback, had_rejection
        )
        self._classification_complete = True

    def _check_early_pullback(self, early_bars):
        """Check if there was a pullback in early bars."""
        if not early_bars or self._first_move_direction == 'neutral':
            return False

        for bar in early_bars[1:]:  # Skip first bar
            if self._first_move_direction == 'up':
                # Pullback = close below open
                if bar['close'] < self._open_price:
                    return True
            elif self._first_move_direction == 'down':
                # Pullback = close above open
                if bar['close'] > self._open_price:
                    return True

        return False

    def _check_rejection(self, bars_list):
        """Check if price was rejected from extreme."""
        if len(bars_list) < 10:
            return False

        # Find when high/low was made
        high_bar_index = 0
        low_bar_index = 0

        for i, bar in enumerate(bars_list):
            if bar['high'] == self._max_high:
                high_bar_index = i
            if bar['low'] == self._min_low:
                low_bar_index = i

        # Rejection if extreme was made early and price moved away
        bars_after_high = len(bars_list) - high_bar_index
        bars_after_low = len(bars_list) - low_bar_index

        # If high made in first third and closed in lower half
        final_close = bars_list[-1]['close']
        midpoint = (self._max_high + self._min_low) / 2

        if high_bar_index <= len(bars_list) // 3 and final_close < midpoint:
            return True

        if low_bar_index <= len(bars_list) // 3 and final_close > midpoint:
            return True

        return False

    def _determine_open_type(self, directional_ratio, end_position, net_move_pct,
                             had_early_pullback, had_rejection):
        """Determine the open type based on metrics."""
        # Open Drive: Strong directional, price stays near extreme
        if directional_ratio > 0.70 and end_position > 0.75 and not had_early_pullback:
            return self.OPEN_DRIVE

        # Open Rejection Reverse: Clear rejection from extreme
        if had_rejection and end_position < 0.40:
            return self.OPEN_REJECTION_REVERSE

        # Open Test Drive: Early pullback but then resumed direction
        if had_early_pullback and end_position > 0.60 and net_move_pct > 0.002:
            return self.OPEN_TEST_DRIVE

        # Open Drive (secondary check): Strong move even with minor pullback
        if directional_ratio > 0.65 and end_position > 0.70 and net_move_pct > 0.003:
            return self.OPEN_DRIVE

        # Default: Open Auction (rotational, balanced)
        return self.OPEN_AUCTION

    def get_description(self) -> str:
        """Get human-readable description of current classification."""
        descriptions = {
            self.OPEN_DRIVE: "Open Drive - Strong directional move, trend day likely (SKIP)",
            self.OPEN_TEST_DRIVE: "Open Test Drive - Brief test then trend (CAUTION)",
            self.OPEN_REJECTION_REVERSE: "Open Rejection Reverse - Balanced day likely (PROCEED)",
            self.OPEN_AUCTION: "Open Auction - Rotational discovery (PROCEED)",
            self.UNKNOWN: "Unknown - Insufficient data",
            None: "Pending - Analysis in progress"
        }
        return descriptions.get(self._classification, "Unknown classification")
