"""
CVD Divergence Algorithm for MES Futures
Trades divergences between price and Cumulative Volume Delta during NY session.
"""
from AlgorithmImports import *  # type: ignore
from datetime import time
from indicators.cvd_divergence import CVDDivergenceIndicator


class CVDDivergenceAlgorithm(QCAlgorithm):
    """
    Algorithm that trades MES futures based on CVD divergence signals.

    Strategy:
    - Enter long on bullish divergence (price lower low, CVD higher low)
    - Enter short on bearish divergence (price higher high, CVD lower high)
    - Only trade during NY session (1 hour after open)
    - Risk-based position sizing (1-2% per trade)
    - ATR-based stops and targets with trailing stop mechanism
    """

    def initialize(self):
        """Initialize algorithm parameters, data, and indicators."""
        # Set date range and initial cash
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2024, 12, 31)
        self.set_cash(100000)

        # Log live mode status
        self.debug(f"Live Mode: {self.live_mode}")

        # Set timezone to Eastern for NY session tracking
        self.set_time_zone(TimeZones.NEW_YORK)

        # Add MES futures (Micro E-mini S&P 500)
        self._future = self.add_future(
            Futures.Indices.MICRO_SP_500_E_MINI,
            Resolution.MINUTE,
            data_normalization_mode=DataNormalizationMode.BACKWARDS_RATIO
        )
        self._future.set_filter(0, 90)  # Front month contract

        self._symbol = None  # Will be set to the continuous contract

        # Strategy parameters
        self.cvd_period = self.get_parameter("cvd_period", 21)
        self.fractal_periods = self.get_parameter("fractal_periods", 2)
        self.ema_period = self.get_parameter("ema_period", 50)
        self.atr_period = self.get_parameter("atr_period", 55)
        self.risk_per_trade = self.get_parameter("risk_per_trade", 0.02)
        self.stop_loss_atr_multiplier = self.get_parameter("stop_loss_atr_multiplier", 2.0)
        self.take_profit_atr_multiplier = self.get_parameter("take_profit_atr_multiplier", 3.0)
        self.trailing_stop_atr_multiplier = self.get_parameter("trailing_stop_atr_multiplier", 1.5)

        # Initialize indicators (will be created when symbol is available)
        self._cvd_indicator = None
        self._atr = None
        self._volume_sma = None

        # Position tracking
        self.position = {
            'is_long': False,
            'is_short': False,
            'entry_price': 0,
            'stop_loss': 0,
            'take_profit': 0,
            'trailing_stop_triggered': False,
            'entry_bar': None,
            'stop_distance': 0  # Track distance for trailing stop
        }

        # Pending signal tracking for breakout confirmation
        self.pending_signal = {
            'active': False,
            'type': None,  # 'bullish' or 'bearish'
            'fractal_price': 0,
            'detected_bar': self.start_date,  # Initialize to algorithm start instead of None
            'strength': None
        }

        # NY session tracking (CME E-mini futures trade nearly 24/5)
        # NY session: 9:30 AM - 4:00 PM ET
        # Trade 1 hour after open = 10:30 AM ET onwards
        self.ny_session_start_hour = 10
        self.ny_session_start_minute = 30
        self.ny_session_end_hour = 16
        self.ny_session_end_minute = 0

        # Warm up period
        self.set_warm_up(max(self.cvd_period, self.ema_period, self.atr_period) + 10, Resolution.MINUTE)

    def on_securities_changed(self, changes):
        """Handle changes in the universe of securities."""
        for security in changes.added_securities:
            if security.symbol.security_type == SecurityType.FUTURE:
                self._symbol = security.symbol

                # Initialize indicators with the mapped symbol
                self._cvd_indicator = CVDDivergenceIndicator(
                    cvd_period=self.cvd_period,
                    fractal_periods=self.fractal_periods,
                    ema_period=self.ema_period
                )

                # Initialize ATR indicator
                self._atr = self.atr(self._symbol, self.atr_period)

                # Initialize volume SMA for volume confirmation
                self._volume_sma = self.sma(self._symbol, 20, Resolution.MINUTE, Field.VOLUME)

                self.debug(f"Trading contract: {self._symbol}")

    def on_data(self, data: Slice):
        """Main trading logic executed on each data slice."""
        if self.is_warming_up or self._symbol is None:
            return

        if not data.bars.contains_key(self._symbol):
            return

        bar = data.bars[self._symbol]

        if not self._is_ny_trading_session(self.time):
            return

        signal_data = self._cvd_indicator.update(bar)

        if not self._cvd_indicator.is_ready or not self._atr.is_ready:
            return

        current_price = bar.close
        bar_volume = bar.volume

        if self.position['is_long'] or self.position['is_short']:
            self._manage_position(current_price, signal_data)
        else:
            self._check_entry_signals(current_price, bar_volume, signal_data)

    def _is_ny_trading_session(self, current_time):
        """
        Check if current time is within NY trading session (1 hour after open).

        Args:
            current_time: DateTime object (already in Eastern timezone)

        Returns:
            bool: True if within trading hours
        """
        # Check if it's a weekday
        if current_time.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Check if within trading hours (10:30 AM - 4:00 PM ET)
        time_of_day = current_time.time()
        session_start = time(self.ny_session_start_hour, self.ny_session_start_minute)
        session_end = time(self.ny_session_end_hour, self.ny_session_end_minute)

        return session_start <= time_of_day <= session_end

    def _check_entry_signals(self, current_price, bar_volume, signal_data):
        """
        Check for entry signals with breakout and volume confirmation.

        Args:
            current_price: Current market price
            bar_volume: Current bar volume
            signal_data: Dictionary with 'signal', 'strength', 'cvd', 'fractal_price'
        """
        signal_type = signal_data['signal']
        signal_strength = signal_data['strength']
        fractal_price = signal_data.get('fractal_price')

        # Skip if fractal_price is None (indicator not ready or user's indicator doesn't provide it)
        if fractal_price is None and signal_type is not None:
            self.debug("Divergence detected but fractal_price is None, skipping")
            return

        if signal_type is not None and not self.pending_signal['active']:
            # New divergence detected - set as pending
            self.pending_signal['active'] = True
            self.pending_signal['type'] = signal_type
            self.pending_signal['fractal_price'] = fractal_price
            self.pending_signal['detected_bar'] = self.time
            self.pending_signal['strength'] = signal_strength

            self.debug(f"PENDING {signal_type.upper()} DIVERGENCE | Fractal: {fractal_price:.2f} | "
                      f"Strength: {signal_strength} | Waiting for breakout confirmation")
            return

        if self.pending_signal['active']:
            bars_since_signal = (self.time - self.pending_signal['detected_bar']).total_seconds() / 60

            # Expire pending signal after 10 bars (10 minutes on minute resolution)
            if bars_since_signal > 10:
                self.debug(f"EXPIRED {self.pending_signal['type'].upper()} signal - no breakout after 10 bars")
                self._reset_pending_signal()
                return

            # Check for breakout confirmation
            breakout_buffer = 0.5  # MES points buffer for breakout
            breakout_confirmed = False

            if self.pending_signal['type'] == 'bullish':
                # For bullish: price must break above fractal low
                breakout_confirmed = current_price > (self.pending_signal['fractal_price'] + breakout_buffer)
            elif self.pending_signal['type'] == 'bearish':
                # For bearish: price must break below fractal high
                breakout_confirmed = current_price < (self.pending_signal['fractal_price'] - breakout_buffer)

            # Check volume confirmation
            volume_confirmed = bar_volume > (self._volume_sma.current.value * 1.2) if self._volume_sma.is_ready else True

            # Enter trade if both confirmations met
            if breakout_confirmed and volume_confirmed:
                self._enter_trade_with_pivot_stops(current_price)
            elif breakout_confirmed and not volume_confirmed:
                self.debug(f"Breakout confirmed but volume too low: {bar_volume:.0f} vs {self._volume_sma.current.value * 1.2:.0f}")

    def _enter_trade_with_pivot_stops(self, entry_price):
        """
        Enter trade using pivot-based stops and 1:2 RR.

        Args:
            entry_price: Current market price for entry
        """
        signal_type = self.pending_signal['type']
        fractal_price = self.pending_signal['fractal_price']
        signal_strength = self.pending_signal['strength']

        # Calculate pivot-based stop loss and 1:2 RR target
        if signal_type == 'bullish':
            stop_loss = fractal_price  # Stop just at/below the fractal low
            stop_distance = entry_price - stop_loss
            take_profit = entry_price + (stop_distance * 2)  # 1:2 RR
        else:  # bearish
            stop_loss = fractal_price  # Stop just at/above the fractal high
            stop_distance = stop_loss - entry_price
            take_profit = entry_price - (stop_distance * 2)  # 1:2 RR

        # Calculate position size based on stop distance
        quantity = self._calculate_position_size(stop_distance)

        if quantity == 0:
            self.debug(f"Calculated quantity is 0, skipping trade")
            self._reset_pending_signal()
            return

        # Place order
        if signal_type == 'bullish':
            self.market_order(self._symbol, quantity)
            self.position['is_long'] = True
        else:
            self.market_order(self._symbol, -quantity)
            self.position['is_short'] = True

        # Update position tracking
        self.position['entry_price'] = entry_price
        self.position['stop_loss'] = stop_loss
        self.position['take_profit'] = take_profit
        self.position['stop_distance'] = stop_distance
        self.position['trailing_stop_triggered'] = False
        self.position['entry_bar'] = self.time

        self.debug(f"{signal_type.upper()} ENTRY CONFIRMED | Price: {entry_price:.2f} | "
                  f"Strength: {signal_strength} | Qty: {quantity} | "
                  f"Stop: {stop_loss:.2f} ({stop_distance:.2f} pts) | "
                  f"Target: {take_profit:.2f} | RR: 1:2")

        # Reset pending signal after entry
        self._reset_pending_signal()

    def _reset_pending_signal(self):
        """Reset pending signal tracker."""
        self.pending_signal = {
            'active': False,
            'type': None,
            'fractal_price': 0,
            'detected_bar': self.time,  # Reset to current time, not None
            'strength': None
        }

    def _manage_position(self, current_price, signal_data):
        """
        Manage existing position: check stops, targets, and trailing stops.

        Args:
            current_price: Current market price
            signal_data: Dictionary with 'signal', 'strength', 'cvd', 'fractal_price'
        """
        signal_type = signal_data['signal']

        # Check for opposite signal exit
        if self.position['is_long'] and signal_type == 'bearish':
            self._close_position("Opposite signal (bearish)")
            return
        elif self.position['is_short'] and signal_type == 'bullish':
            self._close_position("Opposite signal (bullish)")
            return

        # Long position management
        if self.position['is_long']:
            # Check take profit
            if current_price >= self.position['take_profit']:
                self._close_position("Take profit hit")
                return

            # Check stop loss
            if current_price <= self.position['stop_loss']:
                self._close_position("Stop loss hit")
                return

            # Trailing stop logic: move stop to breakeven when halfway to target
            if not self.position['trailing_stop_triggered']:
                profit_distance = current_price - self.position['entry_price']
                trailing_threshold = self.position['stop_distance'] * 1.0  # At 1x stop distance (halfway to 2x target)

                if profit_distance >= trailing_threshold:
                    self.position['stop_loss'] = self.position['entry_price']
                    self.position['trailing_stop_triggered'] = True
                    self.debug(f"TRAILING STOP ACTIVATED | Stop moved to breakeven: {self.position['stop_loss']:.2f}")

        # Short position management
        elif self.position['is_short']:
            # Check take profit
            if current_price <= self.position['take_profit']:
                self._close_position("Take profit hit")
                return

            # Check stop loss
            if current_price >= self.position['stop_loss']:
                self._close_position("Stop loss hit")
                return

            # Trailing stop logic: move stop to breakeven when halfway to target
            if not self.position['trailing_stop_triggered']:
                profit_distance = self.position['entry_price'] - current_price
                trailing_threshold = self.position['stop_distance'] * 1.0  # At 1x stop distance (halfway to 2x target)

                if profit_distance >= trailing_threshold:
                    self.position['stop_loss'] = self.position['entry_price']
                    self.position['trailing_stop_triggered'] = True
                    self.debug(f"TRAILING STOP ACTIVATED | Stop moved to breakeven: {self.position['stop_loss']:.2f}")

    def _close_position(self, reason):
        """
        Close the current position.

        Args:
            reason: String describing why position is being closed
        """
        self.liquidate(self._symbol)

        pnl = 0
        if self.position['is_long']:
            pnl = (self.securities[self._symbol].close - self.position['entry_price']) * abs(self.portfolio[self._symbol].quantity)
        elif self.position['is_short']:
            pnl = (self.position['entry_price'] - self.securities[self._symbol].close) * abs(self.portfolio[self._symbol].quantity)

        self.debug(f"POSITION CLOSED | Reason: {reason} | PnL: ${pnl:.2f}")

        # Reset position tracking
        self.position = {
            'is_long': False,
            'is_short': False,
            'entry_price': 0,
            'stop_loss': 0,
            'take_profit': 0,
            'trailing_stop_triggered': False,
            'entry_bar': None,
            'stop_distance': 0
        }

    def _calculate_position_size(self, stop_distance):
        """
        Calculate position size based on risk per trade.

        Args:
            stop_distance: Distance from entry to stop loss

        Returns:
            int: Number of contracts to trade
        """
        if stop_distance <= 0:
            return 0

        # Calculate risk amount in dollars
        risk_amount = self.portfolio.total_portfolio_value * self.risk_per_trade

        # MES contract multiplier is $5 per point
        contract_multiplier = 5

        # Calculate number of contracts
        # Risk per contract = stop_distance * contract_multiplier
        contracts = int(risk_amount / (stop_distance * contract_multiplier))

        # Ensure at least 1 contract if we have enough capital
        if contracts == 0 and self.portfolio.total_portfolio_value > 10000:
            contracts = 1

        return contracts
