# Tournament — Pump.fun Replay Sprint paper bot

How the entry was chosen: every candidate ran through the same local replay
of the dev window (a faithful Python port of the kit's `tools/sim.ts`;
validated by reproducing the house momentum pilot's TypeScript backtest
**exactly**: net −9.3837 SOL, 410 fills, 48 coins, 80 trips, 5 wins,
drawdown 0.9502). The harness speaks `agent-fun/replay/v2`: one `hello`
message, then one `batch` per slot, then `done`; the bot answers each batch
with its `orders`. Scoring is net PnL after all fees; the guardrails are
≥ 20 distinct mints with round trips ≥ 0.01 SOL and max drawdown ≤ 50%.

## Results on the dev window (10 SOL capital)

| # | Candidate | Net PnL (SOL) | Fills | Coins | Trips | Wins | Max DD |
|---|-----------|--------------:|------:|------:|------:|-----:|-------:|
| A | Equal-weight (house baseline logic) | −0.0168 | 5 | 5 | 5 | 0 | 0.009 |
| B | Momentum (house pilot, default params) | −9.3837 | 410 | 48 | 80 | 5 | 0.950 |
| C | Mean reversion (buy the dip) | −0.5412 | 379 | 59 | 125 | 25 | 0.068 |
| D | Sniper (young launches, rug filter) | −0.3243 | 304 | 79 | 152 | 15 | 0.033 |
| E | Quick-flip (momentum, fast exits) | −0.1264 | 342 | 99 | 171 | 26 | 0.033 |
| E* | **Quick-flip, tuned (WINNER)** | **−0.0201** | 326 | 90 | 163 | 23 | 0.019 |
| F | Probes-only (guardrail floor) | −0.0113 | 48 | 24 | 24 | 4 | 0.001 |
| G | Spike-rider (trailing stop, no fixed TP) | −0.2245 | 240 | 41 | 120 | 8 | 0.026 |
| H | Ride-to-completion (rq 30–80 SOL) | −0.5366 | 270 | 56 | 135 | 10 | 0.098 |

## Why each loser lost

- **A equal-weight** barely trades: it buys 5 coins and holds them, so it
  **fails the 20-coin guardrail** (5 coins). Near-breakeven only because it
  hardly risks anything.
- **B momentum** is a disaster: 2 SOL stakes, pyramiding, 1500-slot holds.
  It rides every pump down to the bottom (drawdown 95%, 4668
  `insufficient_cash` rejections). The house pilot's defaults do not survive
  this window.
- **C reversion**: dips keep dipping. 20% win rate cannot cover the losers.
- **D sniper**: 10% win rate at TP +25% / stop −12% — the payoff shape
  needs ~32% wins to break even. Raising TP to +50%/+100% made it worse.
- **G spike-rider**: the 1%-of-reserve size cap binds so hard on young
  coins that the 0.20 SOL stake never happens; most of its 120 trips turned
  out to be 0.01 SOL probes, and its main entries never fired.
- **H ride-to-completion**: curves with 30–80 SOL of real reserves are
  usually topping, not about to graduate profitably.

## Why the winner won

Quick-flip takes the pump and leaves: small 0.10 SOL stakes, −8% stop,
15% trailing stop armed at +5%, 150-slot max hold. The refinement grid
(trail × net inflow × hold × stop, then window × age) found a flat region
around the shipped settings — trail 0.15, net inflow ≥ 2 SOL, hold 150,
stop 8% — not a sharp overfit peak. Pyramid adds were tried and rejected
(−0.0215 / −0.0348 vs −0.0201).

## Robustness (not tuned on)

- **Fresh coins** (coins created in the last tercile of the window, never
  used for tuning): **+0.0204 SOL**, 114 trips, 13 wins, 40 coins, dd 0.012.
  The only candidate that is positive on unseen coins.
- **2× fees**: −0.2132 SOL (fee-sensitive, like every candidate; the grader
  uses 1× fees).
- **No failed transactions**: −0.0155 SOL (the 2% failed-tx draw is noise).

## Winner settings (shipped in main.py)

window 15 slots, min net inflow 2.0 SOL, min buys 3, min buyers 5,
min price rise 3%, max rise 100%, acceleration ≥ 1.0, near high 0.90,
real SOL 1–40, min age 100 slots, stake 0.10 SOL, buy slippage 1500 bps,
stop-loss 8%, trailing stop 15% armed at +5%, max hold 150 slots,
max 1 entry per curve, 100-slot cooldown, probe 0.01 SOL,
guardrail pace 25 coins / 240 fills over 14400 s.
