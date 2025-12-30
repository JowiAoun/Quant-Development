# ES Futures IB-POC Mean Reversion Strategy

## Strategy Overview

**Core Thesis**: Fade Initial Balance extensions on balanced days, targeting mean reversion to the session's developing Point of Control (POC).

**Statistical Foundation**:
- 96-97% of sessions break at least one IB side
- Only 10-20% are true trend days → 80% are rotational/balanced
- Mean reversion dominates at sub-15 minute horizons (α = -0.912%, t-stat = -13.6)
- Extension beyond 1.5x IB occurs only 30-34% of the time
- Extension beyond 2x IB occurs only 13-18% of the time

**Edge Source**: The asymmetry between high IB break frequency and low trend day occurrence creates systematic fade opportunities.

---

## Pre-Market Checklist (Before 9:30 AM EST)

### 1. Identify Prior Day Context
| Metric | Calculation | Purpose |
|--------|-------------|---------|
| Prior Day Range | PDH - PDL | Baseline for expected volatility |
| Prior Day POC | Highest volume price level | Key reference for value |
| Prior Day VA | VAH and VAL levels | Determines open type |
| 20-Day Avg IB | Rolling average of IB ranges | Benchmark for narrow/wide classification |

### 2. Overnight Session Analysis
| Condition | Implication | Action |
|-----------|-------------|--------|
| ON Range < 50% of Prior Day Range | Low overnight conviction | Favorable for balanced day |
| ON Range > 100% of Prior Day Range | High overnight activity | Potential trend day - caution |
| Price within Prior VA at 9:30 | Balanced open expected | Proceed with strategy |
| Price outside Prior VA at 9:30 | Directional bias present | Wait for re-entry or skip |

---

## Phase 1: Initial Balance Formation (9:30-10:30 AM EST)

**Action**: OBSERVE ONLY - Do not trade during this period.

### Data Collection During IB Formation

```
At 10:30 AM EST, record:
├── IBH (Initial Balance High)
├── IBL (Initial Balance Low)  
├── IB Range = IBH - IBL
├── IB Midpoint = (IBH + IBL) / 2
├── Developing POC (highest volume price in IB)
├── IB Volume (total contracts traded 9:30-10:30)
└── Open Type Classification
```

### IB Width Classification

| IB Range vs 20-Day Avg | Classification | Day Type Probability | Strategy Adjustment |
|------------------------|----------------|---------------------|---------------------|
| < 70% of average | Narrow | 40% trend day risk | REDUCE position size or SKIP |
| 70-130% of average | Medium | 15% trend day risk | PROCEED with full size |
| > 130% of average | Wide | 5% trend day risk | PROCEED - IB likely contains day |

**Critical Filter**: If IB is narrow (< 70% of 20-day average), the probability of a trend day increases significantly. Either skip the session or reduce position size by 50%.

### Open Type Classification

| Open Type | Description | Implication |
|-----------|-------------|-------------|
| Open Drive | Price moves directionally from open with no pullback | HIGH trend probability - SKIP session |
| Open Test Drive | Brief test of one direction, then sustained move opposite | Moderate trend risk - Proceed with caution |
| Open Rejection Reverse | Tests one direction, rejected, reverses | Balanced day likely - PROCEED |
| Open Auction | Rotational price discovery around open | Balanced day likely - PROCEED |

---

## Phase 2: Trade Setup Identification (10:30 AM - 3:00 PM EST)

### Entry Conditions Checklist

All conditions must be TRUE for valid setup:

```
□ 1. IB Width Filter: IB Range is MEDIUM or WIDE (≥ 70% of 20-day avg)
□ 2. Open Type Filter: NOT an Open Drive day
□ 3. Extension Trigger: Price breaks IBH or IBL
□ 4. Extension Limit: Extension < 1.5x IB Range from IB extreme
□ 5. POC Distance: Developing POC is ≥ 2x the distance from entry to stop
□ 6. Time Filter: Current time is between 10:30 AM and 2:30 PM EST
□ 7. Volume Confirmation: Extension occurs on declining volume (vs IB avg)
```

### Setup Identification Logic

**LONG Setup (Fade IBL Break)**:
```
Trigger: Price breaks below IBL
Entry Zone: IBL - (0.25 × IB Range) to IBL - (1.0 × IB Range)
Optimal Entry: Price shows rejection candle (hammer, bullish engulfing) on 5-min
Stop Loss: Below entry by 0.5 × IB Range (or below swing low)
Target: Developing session POC
```

**SHORT Setup (Fade IBH Break)**:
```
Trigger: Price breaks above IBH
Entry Zone: IBH + (0.25 × IB Range) to IBH + (1.0 × IB Range)
Optimal Entry: Price shows rejection candle (shooting star, bearish engulfing) on 5-min
Stop Loss: Above entry by 0.5 × IB Range (or above swing high)
Target: Developing session POC
```

### Extension Zone Probability Table

| Extension Level | Probability of Further Extension | Fade Quality |
|-----------------|----------------------------------|--------------|
| 0.25x IB | 75-80% continue | POOR - too early |
| 0.5x IB | 55-65% continue | MODERATE - acceptable |
| 0.75x IB | 40-50% continue | GOOD - favorable odds |
| 1.0x IB | 30-35% continue | EXCELLENT - high probability fade |
| 1.25x IB | 20-25% continue | EXCELLENT - but assess trend risk |
| 1.5x IB+ | 13-18% continue | CAUTION - may be trend day |

**Optimal Entry Zone**: 0.5x to 1.0x IB extension provides the best risk/reward balance.

---

## Phase 3: Trade Execution

### Entry Confirmation Signals (5-Minute Chart)

Require at least ONE of the following before entry:

| Signal | Description | Strength |
|--------|-------------|----------|
| Rejection Candle | Hammer/Shooting Star with wick ≥ 2x body | Strong |
| Engulfing Pattern | Bullish/Bearish engulfing at extension | Strong |
| Volume Climax | Spike in volume followed by reversal candle | Strong |
| Delta Divergence | Price makes new high/low but delta doesn't confirm | Moderate |
| POC Magnet | Price stalls and developing POC "pulls" price back | Moderate |

### Position Sizing

```
Risk Per Trade: 1-2% of account equity
Position Size = (Account Risk $) / (Stop Distance in points × $12.50)

Example:
- Account: $50,000
- Risk: 1% = $500
- Stop Distance: 8 points
- Position Size = $500 / (8 × $12.50) = $500 / $100 = 5 contracts (MES) or 1 contract (ES)
```

### Order Execution

```
1. Entry: Limit order at confirmation candle close
2. Stop Loss: Stop-market order (hard stop, no mental stops)
3. Target: Limit order at developing POC level
4. Time Stop: If trade not at 50% of target by 90 minutes, reassess
```

---

## Phase 4: Trade Management

### Scaling Rules

| Price Action | Action | Reasoning |
|--------------|--------|-----------|
| Price reaches 1R (risk amount) profit | Move stop to breakeven | Lock in risk-free trade |
| Price reaches IB midpoint | Take 50% off, trail stop | Capture partial profit |
| Price reaches POC | Exit remaining position | Primary target achieved |
| POC moves toward entry | Adjust target to new POC | POC is dynamic |

### Time-Based Management

| Time (EST) | Consideration |
|------------|---------------|
| 11:30 AM - 1:00 PM | "Dead zone" - expect slower price action, be patient |
| 1:00 PM - 2:00 PM | Energy returns, watch for trend resumption or reversal |
| 2:30 PM | Hard cutoff for new entries (avoid MOC volatility) |
| 3:00 PM | Begin tightening stops on open positions |
| 3:45 PM | Exit all positions (avoid close auction chaos) |

### Invalidation Signals (Exit Immediately)

```
□ Price extends beyond 1.5x IB Range → Trend day likely, exit at stop
□ Strong volume surge in direction of extension → Institutional flow, exit
□ Break of prior day's high/low with conviction → Larger timeframe trend
□ VIX spike > 10% intraday → Regime change, exit all positions
□ Major news event (unscheduled) → Exit, reassess
```

---

## Risk/Reward Framework

### Minimum R:R Requirement

```
Minimum acceptable R:R = 2:1

Calculation:
- Entry: IBL - 0.75 × IB Range (example: long setup)
- Stop: Entry - 0.5 × IB Range
- Target: Developing POC

If POC is not at least 2x stop distance from entry, SKIP the trade.
```

### Expected Value Calculation

```
Conservative Estimates (based on research):
- Win Rate on qualified setups: 58-62%
- Average Winner: 2R (when POC target hit)
- Average Loser: 1R (full stop)

Expected Value = (0.60 × 2R) - (0.40 × 1R)
Expected Value = 1.2R - 0.4R = 0.80R per trade

With 1% risk per trade:
Expected return per trade = 0.80% of account
```

### Maximum Daily Risk

```
Max Daily Loss: 3% of account (3 full losses)
Max Consecutive Losses Before Stop: 3 trades
Daily Profit Target: 4% (scale back after achieving)
```

---

## Conditional Probability Matrix

### Setup Quality Scoring

Score each trade 0-10 based on conditions met:

| Condition | Points | Your Score |
|-----------|--------|------------|
| Medium/Wide IB (≥ 70% of avg) | +2 | ___ |
| Non-Open Drive day | +2 | ___ |
| Extension in optimal zone (0.5-1.0x) | +2 | ___ |
| Rejection candle confirmation | +1 | ___ |
| Volume declining on extension | +1 | ___ |
| R:R ≥ 2.5:1 | +1 | ___ |
| Time is 10:30 AM - 12:30 PM | +1 | ___ |
| **TOTAL** | **/10** | ___ |

### Trade Authorization by Score

| Score | Action |
|-------|--------|
| 8-10 | Full position size - A+ setup |
| 6-7 | 75% position size - Good setup |
| 4-5 | 50% position size - Marginal setup |
| 0-3 | NO TRADE - Insufficient edge |

---

## Day Type Filters: When NOT to Trade

### Trend Day Warning Signs (SKIP SESSION)

```
□ Narrow IB (< 70% of 20-day average)
□ Open Drive pattern in first 30 minutes
□ Price opens outside prior VA and does NOT re-enter by 10:30 AM
□ IB breaks both sides early with conviction
□ Gap > 1% that doesn't fill by 10:00 AM
□ Major economic release day (FOMC, NFP, CPI)
□ Triple/Quadruple witching days
□ First/Last trading day of month
```

### Ideal Session Characteristics (TRADE)

```
□ Medium IB width (70-130% of average)
□ Open Auction or Open Rejection Reverse pattern
□ Price opens within or near prior day's Value Area
□ Overnight range contained (< 75% of prior day range)
□ No major scheduled news during RTH
□ VIX in normal range (no regime change signals)
```

---

## Performance Tracking Template

### Daily Log

| Field | Value |
|-------|-------|
| Date | ___ |
| IB Range | ___ pts |
| IB vs 20-Day Avg | ___% |
| IB Classification | Narrow / Medium / Wide |
| Open Type | OD / OTD / ORR / OA |
| Day Type (post-hoc) | Trend / Balanced |
| Setups Identified | ___ |
| Trades Taken | ___ |
| Win/Loss | ___ |
| Total R Gained/Lost | ___ |
| Notes | ___ |

### Weekly Statistics

```
Total Trades: ___
Win Rate: ___%
Average Winner: ___R
Average Loser: ___R
Profit Factor: ___
Expectancy: ___R per trade
Max Drawdown: ___%
```

---

## Strategy Refinement Notes

### Parameters to Optimize via Backtesting

1. **IB Width Threshold**: Test 60%, 70%, 80% cutoffs
2. **Optimal Extension Entry**: Test 0.5x, 0.75x, 1.0x zones
3. **Stop Distance**: Test 0.4x, 0.5x, 0.6x IB Range
4. **Time Filters**: Test different cutoff times
5. **Volume Confirmation**: Test volume decline thresholds

### Market Regime Considerations

| VIX Level | IB Adjustment | Position Size |
|-----------|---------------|---------------|
| < 15 | Use standard IB avg | 100% |
| 15-25 | Expect wider IB | 75% |
| 25-35 | Much wider IB expected | 50% |
| > 35 | Crisis regime | 25% or skip |

---

## Quick Reference Card

```
╔══════════════════════════════════════════════════════════════════╗
║                    ES IB-POC FADE STRATEGY                       ║
╠══════════════════════════════════════════════════════════════════╣
║ BEFORE 9:30: Note prior day VA, POC, 20-day avg IB              ║
║ 9:30-10:30:  OBSERVE - Record IB, classify width & open type    ║
║ 10:30+:      EXECUTE - Fade IB extensions → target POC          ║
╠══════════════════════════════════════════════════════════════════╣
║ ENTRY RULES:                                                     ║
║ • IB must be MEDIUM or WIDE (≥ 70% of 20-day avg)               ║
║ • Wait for 0.5x - 1.0x IB extension                             ║
║ • Require rejection candle on 5-min                             ║
║ • R:R must be ≥ 2:1 to POC                                      ║
╠══════════════════════════════════════════════════════════════════╣
║ STOP: 0.5x IB Range below/above entry                           ║
║ TARGET: Developing Session POC                                   ║
║ RISK: 1-2% per trade, 3% daily max                              ║
╠══════════════════════════════════════════════════════════════════╣
║ SKIP IF: Narrow IB, Open Drive, news day, VIX spike             ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Appendix: Key Statistics Reference

| Statistic | Value | Source |
|-----------|-------|--------|
| IB Break Probability (one side) | 96-97% | Rancho Dinero |
| Trend Day Frequency | 10-20% | NinjaTrader Study |
| Balanced Day Frequency | 80-90% | NinjaTrader Study |
| 1.5x Extension Probability | 30-34% | Rancho Dinero |
| 2.0x Extension Probability | 13-18% | Rancho Dinero |
| Mean Reversion Coefficient (< 15 min) | -0.912% | Safari & Schmidhuber (2025) |
| 80% Rule Actual Accuracy | 62% | TradeStation Backtest |
| Gap Fill Probability | 76% | 528-day study |

---

*Strategy Version 1.0 - Requires backtesting validation before live implementation*