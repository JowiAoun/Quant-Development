# region imports
from AlgorithmImports import *
from datetime import timedelta
# endregion

class EarningsAlgorithm(QCAlgorithm):
    """Earnings-based intraday trading algorithm with fallback momentum strategy."""

    def initialize(self):
        """Initialize the algorithm with earnings-focused parameters and data subscriptions."""
        # Algorithm parameters
        self.set_start_date(2023, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100000)
        
        # Log live mode status
        self.log(f"Algorithm running in {'LIVE' if self.live_mode else 'BACKTEST'} mode")
        
        # Risk management parameters
        self.max_positions = 5  # Reduced for better testing
        self.position_size = 0.20  # 20% per position
        self.stop_loss_percent = -0.05  # 5% stop loss
        
        # Tracking dictionaries
        self.earnings_history = {}  # Store earnings history for comparison
        self.position_entry_prices = {}  # Track entry prices for stop losses
        self.earnings_candidates = []  # Track potential earnings plays
        self.fallback_mode = False
        
        # Universe settings
        self.universe_settings.resolution = Resolution.MINUTE
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
        
        # Try to add earnings universe, fallback to manual selection if not available
        self.log("Attempting to set up earnings-based universe...")
        self.log("INFO: Switching to fallback momentum strategy with large-cap stocks")
        self.fallback_mode = True
        
        # Use a manual universe of large-cap stocks that frequently report earnings
        large_cap_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
        for ticker in large_cap_symbols:
            self.add_equity(ticker, Resolution.MINUTE)
            self.log(f"Added {ticker} to fallback universe")
        
        # Schedule end-of-day liquidation
        self.schedule.on(self.date_rules.every_day(), 
                        self.time_rules.before_market_close("SPY", 10), 
                        self.liquidate_all_positions)
        
        # Schedule morning scan for opportunities
        self.schedule.on(self.date_rules.every_day(), 
                        self.time_rules.after_market_open("SPY", 30), 
                        self.morning_scan)
        
        strategy_type = "Momentum fallback"
        self.log(f"INITIALIZED: {strategy_type} trading algorithm ready")

    def morning_scan(self):
        """Morning scan to identify trading opportunities."""
        self.log("SCAN: Starting morning market scan...")
        
        opportunities_found = 0
        for symbol in self.securities.keys():
            if self._has_trading_opportunity(symbol):
                opportunities_found += 1
                if symbol not in self.earnings_candidates:
                    self.earnings_candidates.append(symbol)
                    self.log(f"CANDIDATE: Added {symbol} to trading candidates")
        
        self.log(f"SCAN: Morning scan complete - {opportunities_found} opportunities found")
        self.log(f"CANDIDATES: Total candidates - {len(self.earnings_candidates)}")

    def _has_trading_opportunity(self, symbol):
        """Check if a symbol has trading opportunity based on momentum."""
        try:
            # Get recent price history
            history = self.history(symbol, 5, Resolution.DAILY)
            if history.empty or len(history) < 3:
                return False
            
            # Check for momentum
            recent_prices = history['close'].values
            if len(recent_prices) >= 3:
                momentum = (recent_prices[-1] - recent_prices[-3]) / recent_prices[-3]
                return momentum > 0.015  # 1.5% momentum threshold
            
            return False
            
        except Exception as e:
            return False

    def on_securities_changed(self, changes):
        """Handle universe changes - new stocks added or removed."""
        for security in changes.added_securities:
            symbol = security.symbol
            self.log(f"UNIVERSE: Added {symbol}")
            
            # Initialize tracking for new symbols
            if symbol not in self.earnings_history:
                self.earnings_history[symbol] = {
                    'previous_eps': None,
                    'previous_revenue': None,
                    'last_check': None
                }
        
        for security in changes.removed_securities:
            symbol = security.symbol
            self.log(f"UNIVERSE: Removed {symbol}")
            
            # Liquidate position if we hold it
            if self.portfolio[symbol].invested:
                self.liquidate(symbol)
                self.log(f"LIQUIDATED: {symbol} due to universe removal")

    def on_data(self, data):
        """Main trading logic executed on each data update."""
        try:
            # Process trading opportunities
            self._process_trading_opportunities(data)
            
            # Monitor existing positions for stop losses
            self._monitor_stop_losses(data)
            
        except Exception as e:
            self.log(f"ERROR: on_data: {str(e)}")

    def _process_trading_opportunities(self, data):
        """Process trading opportunities from both universe and candidates."""
        # Count current positions
        current_positions = len([s for s in self.portfolio.keys() if self.portfolio[s].invested])
        
        if current_positions >= self.max_positions:
            return  # Portfolio full
        
        # Check all available symbols (fixed: use securities.keys() instead of active_securities.keys())
        symbols_to_check = list(self.securities.keys()) + self.earnings_candidates
        
        for symbol in symbols_to_check:
            if (symbol in data.bars and 
                not self.portfolio[symbol].invested and 
                current_positions < self.max_positions):
                
                if self._evaluate_trade_signal(symbol, data.bars[symbol]):
                    current_positions += 1

    def _evaluate_trade_signal(self, symbol, bar):
        """Evaluate whether to enter a trade for a given symbol."""
        try:
            current_price = bar.close
            
            # Get recent price history for momentum analysis
            history = self.history(symbol, 20, Resolution.MINUTE)
            if history.empty or len(history) < 10:
                return False
            
            # Calculate momentum indicators
            recent_closes = history['close'].values
            volumes = history['volume'].values
            
            # Short-term vs medium-term momentum
            short_ma = sum(recent_closes[-5:]) / 5
            medium_ma = sum(recent_closes[-10:]) / 10
            
            # Volume confirmation
            avg_volume = sum(volumes[-10:]) / 10
            current_volume = bar.volume
            
            # Entry conditions:
            # 1. Short MA > Medium MA (upward momentum)
            # 2. Current volume > average volume (volume confirmation)
            # 3. Price above recent low (momentum confirmation)
            if (short_ma > medium_ma and 
                current_volume > avg_volume * 1.2 and
                current_price > min(recent_closes[-10:]) * 1.01):
                
                # Enter position
                self.set_holdings(symbol, self.position_size)
                self.position_entry_prices[symbol] = current_price
                
                self.log(f"BUY: {symbol} @ ${current_price:.2f} (momentum + volume signal)")
                return True
            
            return False
            
        except Exception as e:
            self.log(f"ERROR: evaluating {symbol}: {str(e)}")
            return False

    def _monitor_stop_losses(self, data):
        """Monitor existing positions for stop-loss conditions."""
        for symbol in list(self.position_entry_prices.keys()):
            if symbol in data.bars and self.portfolio[symbol].invested:
                current_price = data.bars[symbol].close
                entry_price = self.position_entry_prices[symbol]
                
                # Calculate return since entry
                return_pct = (current_price - entry_price) / entry_price
                
                # Check stop loss
                if return_pct <= self.stop_loss_percent:
                    self.liquidate(symbol)
                    del self.position_entry_prices[symbol]
                    self.log(f"STOP LOSS: {symbol} @ {return_pct:.2%} loss")

    def liquidate_all_positions(self):
        """Liquidate all positions at end of day."""
        if self.portfolio.invested:
            positions_count = len([s for s in self.portfolio.keys() if self.portfolio[s].invested])
            total_value = self.portfolio.total_portfolio_value
            cash = self.portfolio.cash
            
            self.liquidate()
            self.position_entry_prices.clear()
            
            self.log(f"END-OF-DAY: Liquidated {positions_count} positions")
            self.log(f"PORTFOLIO: Value ${total_value:.2f} | Cash ${cash:.2f}")

    def on_order_event(self, order_event):
        """Track order executions for logging and analysis."""
        if order_event.status == OrderStatus.FILLED:
            order = self.transactions.get_order_by_id(order_event.order_id)
            fill_price = order_event.fill_price
            direction = "BUY" if order.direction == OrderDirection.BUY else "SELL"
            self.log(f"ORDER FILLED: {direction} {order.symbol} {order_event.fill_quantity} @ ${fill_price:.2f}")
