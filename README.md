# Pump.fun Replay Sprint — Quick-Flip Paper Bot

[![competition](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122.svg)](https://make.fun/c/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)
[![rank](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/yudhisutawan/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/rank.svg)](https://make.fun/c/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)
[![reward](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/yudhisutawan/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/reward.svg)](https://make.fun/c/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)

A paper trading bot for the [Pump.fun Replay Sprint](https://make.fun/c/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)
competition on [make.fun](https://make.fun). It trades 10 SOL of paper money
on a 24-hour replay of pump.fun bonding-curve activity. Best net PnL wins.

## Strategy

Quick-flip momentum: buy a curve (age ≥ 100 slots) whose last 15 slots show
accelerating net buy inflow (≥ 2 SOL, ≥ 3 buys, ≥ 5 distinct buyers, price
up ≥ 3% and within 10% of its window high), stake 0.10 SOL, then leave fast:
−8% stop-loss, 15% trailing stop armed at +5%, or 150 slots, whichever comes
first. One entry per curve, never pyramids. Tiny 0.01 SOL probe round trips
keep the run above the 20-coin guardrail on quiet stretches.

The strategy was picked by a 6-way backtest tournament on the dev window
(see [TOURNAMENT.md](TOURNAMENT.md)): net **−0.0201 SOL**, 163 trips,
23 wins, 90 coins, max drawdown 0.019 — and **+0.0204 SOL** on a fresh
sample of coins the strategy was never tuned on. The house momentum pilot
loses −9.38 SOL on the same window; the equal-weight baseline fails the
20-coin guardrail outright.

## Layout

- `main.py` — the bot. Standard library only; speaks `agent-fun/replay/v2`
  on stdin/stdout through the vendored shim.
- `vendor/makefun_bot.py` — the kit's Python bot shim (unchanged from the kit).
- `TOURNAMENT.md` — how the candidates were compared and why this one won.

## Run

The grader runs `python3 -P -s main.py` with `PYTHONHASHSEED=0`. The bot
reads the `hello`, `batch` and `done` messages on stdin and answers each
batch with its orders on stdout. It never reads the clock, the environment
or unseeded randomness, so the two graded executions produce byte-identical
action logs.

## License

MIT — see [LICENSE](LICENSE).
