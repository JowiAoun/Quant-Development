"""
Prior Day Context Indicator

Tracks and stores prior day's key levels for pre-market context analysis.
"""
from collections import deque
from datetime import time


class PriorDayContext:
    """
    Tracks and stores prior day's key levels for pre-market context.

    Maintains:
    - Prior Day High (PDH)
    - Prior Day Low (PDL)
    - Prior Day Range
    - Prior Day POC (from SessionPOCIndicator)
    - Prior Day Value Area High/Low

    Args:
        history_days: Number of days to maintain history (default: 5)
        session_start_hour: Session start hour (default: 9)
        session_start_minute: Session start minute (default: 30)
        session_end_hour: Session end hour (default: 16)
        session_end_minute: Session end minute (default: 0)
    """

    def __init__(self, history_days=5, session_start_hour=9, session_start_minute=30,
                 session_end_hour=16, session_end_minute=0):
        self._history = deque(maxlen=history_days)
        self.session_start = time(session_start_hour, session_start_minute)
        self.session_end = time(session_end_hour, session_end_minute)
        self._current_date = None

        # Intraday accumulation (current session)
        self._session_high = None
        self._session_low = None
        self._session_open = None
        self._session_close = None
        self._session_poc = None
        self._session_vah = None
        self._session_val = None

        # Prior day values (populated after session change)
        self._prior_day_high = None
        self._prior_day_low = None
        self._prior_day_open = None
        self._prior_day_close = None
        self._prior_day_poc = None
        self._prior_day_vah = None
        self._prior_day_val = None

        self._is_ready = False

    @property
    def is_ready(self) -> bool:
        """Returns True when prior day data is available."""
        return self._is_ready

    @property
    def pdh(self) -> float:
        """Returns Prior Day High."""
        return self._prior_day_high

    @property
    def pdl(self) -> float:
        """Returns Prior Day Low."""
        return self._prior_day_low

    @property
    def prior_day_open(self) -> float:
        """Returns Prior Day Open."""
        return self._prior_day_open

    @property
    def prior_day_close(self) -> float:
        """Returns Prior Day Close."""
        return self._prior_day_close

    @property
    def prior_day_range(self) -> float:
        """Returns Prior Day Range (PDH - PDL)."""
        if self._prior_day_high is not None and self._prior_day_low is not None:
            return self._prior_day_high - self._prior_day_low
        return None

    @property
    def prior_poc(self) -> float:
        """Returns Prior Day Point of Control."""
        return self._prior_day_poc

    @property
    def prior_vah(self) -> float:
        """Returns Prior Day Value Area High."""
        return self._prior_day_vah

    @property
    def prior_val(self) -> float:
        """Returns Prior Day Value Area Low."""
        return self._prior_day_val

    @property
    def prior_value_area(self) -> tuple:
        """Returns Prior Day Value Area as (VAL, VAH) tuple."""
        return (self._prior_day_val, self._prior_day_vah)

    def reset_session(self):
        """Reset current session data."""
        self._session_high = None
        self._session_low = None
        self._session_open = None
        self._session_close = None
        self._session_poc = None
        self._session_vah = None
        self._session_val = None

    def update(self, bar, current_time, session_poc_data=None):
        """
        Update prior day context with new bar.

        Args:
            bar: TradeBar with OHLCV data
            current_time: DateTime in local timezone (NY)
            session_poc_data: Dict from SessionPOCIndicator {'poc', 'vah', 'val'}

        Returns:
            dict with prior day levels
        """
        current_date = current_time.date()
        time_of_day = current_time.time()

        # Check for new session (date change)
        if self._current_date != current_date:
            # Save previous day's data if we have valid session data
            if self._current_date is not None and self._session_high is not None:
                day_data = {
                    'date': self._current_date,
                    'high': self._session_high,
                    'low': self._session_low,
                    'open': self._session_open,
                    'close': self._session_close,
                    'poc': self._session_poc,
                    'vah': self._session_vah,
                    'val': self._session_val
                }
                self._history.append(day_data)

                # Update prior day references
                self._prior_day_high = self._session_high
                self._prior_day_low = self._session_low
                self._prior_day_open = self._session_open
                self._prior_day_close = self._session_close
                self._prior_day_poc = self._session_poc
                self._prior_day_vah = self._session_vah
                self._prior_day_val = self._session_val

                self._is_ready = True

            # Reset for new day
            self._current_date = current_date
            self.reset_session()

        # Only track during regular session
        if time_of_day < self.session_start or time_of_day >= self.session_end:
            return self._get_result()

        # Update session data
        if self._session_open is None:
            self._session_open = bar.Open

        if self._session_high is None or bar.High > self._session_high:
            self._session_high = bar.High
        if self._session_low is None or bar.Low < self._session_low:
            self._session_low = bar.Low

        self._session_close = bar.Close

        # Update POC from session indicator
        if session_poc_data:
            self._session_poc = session_poc_data.get('poc')
            self._session_vah = session_poc_data.get('vah')
            self._session_val = session_poc_data.get('val')

        return self._get_result()

    def _get_result(self):
        """Get current indicator values as dict."""
        return {
            'pdh': self._prior_day_high,
            'pdl': self._prior_day_low,
            'prior_open': self._prior_day_open,
            'prior_close': self._prior_day_close,
            'prior_range': self.prior_day_range,
            'prior_poc': self._prior_day_poc,
            'prior_vah': self._prior_day_vah,
            'prior_val': self._prior_day_val,
            'is_ready': self._is_ready
        }

    def is_open_inside_value_area(self, open_price) -> bool:
        """
        Check if today's open is inside prior day's value area.

        Args:
            open_price: Today's opening price

        Returns:
            True if open is within prior VAL and VAH
        """
        if self._prior_day_val is None or self._prior_day_vah is None:
            return False
        return self._prior_day_val <= open_price <= self._prior_day_vah

    def is_open_above_value_area(self, open_price) -> bool:
        """Check if today's open is above prior day's value area."""
        if self._prior_day_vah is None:
            return False
        return open_price > self._prior_day_vah

    def is_open_below_value_area(self, open_price) -> bool:
        """Check if today's open is below prior day's value area."""
        if self._prior_day_val is None:
            return False
        return open_price < self._prior_day_val

    def get_gap_percentage(self, current_open) -> float:
        """
        Calculate gap percentage from prior close.

        Args:
            current_open: Current session's opening price

        Returns:
            Gap as percentage (positive = gap up, negative = gap down)
        """
        if self._prior_day_close is None or self._prior_day_close == 0:
            return None
        return (current_open - self._prior_day_close) / self._prior_day_close

    def is_significant_gap(self, current_open, threshold=0.01) -> bool:
        """
        Check if there's a significant gap (> threshold).

        Args:
            current_open: Current session's opening price
            threshold: Gap threshold (default 1%)

        Returns:
            True if gap exceeds threshold
        """
        gap_pct = self.get_gap_percentage(current_open)
        if gap_pct is None:
            return False
        return abs(gap_pct) > threshold

    def get_overnight_range_ratio(self, overnight_high, overnight_low) -> float:
        """
        Calculate overnight range as ratio of prior day range.

        Args:
            overnight_high: Overnight session high
            overnight_low: Overnight session low

        Returns:
            Ratio of overnight range to prior day range
        """
        if self.prior_day_range is None or self.prior_day_range == 0:
            return None
        overnight_range = overnight_high - overnight_low
        return overnight_range / self.prior_day_range

    def get_average_range(self, days=5) -> float:
        """
        Calculate average daily range over recent history.

        Args:
            days: Number of days to average

        Returns:
            Average daily range
        """
        if len(self._history) == 0:
            return None

        ranges = []
        for day_data in list(self._history)[-days:]:
            day_range = day_data['high'] - day_data['low']
            ranges.append(day_range)

        if not ranges:
            return None
        return sum(ranges) / len(ranges)
