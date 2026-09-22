def _points(signal, price):
    entry = float(signal["risk"]["entry"])
    px = float(price)
    return px - entry if signal["direction"] == "BUY" else entry - px


def _result_price(signal, final_prices):
    # If a target was reached, summarize the highest achieved target rather
    # than allowing a later EOD pullback to erase the achieved target result.
    hit = signal.get("highest_target_hit")
    if hit == "T3_HIT":
        return float(signal["risk"]["t3"])
    if hit == "T2_HIT":
        return float(signal["risk"]["t2"])
    if hit == "T1_HIT":
        return float(signal["risk"]["t1"])
    if signal.get("status") == "EXITED" and signal.get("exit_price") is not None:
        return float(signal["exit_price"])
    return float(final_prices.get(signal["symbol"], signal["risk"]["entry"]))


def build_summary(state, final_prices):
    lines = ["<b>📊 NSE MOMENTUM SUMMARY</b>", ""]
    count = 0
    total_points = 0
    winners = 0
    losers = 0

    for s in state.get("signals", {}).values():
        if s.get("status") not in {"ACTIVE", "EXITED", "CLOSED_EOD", "REVERSED"}:
            continue
        price = _result_price(s, final_prices)
        points = _points(s, price)

        # Use emoji based on result
        emoji = "✅" if points >= 0 else "❌"
        symbol = s['symbol']

        lines.append(f"{emoji} <b>{symbol}</b>: {points:+.2f} pts")
        count += 1
        total_points += points

        if points >= 0:
            winners += 1
        else:
            losers += 1

    if count == 0:
        lines.append("No completed alerts.")
    else:
        lines.append("")
        lines.append(f"<b>Summary:</b> {count} trades | {winners}W {losers}L | Total: {total_points:+.2f} pts")

    return "\n".join(lines)
