# region imports
from AlgorithmImports import *
from datetime import time
from enum import Enum

from indicators.session_poc import SessionPOCIndicator
from indicators.initial_balance import InitialBalanceIndicator
from indicators.open_type_classifier import OpenTypeClassifier
from indicators.prior_day_context import PriorDayContext
from indicators.candle_patterns import CandlePatternDetector
# endregion


class TradingPhase(Enum):
    """Trading session phases for state machine."""
    PRE_MARKET = "pre_market"           # Before 9:30 AM - Collect prior day data
    IB_FORMATION = "ib_formation"       # 9:30-10:30 AM - Observe only
    TRADING = "trading"                 # 10:30 AM - 2:30 PM - Look for setups
    EOD_MANAGEMENT = "eod_management"   # 2:30 PM - 3:45 PM - Manage/close
    CLOSED = "closed"                   # 3:45 PM+ - No trading


class IBPOCMeanReversionStrategy(QCAlgorithm):
    """
    ES Futures IB-POC Mean Reversion Strategy.

    Fades Initial Balance extensions on balanced days, targeting mean reversion
    to the session's developing Point of Control (POC).

    Statistical Foundation:
    - 80-90% of sessions are balanced/rotational (not trend days)
    - IB extensions beyond 1.5x occur only 30-34% of the time
    - Mean reversion dominates at sub-15 minute horizons

    Strategy Rules:
    1. Observe IB formation (9:30-10:30 AM EST)
    2. Classify IB width and open type
    3. Trade extensions 0.5x-1.0x IB range with confirmation
    4. Target developing session POC with 2:1 R:R minimum
    5. Scale out at IB midpoint and POC
    """

    def initialize(self):
        """Initialize algorithm with parameters, data, and indicators."""
        # Date range and capital
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2024, 12, 31)
        self.set_cash(100000)

        # Log live mode status (required by CLAUDE.md)
        self.debug(f"Live Mode: {self.live_mode}")

        # Set timezone to Eastern for session tracking
        self.set_time_zone(TimeZones.NEW_YORK)

        # Add MES futures (Micro E-mini S&P 500)
        self._future = self.add_future(
            Futures.Indices.MICRO_SP_500_E_MINI,
            Resolution.MINUTE,
            data_normalization_mode=DataNormalizationMode.BACKWARDS_RATIO
        )
        self._future.set_filter(0, 90)  # Front month only
        self._symbol = None

        # Initialize strategy parameters
        self._init_parameters()

        # Custom indicators (created in on_securities_changed)
        self._session_poc = None
        self._ib_indicator = None
        self._open_classifier = None
        self._prior_day = None
        self._candle_patterns = None

        # State tracking
        self._current_phase = TradingPhase.PRE_MARKET
        self._position = self._init_position_dict()
        self._daily_stats = self._init_daily_stats()

        # Session logging flags
        self._logged_prior_day = False
        self._logged_ib = False

        # Warm-up period (need enough history for 20-day IB average)
        self.set_warm_up(30, Resolution.DAILY)

    def _init_parameters(self):
        """Initialize all strategy parameters using get_parameter for cloud optimization."""
        # IB classification thresholds
        self._ib_narrow_threshold = self.get_parameter("ib_narrow_threshold", 0.70)
        self._ib_wide_threshold = self.get_parameter("ib_wide_threshold", 1.30)

        # Extension zone parameters
        self._min_extension = self.get_parameter("min_extension", 0.50)  # Minimum 0.5x IB
        self._max_extension = self.get_parameter("max_extension", 1.50)  # Maximum 1.5x IB
        self._optimal_extension_low = self.get_parameter("optimal_extension_low", 0.50)
        self._optimal_extension_high = self.get_parameter("optimal_extension_high", 1.00)

        # Risk management parameters
        self._risk_per_trade = self.get_parameter("risk_per_trade", 0.01)  # 1%
        self._max_daily_risk = self.get_parameter("max_daily_risk", 0.03)  # 3%
        self._stop_ib_multiplier = self.get_parameter("stop_ib_multiplier", 0.50)  # 0.5x IB
        self._min_rr_ratio = self.get_parameter("min_rr_ratio", 2.0)  # Minimum 2:1

        # Position size adjustments by IB classification
        self._narrow_ib_size_mult = self.get_parameter("narrow_ib_size_mult", 0.50)
        self._medium_ib_size_mult = self.get_parameter("medium_ib_size_mult", 1.00)
        self._wide_ib_size_mult = self.get_parameter("wide_ib_size_mult", 1.00)

        # Scoring thresholds
        self._min_score_to_trade = self.get_parameter("min_score_to_trade", 4)

        # Session time parameters
        self._market_open = time(9, 30)
        self._ib_end = time(10, 30)
        self._new_entry_cutoff = time(14, 30)
        self._tighten_stops_time = time(15, 0)
        self._close_all_time = time(15, 45)
        self._market_close = time(16, 0)

        # Contract specifications
        self._contract_multiplier = 5  # MES = $5 per point

    def _init_position_dict(self):
        """Initialize position tracking dictionary."""
        return {
            'is_long': False,
            'is_short': False,
            'entry_price': 0,
            'stop_loss': 0,
            'target_poc': 0,
            'target_midpoint': 0,
            'quantity': 0,
            'remaining_quantity': 0,
            'at_breakeven': False,
            'took_partial': False,
            'entry_time': None,
            'setup_score': 0
        }

    def _init_daily_stats(self):
        """Initialize daily statistics tracking."""
        return {
            'date': None,
            'trades_taken': 0,
            'wins': 0,
            'losses': 0,
            'daily_pnl': 0,
            'max_drawdown': 0
        }

    def on_securities_changed(self, changes):
        """Handle changes in the universe of securities."""
        for security in changes.added_securities:
            if security.symbol.security_type == SecurityType.FUTURE:
                self._symbol = security.symbol

                # Initialize custom indicators
                self._session_poc = SessionPOCIndicator(tick_size=0.25)
                self._ib_indicator = InitialBalanceIndicator(
                    narrow_threshold=self._ib_narrow_threshold,
                    wide_threshold=self._ib_wide_threshold
                )
                self._open_classifier = OpenTypeClassifier()
                self._prior_day = PriorDayContext()
                self._candle_patterns = CandlePatternDetector()

                self.debug(f"Trading contract: {self._symbol}")

    def on_data(self, data: Slice):
        """Main trading logic executed on each data slice."""
        # Guard clauses
        if self.is_warming_up or self._symbol is None:
            return

        if not data.bars.contains_key(self._symbol):
            return

        bar = data.bars[self._symbol]
        current_time = self.time

        # Skip weekends
        if current_time.weekday() >= 5:
            return

        # Determine trading phase
        self._current_phase = self._determine_phase(current_time)

        # Update all indicators
        poc_data = self._session_poc.update(bar, current_time)
        ib_data = self._ib_indicator.update(bar, current_time)
        open_type_data = self._open_classifier.update(bar, current_time)
        prior_day_data = self._prior_day.update(bar, current_time, poc_data)
        candle_data = self._candle_patterns.update(bar)

        # Phase-specific logic
        if self._current_phase == TradingPhase.PRE_MARKET:
            self._handle_pre_market(prior_day_data)

        elif self._current_phase == TradingPhase.IB_FORMATION:
            self._handle_ib_formation(ib_data, open_type_data)

        elif self._current_phase == TradingPhase.TRADING:
            self._handle_trading_phase(bar, ib_data, poc_data, candle_data)

        elif self._current_phase == TradingPhase.EOD_MANAGEMENT:
            self._handle_eod_management(bar, poc_data)

        elif self._current_phase == TradingPhase.CLOSED:
            self._handle_closed()

    def _determine_phase(self, current_time) -> TradingPhase:
        """Determine current trading phase based on time."""
        time_of_day = current_time.time()

        if time_of_day < self._market_open:
            return TradingPhase.PRE_MARKET
        elif time_of_day < self._ib_end:
            return TradingPhase.IB_FORMATION
        elif time_of_day < self._new_entry_cutoff:
            return TradingPhase.TRADING
        elif time_of_day < self._close_all_time:
            return TradingPhase.EOD_MANAGEMENT
        else:
            return TradingPhase.CLOSED

    def _handle_pre_market(self, prior_day_data):
        """Handle pre-market phase - collect context data."""
        # Reset daily stats on new day
        if self._daily_stats['date'] != self.time.date():
            self._daily_stats = self._init_daily_stats()
            self._daily_stats['date'] = self.time.date()
            self._logged_prior_day = False
            self._logged_ib = False

        # Log prior day context (once per session)
        if prior_day_data['is_ready'] and not self._logged_prior_day:
            self.debug(
                f"Prior Day Context: PDH={prior_day_data['pdh']:.2f}, "
                f"PDL={prior_day_data['pdl']:.2f}, "
                f"Range={prior_day_data['prior_range']:.2f}, "
                f"POC={prior_day_data['prior_poc']:.2f if prior_day_data['prior_poc'] else 'N/A'}"
            )
            self._logged_prior_day = True

    def _handle_ib_formation(self, ib_data, open_type_data):
        """Handle IB formation phase - observe only."""
        # Log IB analysis once complete
        if ib_data['ib_complete'] and not self._logged_ib:
            classification = ib_data['ib_classification']
            ib_ratio = ib_data['ib_ratio']

            self.debug(
                f"IB Complete: Range={ib_data['ib_range']:.2f}, "
                f"Classification={classification} ({ib_ratio*100:.1f}% of avg), "
                f"IBH={ib_data['ibh']:.2f}, IBL={ib_data['ibl']:.2f}, "
                f"Midpoint={ib_data['ib_midpoint']:.2f}"
            )

            if open_type_data['is_ready']:
                self.debug(f"Open Type: {open_type_data['classification']}")
                if open_type_data['is_trend_day_likely']:
                    self.debug("WARNING: Open Drive detected - trend day likely, skipping session")

            self._logged_ib = True

    def _handle_trading_phase(self, bar, ib_data, poc_data, candle_data):
        """Handle active trading phase."""
        # Check if already in position
        if self._position['is_long'] or self._position['is_short']:
            self._manage_position(bar, poc_data, eod_mode=False)
        else:
            # Check for new entry signals
            self._check_entry_signals(bar, ib_data, poc_data, candle_data)

    def _handle_eod_management(self, bar, poc_data):
        """Handle end-of-day management - no new entries, manage/close positions."""
        if self._position['is_long'] or self._position['is_short']:
            self._manage_position(bar, poc_data, eod_mode=True)

    def _handle_closed(self):
        """Handle closed phase - exit all positions."""
        if self._position['is_long'] or self._position['is_short']:
            self._close_position("Session close (3:45 PM)")

    def _check_entry_signals(self, bar, ib_data, poc_data, candle_data):
        """Check for valid entry setups."""
        current_price = bar.Close

        # Pre-check: Ensure indicators are ready
        if not self._ib_indicator.is_ready or not self._session_poc.is_ready:
            return

        if not ib_data['ib_complete']:
            return

        # Pre-check: Skip if Open Drive day
        if self._open_classifier.is_trend_day_likely:
            return

        # Pre-check: Check daily risk limit
        max_daily_loss = self._max_daily_risk * self.portfolio.total_portfolio_value
        if self._daily_stats['daily_pnl'] <= -max_daily_loss:
            return

        # Check for IB extension
        ibh = ib_data['ibh']
        ibl = ib_data['ibl']
        ib_range = ib_data['ib_range']

        if ibh is None or ibl is None or ib_range is None or ib_range == 0:
            return

        direction = None
        extension_amount = 0

        # Check for short setup (price above IBH)
        if current_price > ibh:
            direction = 'short'
            extension_amount = self._ib_indicator.get_extension_amount(current_price, 'short')

        # Check for long setup (price below IBL)
        elif current_price < ibl:
            direction = 'long'
            extension_amount = self._ib_indicator.get_extension_amount(current_price, 'long')

        if direction is None or extension_amount is None or extension_amount == 0:
            return

        # Check extension is in valid range (0.5x to 1.5x)
        if extension_amount < self._min_extension or extension_amount > self._max_extension:
            return

        # Check for confirmation candle
        has_confirmation = False
        if direction == 'long':
            has_confirmation = candle_data.get('any_bullish', False)
        else:
            has_confirmation = candle_data.get('any_bearish', False)

        if not has_confirmation:
            return

        # Check R:R ratio
        poc = poc_data.get('poc')
        if poc is None:
            return

        stop_distance = ib_range * self._stop_ib_multiplier

        if direction == 'long':
            entry = current_price
            stop = entry - stop_distance
            target = poc
            profit_distance = target - entry
        else:
            entry = current_price
            stop = entry + stop_distance
            target = poc
            profit_distance = entry - target

        # POC must be in the right direction for profit
        if profit_distance <= 0:
            return

        rr_ratio = profit_distance / stop_distance
        if rr_ratio < self._min_rr_ratio:
            return

        # Calculate IB volume average for volume filter
        ib_volume = ib_data.get('ib_volume', 0)
        ib_avg_volume_per_min = ib_volume / 60 if ib_volume > 0 else 0
        volume_declining = bar.Volume < ib_avg_volume_per_min if ib_avg_volume_per_min > 0 else True

        # Calculate setup score
        score = self._calculate_setup_score(
            ib_data, extension_amount, has_confirmation,
            volume_declining, rr_ratio
        )

        if score < self._min_score_to_trade:
            self.debug(f"Setup score {score} below minimum {self._min_score_to_trade}, skipping")
            return

        # Execute entry
        self._execute_entry(direction, entry, stop, target, ib_data, score)

    def _calculate_setup_score(self, ib_data, extension, has_confirmation,
                               volume_declining, rr_ratio):
        """
        Calculate setup quality score (0-10).

        Scoring:
        - Medium/Wide IB (>= 70% of avg): +2
        - Non-Open Drive day: +2 (already filtered)
        - Extension in optimal zone (0.5-1.0x): +2
        - Rejection candle confirmation: +1
        - Volume declining on extension: +1
        - R:R >= 2.5:1: +1
        - Time is 10:30 AM - 12:30 PM: +1
        """
        score = 0

        # IB Classification (+2)
        classification = ib_data.get('ib_classification')
        if classification in ['medium', 'wide']:
            score += 2

        # Non-Open Drive (+2) - already filtered, always awarded
        score += 2

        # Extension in optimal zone (+2)
        if self._optimal_extension_low <= extension <= self._optimal_extension_high:
            score += 2

        # Confirmation signal (+1)
        if has_confirmation:
            score += 1

        # Volume declining (+1)
        if volume_declining:
            score += 1

        # R:R >= 2.5:1 (+1)
        if rr_ratio >= 2.5:
            score += 1

        # Time 10:30 AM - 12:30 PM (+1)
        time_of_day = self.time.time()
        optimal_start = time(10, 30)
        optimal_end = time(12, 30)
        if optimal_start <= time_of_day <= optimal_end:
            score += 1

        return score

    def _execute_entry(self, direction, entry_price, stop_loss, target_poc, ib_data, score):
        """Execute trade entry."""
        # Calculate position size
        stop_distance = abs(entry_price - stop_loss)
        classification = ib_data.get('ib_classification', 'medium')
        quantity = self._calculate_position_size(stop_distance, classification)

        if quantity == 0:
            self.debug("Calculated quantity is 0, skipping trade")
            return

        # Place market order
        if direction == 'long':
            self.market_order(self._symbol, quantity)
            self._position['is_long'] = True
        else:
            self.market_order(self._symbol, -quantity)
            self._position['is_short'] = True

        # Get IB midpoint for scaling target
        ib_midpoint = ib_data.get('ib_midpoint', (ib_data['ibh'] + ib_data['ibl']) / 2)

        # Update position tracking
        self._position['entry_price'] = entry_price
        self._position['stop_loss'] = stop_loss
        self._position['target_poc'] = target_poc
        self._position['target_midpoint'] = ib_midpoint
        self._position['quantity'] = quantity
        self._position['remaining_quantity'] = quantity
        self._position['entry_time'] = self.time
        self._position['setup_score'] = score
        self._position['at_breakeven'] = False
        self._position['took_partial'] = False

        self.debug(
            f"ENTRY: {direction.upper()} | Price={entry_price:.2f} | Qty={quantity} | "
            f"Stop={stop_loss:.2f} | POC Target={target_poc:.2f} | "
            f"Midpoint={ib_midpoint:.2f} | Score={score}"
        )

        self._daily_stats['trades_taken'] += 1

    def _manage_position(self, bar, poc_data, eod_mode=False):
        """Manage open position: stops, targets, scaling."""
        current_price = bar.Close

        # Update POC target if available (POC is dynamic)
        if poc_data and poc_data.get('poc'):
            self._position['target_poc'] = poc_data['poc']

        # Long position management
        if self._position['is_long']:
            self._manage_long_position(current_price, eod_mode)

        # Short position management
        elif self._position['is_short']:
            self._manage_short_position(current_price, eod_mode)

    def _manage_long_position(self, current_price, eod_mode):
        """Manage a long position."""
        # Check stop loss
        if current_price <= self._position['stop_loss']:
            self._close_position("Stop loss hit")
            return

        entry_price = self._position['entry_price']
        stop_loss = self._position['stop_loss']
        profit = current_price - entry_price
        stop_distance = entry_price - stop_loss

        # Move to breakeven at 1R profit
        if not self._position['at_breakeven'] and profit >= stop_distance:
            self._position['stop_loss'] = entry_price
            self._position['at_breakeven'] = True
            self.debug(f"Moved stop to breakeven: {entry_price:.2f}")

        # Take 50% at IB midpoint
        midpoint = self._position['target_midpoint']
        if not self._position['took_partial'] and current_price >= midpoint:
            partial_qty = self._position['remaining_quantity'] // 2
            if partial_qty > 0:
                self.market_order(self._symbol, -partial_qty)
                self._position['remaining_quantity'] -= partial_qty
                self._position['took_partial'] = True
                self.debug(f"Partial exit at midpoint ({midpoint:.2f}): {partial_qty} contracts")

        # Full exit at POC
        if current_price >= self._position['target_poc']:
            self._close_position("POC target hit")
            return

        # EOD management
        if eod_mode:
            self._apply_eod_management(current_price, 'long')

    def _manage_short_position(self, current_price, eod_mode):
        """Manage a short position."""
        # Check stop loss
        if current_price >= self._position['stop_loss']:
            self._close_position("Stop loss hit")
            return

        entry_price = self._position['entry_price']
        stop_loss = self._position['stop_loss']
        profit = entry_price - current_price
        stop_distance = stop_loss - entry_price

        # Move to breakeven at 1R profit
        if not self._position['at_breakeven'] and profit >= stop_distance:
            self._position['stop_loss'] = entry_price
            self._position['at_breakeven'] = True
            self.debug(f"Moved stop to breakeven: {entry_price:.2f}")

        # Take 50% at IB midpoint
        midpoint = self._position['target_midpoint']
        if not self._position['took_partial'] and current_price <= midpoint:
            partial_qty = self._position['remaining_quantity'] // 2
            if partial_qty > 0:
                self.market_order(self._symbol, partial_qty)
                self._position['remaining_quantity'] -= partial_qty
                self._position['took_partial'] = True
                self.debug(f"Partial exit at midpoint ({midpoint:.2f}): {partial_qty} contracts")

        # Full exit at POC
        if current_price <= self._position['target_poc']:
            self._close_position("POC target hit")
            return

        # EOD management
        if eod_mode:
            self._apply_eod_management(current_price, 'short')

    def _apply_eod_management(self, current_price, direction):
        """Apply EOD stop tightening."""
        time_of_day = self.time.time()

        # Tighten stops after 3:00 PM
        if time_of_day >= self._tighten_stops_time:
            if direction == 'long':
                current_stop_dist = current_price - self._position['stop_loss']
                new_stop = current_price - (current_stop_dist * 0.5)
                if new_stop > self._position['stop_loss']:
                    self._position['stop_loss'] = new_stop
                    self.debug(f"EOD tightened stop: {new_stop:.2f}")
            else:  # short
                current_stop_dist = self._position['stop_loss'] - current_price
                new_stop = current_price + (current_stop_dist * 0.5)
                if new_stop < self._position['stop_loss']:
                    self._position['stop_loss'] = new_stop
                    self.debug(f"EOD tightened stop: {new_stop:.2f}")

    def _close_position(self, reason):
        """Close the entire position."""
        if self._symbol is None:
            return

        # Get current price for PnL calculation
        current_price = self.securities[self._symbol].close

        # Calculate PnL
        if self._position['is_long']:
            pnl = (current_price - self._position['entry_price']) * \
                  self._position['quantity'] * self._contract_multiplier
        else:
            pnl = (self._position['entry_price'] - current_price) * \
                  self._position['quantity'] * self._contract_multiplier

        # Liquidate
        self.liquidate(self._symbol)

        # Update daily stats
        self._daily_stats['daily_pnl'] += pnl
        if pnl > 0:
            self._daily_stats['wins'] += 1
        else:
            self._daily_stats['losses'] += 1

        self.debug(
            f"CLOSED: {reason} | Entry={self._position['entry_price']:.2f} | "
            f"Exit={current_price:.2f} | PnL=${pnl:.2f} | "
            f"Daily P&L=${self._daily_stats['daily_pnl']:.2f}"
        )

        # Reset position
        self._position = self._init_position_dict()

    def _calculate_position_size(self, stop_distance, ib_classification):
        """
        Calculate position size based on risk and IB classification.

        Args:
            stop_distance: Distance to stop loss in points
            ib_classification: 'narrow', 'medium', or 'wide'

        Returns:
            Number of contracts to trade
        """
        if stop_distance <= 0:
            return 0

        # Get size multiplier based on IB classification
        if ib_classification == 'narrow':
            size_mult = self._narrow_ib_size_mult
        elif ib_classification == 'wide':
            size_mult = self._wide_ib_size_mult
        else:
            size_mult = self._medium_ib_size_mult

        # Calculate risk amount
        risk_amount = self.portfolio.total_portfolio_value * self._risk_per_trade * size_mult

        # Calculate contracts
        risk_per_contract = stop_distance * self._contract_multiplier
        contracts = int(risk_amount / risk_per_contract)

        # Minimum 1 contract if sufficient capital
        if contracts == 0 and self.portfolio.total_portfolio_value > 10000:
            contracts = 1

        return contracts

    def on_end_of_day(self, symbol):
        """
        Handle end of day events.

        Log daily summary if we traded.
        """
        if symbol != self._symbol:
            return

        if self._daily_stats['trades_taken'] > 0:
            wins = self._daily_stats['wins']
            losses = self._daily_stats['losses']
            total = wins + losses
            win_rate = (wins / total * 100) if total > 0 else 0

            self.debug(
                f"Daily Summary: Trades={self._daily_stats['trades_taken']}, "
                f"W/L={wins}/{losses} ({win_rate:.1f}%), "
                f"P&L=${self._daily_stats['daily_pnl']:.2f}"
            )
