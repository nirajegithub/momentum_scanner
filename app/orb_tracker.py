"""Track which ORB source is used for breakout detection."""

import logging

LOG = logging.getLogger(__name__)


def log_orb_used(symbol, orb_data, orb_source, current_price, breakout_side):
    """Log which ORB was used and the resulting breakout detection.

    Args:
        symbol: Stock symbol
        orb_data: ORB high/low/close data
        orb_source: "TODAY_ORB" or "PREVIOUS_DAY_LAST_HOUR"
        current_price: Current close price
        breakout_side: "BUY" or "SELL" or None
    """
    orb_high = orb_data.get("high", 0)
    orb_low = orb_data.get("low", 0)
    orb_date = orb_data.get("date", "unknown")
    orb_time = orb_data.get("time", "unknown")

    if breakout_side == "BUY":
        LOG.info(
            "ORB BREAKOUT | %s | source=%s | orb_date=%s orb_time=%s | "
            "orb_high=%.2f | current=%.2f | direction=%s | "
            "price_above_orb_high=%.2f",
            symbol, orb_source, orb_date, orb_time,
            orb_high, current_price, breakout_side,
            current_price - orb_high
        )
    elif breakout_side == "SELL":
        LOG.info(
            "ORB BREAKOUT | %s | source=%s | orb_date=%s orb_time=%s | "
            "orb_low=%.2f | current=%.2f | direction=%s | "
            "price_below_orb_low=%.2f",
            symbol, orb_source, orb_date, orb_time,
            orb_low, current_price, breakout_side,
            orb_low - current_price
        )
    else:
        LOG.debug(
            "ORB NO_BREAKOUT | %s | source=%s | orb_date=%s orb_time=%s | "
            "orb_range=[%.2f-%.2f] | current=%.2f | in_range",
            symbol, orb_source, orb_date, orb_time,
            orb_low, orb_high, current_price
        )


def log_orb_selection(symbol, attempted_date, fallback_date, selected_source):
    """Log which ORB was selected (today's or fallback)."""
    if selected_source == "TODAY_ORB":
        LOG.info(
            "ORB SELECTED | %s | source=TODAY_ORB | date=%s",
            symbol, attempted_date
        )
    elif selected_source == "PREVIOUS_DAY_LAST_HOUR":
        LOG.info(
            "ORB SELECTED | %s | source=PREVIOUS_DAY_LAST_HOUR | "
            "today=%s | fallback_to=%s",
            symbol, attempted_date, fallback_date
        )
    else:
        LOG.warning(
            "ORB SELECTION UNKNOWN | %s | source=%s",
            symbol, selected_source
        )


def log_orb_comparison(symbol, today_orb, fallback_orb):
    """Log comparison if both ORBs are available (for diagnostics)."""
    if today_orb and fallback_orb:
        LOG.debug(
            "ORB COMPARISON | %s | today_high=%.2f today_low=%.2f | "
            "fallback_high=%.2f fallback_low=%.2f | "
            "range_diff=%.2f (today_wider=%s)",
            symbol,
            today_orb.get("high", 0), today_orb.get("low", 0),
            fallback_orb.get("high", 0), fallback_orb.get("low", 0),
            (today_orb.get("high", 0) - today_orb.get("low", 0)) -
            (fallback_orb.get("high", 0) - fallback_orb.get("low", 0)),
            (today_orb.get("high", 0) - today_orb.get("low", 0)) >
            (fallback_orb.get("high", 0) - fallback_orb.get("low", 0))
        )
