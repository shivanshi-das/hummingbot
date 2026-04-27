from decimal import Decimal
from typing import Any, Dict, Optional

import hummingbot.connector.exchange.gemini.gemini_constants as CONSTANTS
from hummingbot.core.data_type.in_flight_order import OrderState


def convert_timestamp_seconds_to_ms(timestamp_seconds: str) -> float:
    """
    Converts Gemini seconds timestamp to milliseconds.

    Gemini REST responses include both:
    - timestamp: seconds (string)
    - timestampms: milliseconds (integer)

    Prefer timestampms when available.

    :param timestamp_seconds: timestamp in seconds as string
    :return: timestamp in milliseconds
    """
    return float(timestamp_seconds) * 1000


def convert_timestamp_ms_to_seconds(timestamp_ms: int) -> float:
    """
    Converts milliseconds to seconds for Hummingbot.

    :param timestamp_ms: timestamp in milliseconds
    :return: timestamp in seconds
    """
    return float(timestamp_ms) / 1000.0


def parse_order_status(order_data: Dict[str, Any]) -> OrderState:
    """
    Determines order state from Gemini REST response.

    Gemini doesn't have an explicit status field. Must derive from flags:
    - is_live: Order active on book
    - is_cancelled: Order was cancelled
    - remaining_amount: How much is left to fill
    - executed_amount: How much has filled

    :param order_data: order data from Gemini API
    :return: OrderState enum value
    """
    is_live = order_data.get("is_live", False)
    is_cancelled = order_data.get("is_cancelled", False)
    remaining = Decimal(str(order_data.get("remaining_amount", "0")))
    executed = Decimal(str(order_data.get("executed_amount", "0")))
    original = Decimal(str(order_data.get("original_amount", "0")))

    if is_cancelled:
        return OrderState.CANCELED
    elif remaining == Decimal("0") and executed > Decimal("0"):
        # Fully filled
        return OrderState.FILLED
    elif executed > Decimal("0") and remaining > Decimal("0"):
        # Partially filled
        return OrderState.PARTIALLY_FILLED
    elif is_live:
        # Active on order book
        return OrderState.OPEN
    elif executed == Decimal("0") and remaining == original:
        # Order submitted but not yet on book
        return OrderState.PENDING_CREATE
    else:
        # Rejected or failed
        return OrderState.FAILED


def get_market_order_buffer_pct(config: Optional[Dict[str, Any]] = None) -> Decimal:
    """
    Gets the market order price buffer percentage.

    Since Gemini doesn't support true market orders, limit orders
    with price buffer are used instead.

    :param config: optional configuration dict with 'market_order_buffer_pct'
    :return: buffer percentage (default 2%)
    """
    if config and "market_order_buffer_pct" in config:
        return Decimal(str(config["market_order_buffer_pct"]))
    return Decimal(str(CONSTANTS.DEFAULT_MARKET_ORDER_BUFFER_PCT))


def is_spot_symbol(symbol_details: Dict[str, Any]) -> bool:
    """
    Checks if a symbol is a spot trading pair.

    Uses the product_type field from /v1/symbols/details/{symbol} response.
    This is more reliable than checking for hyphens in the symbol name.

    :param symbol_details: symbol details from Gemini API
    :return: True if spot symbol, False otherwise
    """
    product_type = symbol_details.get("product_type", "")
    return product_type == "spot"
