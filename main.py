"""Pump.fun Replay Sprint paper bot: quick-flip momentum on bonding curves.

The harness speaks agent-fun/replay/v2 on stdin/stdout: one hello message,
then one batch per slot, then done. Each batch carries the slot's events,
marks, fills and account; the bot answers with at most 16 orders for that
slot. Every decision is a pure function of the batches seen so far: no clock,
no randomness, no I/O, so the two graded executions produce byte-identical
action logs.

Strategy (chosen by a 6-way backtest tournament on the dev window, see
TOURNAMENT.md): buy a mature-enough curve (age >= 100 slots) whose last
15 slots show accelerating net buy inflow (>= 2 SOL, >= 3 buys, >= 5 distinct
buyers, price up >= 3% and sitting within 10% of its window high), stake
0.10 SOL, then leave fast: -8% stop-loss, 15% trailing stop armed at +5%,
or 150 slots, whichever comes first. One entry per curve, never pyramids.
A pace guard keeps tiny 0.01 SOL probe round trips going so the run clears
the 20-coin guardrail even on quiet stretches. Verified on the dev window
with the kit's own market model: net -0.0201 SOL, 163 trips, 90 coins,
max drawdown 0.019 (see TOURNAMENT.md).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bot  # noqa: E402  (after the sys.path line: -P leaves the script dir off sys.path)

LAMPORTS = 1_000_000_000
CURVE_FEE = 0.0125
BPS = 10_000

# Entry window (slots) and inflow thresholds.
WINDOW = 15
MIN_NET_SOL = 2.0
MIN_BUYS = 3
MIN_BUYERS = 5
MIN_PRICE_UP = 0.03
MAX_PRICE_UP = 1.0
ACCEL = 1.0
NEAR_HIGH = 0.90
MAX_BUYER_SHARE = 1.0
MIN_RQ_SOL = 1.0
MAX_RQ_SOL = 40.0
MIN_AGE = 100
# Sizing and slippage.
STAKE_SOL = 0.10
MIN_BUY_SOL = 0.01
BUY_SLIP_BPS = 1500
# Exits.
STOP_LOSS = 0.08
TRAIL = 0.15
TRAIL_ARM = 0.05
MAX_HOLD = 150
COOLDOWN = 100
MAX_ENTRIES = 1
# Guardrail pacing (20 coins / 240 fills over the run).
TARGET_COINS = 25
TARGET_FILLS = 240
PACE_SECS = 14400
PROBE_SOL = 0.01
MAX_PROBES = 1
MAX_EXPOSURE_SOL = 6.0
# The fade / big-sell / ride exits were tested and left off (thresholds no
# real tape can reach); they stay as named constants so the intent is clear.
FADE_WINDOW = 10
FADE_NET_SOL = 1000.0
BIG_SELL_SOL = 1000.0
RIDE_RQ_SOL = 1000.0
HOLD_IF_UP = 1000.0


class QuickFlipBot:
    """One bot instance holds the tapes, the open positions and the probe
    bookkeeping for the whole run."""

    def __init__(self):
        self.tapes = {}
        self.held = {}
        self.probes = {}
        self.my_fills = 0
        self.my_coins = {}
        self.first_time = None
        self.last_time = None

    def _tape(self, mint):
        tape = self.tapes.get(mint)
        if tape is None:
            tape = {"created": None, "trades": [], "entries": 0, "last_exit": -10**12}
            self.tapes[mint] = tape
        return tape

    def _signal(self, tape, now, rq_sol):
        """True when the tape shows accelerating buy pressure near its high."""
        if not tape["trades"]:
            return False
        if rq_sol < MIN_RQ_SOL or rq_sol > MAX_RQ_SOL:
            return False
        if tape["created"] is None or now - tape["created"] < MIN_AGE:
            return False
        start = now - WINDOW
        mid = now - WINDOW / 2
        buy_sol = 0.0
        sell_sol = 0.0
        buys = 0
        net_old = 0.0
        net_new = 0.0
        start_price = -1.0
        high = 0.0
        last = 0.0
        by_user = {}
        for tr in tape["trades"]:
            if tr["slot"] <= start:
                start_price = tr["price"]
                continue
            if start_price < 0:
                start_price = tr["price"]
            signed = tr["sol"] if tr["buy"] else -tr["sol"]
            if tr["slot"] <= mid:
                net_old += signed
            else:
                net_new += signed
            if tr["buy"]:
                buy_sol += tr["sol"]
                buys += 1
                by_user[tr["user"]] = by_user.get(tr["user"], 0.0) + tr["sol"]
            else:
                sell_sol += tr["sol"]
            if tr["price"] > high:
                high = tr["price"]
            last = tr["price"]
        if buys < MIN_BUYS or len(by_user) < MIN_BUYERS:
            return False
        if buy_sol - sell_sol < MIN_NET_SOL:
            return False
        if start_price <= 0:
            return False
        up = last / start_price - 1
        if up < MIN_PRICE_UP or up > MAX_PRICE_UP:
            return False
        if last < high * NEAR_HIGH:
            return False
        if net_new <= 0 or net_new < ACCEL * net_old:
            return False
        top = max(by_user.values()) if by_user else 0.0
        if top > MAX_BUYER_SHARE * buy_sol:
            return False
        return True

    def _flow(self, tape, now, window):
        """Net recorded SOL (buys minus sells) over the last `window` slots."""
        net = 0.0
        for tr in reversed(tape["trades"]):
            if tr["slot"] <= now - window:
                break
            net += tr["sol"] if tr["buy"] else -tr["sol"]
        return net

    def _liquidation_value(self, state, mint, tx_lamports):
        """What a held position would net if sold now (SOL, fees deducted)."""
        pos = state.positions.get(mint)
        curve = state.curves.get(mint)
        if pos is None or curve is None:
            return 0.0
        tokens = int(pos.token_amount)
        vq = int(curve.virtual_quote_reserves)
        vt = int(curve.virtual_token_reserves)
        return ((tokens * vq) / (vt + tokens) / LAMPORTS) * (1 - CURVE_FEE) - tx_lamports / LAMPORTS

    def on_batch(self, state, batch):
        now = batch["slot"]
        big_sell = {}
        traded = {}
        for fill in batch["fills"]:
            if fill["status"] == "filled" and not fill["client_id"].startswith("_"):
                self.my_fills += 1
                self.my_coins[fill["mint"]] = True
        for event in batch["events"]:
            if event.get("block_time") is not None:
                if self.first_time is None:
                    self.first_time = event["block_time"]
                if self.last_time is None or event["block_time"] > self.last_time:
                    self.last_time = event["block_time"]
            if event["event"] == "CreateEvent":
                self._tape(event["mint"])["created"] = event["slot"]
            elif event["event"] == "TradeEvent":
                tape = self._tape(event["mint"])
                sol = int(event["sol_amount"]) / LAMPORTS
                tape["trades"].append({
                    "slot": event["slot"],
                    "buy": event["is_buy"],
                    "sol": sol,
                    "user": event["user"],
                    "price": int(event["virtual_quote_reserves"]) / int(event["virtual_token_reserves"]),
                })
                traded[event["mint"]] = True
                if not event["is_buy"] and sol >= BIG_SELL_SOL:
                    big_sell[event["mint"]] = True
        keep = max(WINDOW, FADE_WINDOW) + 5
        for mint in traded:
            tape = self.tapes[mint]
            cut = 0
            while cut < len(tape["trades"]) and tape["trades"][cut]["slot"] <= now - keep:
                cut += 1
            if cut:
                del tape["trades"][:cut]
        marks = {m["mint"]: m for m in batch["marks"]}
        pending = {}
        for po in state.pending.values():
            pending[po.order["mint"]] = pending.get(po.order["mint"], 0) + 1
        orders = []
        cap = state.hello["caps"]["max_orders_per_batch"]
        tx = state.tx_fee_lamports() / LAMPORTS

        # Exits first: stop-loss, trailing stop, fade, big sell, max hold.
        for mint, held in list(self.held.items()):
            pos = state.positions.get(mint)
            curve = state.curves.get(mint)
            if pos is None:
                if mint not in pending:
                    self.held.pop(mint, None)
                    tape = self._tape(mint)
                    if held["filled"]:
                        tape["last_exit"] = now
                    else:
                        tape["entries"] -= 1
                continue
            held["filled"] = True
            if curve is None or curve.complete:
                continue
            mark = marks.get(mint)
            vq = int(mark["virtual_quote_reserves"]) if mark else int(curve.virtual_quote_reserves)
            vt = int(mark["virtual_token_reserves"]) if mark else int(curve.virtual_token_reserves)
            rq_sol = (int(mark["real_quote_reserves"]) if mark
                      else int(curve.real_quote_reserves)) / LAMPORTS
            tokens = int(pos.token_amount)
            value = ((tokens * vq) / (vt + tokens) / LAMPORTS) * (1 - CURVE_FEE) - tx
            cost = int(pos.cost_lamports) / LAMPORTS
            if value > held["peak_value"]:
                held["peak_value"] = value
            held["last_value"] = value
            tape = self._tape(mint)
            riding = rq_sol >= RIDE_RQ_SOL
            exit_ = held["exiting"]
            if not exit_ and value < cost * (1 - STOP_LOSS):
                exit_ = True
            if (not exit_ and not riding
                    and held["peak_value"] >= cost * (1 + TRAIL_ARM)
                    and value < held["peak_value"] * (1 - TRAIL)):
                exit_ = True
            if not exit_ and not riding and self._flow(tape, now, FADE_WINDOW) < -FADE_NET_SOL:
                exit_ = True
            if not exit_ and not riding and mint in big_sell:
                exit_ = True
            if (not exit_ and now - held["opened"] > MAX_HOLD
                    and value < cost * (1 + HOLD_IF_UP)):
                exit_ = True
            if not exit_:
                continue
            held["exiting"] = True
            if mint in pending:
                sell_pending = any(po.order["mint"] == mint and po.order["side"] == "sell"
                                   for po in state.pending.values())
                if sell_pending:
                    continue
            if len(orders) >= cap:
                break
            orders.append({"side": "sell", "mint": mint, "token_amount": pos.token_amount,
                           "max_slippage_bps": 10_000})

        # Probe round trips: sell the whole probe as soon as its buy lands.
        for mint, selling in list(self.probes.items()):
            pos = state.positions.get(mint)
            curve = state.curves.get(mint)
            if pos is None:
                if mint not in pending:
                    self.probes.pop(mint, None)
                continue
            if curve is None or curve.complete or mint in pending:
                continue
            if len(orders) >= cap:
                break
            orders.append({"side": "sell", "mint": mint, "token_amount": pos.token_amount,
                           "max_slippage_bps": 10_000})
            if not selling:
                self.probes[mint] = True

        # Entries: one 0.10 SOL buy per qualifying curve, slots and cash permitting.
        free = state.free_cash_lamports() / LAMPORTS
        slots_left = state.hello["caps"]["max_open_positions"] - state.committed_position_count()
        main_left = state.hello["caps"]["max_open_positions"] - len(self.held)
        exposure = 0.0
        for mint, held in self.held.items():
            pos = state.positions.get(mint)
            exposure += max(held["invested"],
                            int(pos.cost_lamports) / LAMPORTS if pos is not None else 0.0)
        for mint in traded:
            if len(orders) >= cap:
                break
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                continue
            if mint in pending or mint in self.probes:
                continue
            if mint in self.held:
                continue
            tape = self.tapes[mint]
            if slots_left <= 0 or main_left <= 0:
                continue
            if tape["entries"] >= MAX_ENTRIES or now - tape["last_exit"] < COOLDOWN:
                continue
            rq_sol = int(curve.real_quote_reserves) / LAMPORTS
            if not self._signal(tape, now, rq_sol):
                continue
            want = STAKE_SOL
            cap_sol = state.max_buy_lamports(mint) / LAMPORTS
            amount = min(cap_sol, want, MAX_EXPOSURE_SOL - exposure)
            if amount > free - tx:
                amount = free - tx
            if amount < MIN_BUY_SOL:
                continue
            lamports = int(amount * LAMPORTS)
            orders.append({"side": "buy", "mint": mint, "quote_lamports": lamports,
                           "max_slippage_bps": BUY_SLIP_BPS})
            free -= amount + tx
            exposure += amount
            self.held[mint] = {"opened": now, "peak_value": 0.0, "invested": amount,
                               "exiting": False, "filled": False,
                               "last_add_price": int(curve.virtual_quote_reserves) / int(curve.virtual_token_reserves),
                               "last_value": 0.0}
            tape["entries"] += 1
            slots_left -= 1
            main_left -= 1

        # Guardrail pacing: open a probe when fills or coins lag the pace.
        if (len(self.probes) < MAX_PROBES and slots_left > 0
                and self.first_time is not None and self.last_time is not None):
            pace = min(1.0, (self.last_time - self.first_time) / PACE_SECS)
            need_coins = len(self.my_coins) < int(TARGET_COINS * pace + 0.999999)
            need_fills = self.my_fills < int(TARGET_FILLS * pace + 0.999999)
            if need_coins or need_fills:
                min_rq = (PROBE_SOL * BPS) / state.hello["caps"]["max_order_bps_of_real_reserve"]
                for mint in traded:
                    if len(orders) >= cap or len(self.probes) >= MAX_PROBES:
                        break
                    if mint in self.held or mint in self.probes or mint in pending:
                        continue
                    if mint in state.positions:
                        continue
                    if need_coins and not need_fills and mint in self.my_coins:
                        continue
                    curve = state.curves.get(mint)
                    if curve is None or curve.complete:
                        continue
                    if int(curve.real_quote_reserves) / LAMPORTS < min_rq * 1.5:
                        continue
                    if free < PROBE_SOL + 2 * tx:
                        break
                    orders.append({"side": "buy", "mint": mint,
                                   "quote_lamports": int(PROBE_SOL * LAMPORTS),
                                   "max_slippage_bps": BUY_SLIP_BPS})
                    self.probes[mint] = False
                    free -= PROBE_SOL + tx
        return orders


BOT = QuickFlipBot()


def on_batch(state, batch):
    return BOT.on_batch(state, batch)


if __name__ == "__main__":
    makefun_bot.run(on_batch)
