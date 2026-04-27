import time
from typing import Callable, Optional

import hummingbot.connector.exchange.gemini.gemini_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.connector.utils import TimeSynchronizerRESTPreProcessor
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


def rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Creates a full URL for provided REST endpoint.

    :param path_url: a REST endpoint (e.g., "/v1/symbols")
    :param domain: the Gemini domain to connect to ("gemini_main" or "gemini_sandbox")
    :return: the full URL to the endpoint
    """
    base_url = CONSTANTS.REST_URLS[domain]
    return base_url + path_url


def wss_url(domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Returns the WebSocket URL for Order Events (private).

    :param domain: the Gemini domain to connect to
    :return: the WebSocket URL for order events
    """
    return CONSTANTS.WSS_URLS[domain]


def wss_market_data_url(domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """
    Returns the WebSocket URL for Market Data v2 (public).

    :param domain: the Gemini domain to connect to
    :return: the WebSocket URL for market data
    """
    return CONSTANTS.WSS_MARKET_DATA_URLS[domain]


def build_api_factory(
        throttler: Optional[AsyncThrottler] = None,
        time_synchronizer: Optional[TimeSynchronizer] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
        time_provider: Optional[Callable] = None,
        auth: Optional[AuthBase] = None,
) -> WebAssistantsFactory:
    """
    Creates a WebAssistantsFactory with Gemini-specific configuration.

    :param throttler: the AsyncThrottler to use for rate limiting
    :param time_synchronizer: the TimeSynchronizer for time sync
    :param domain: the Gemini domain
    :param time_provider: callable that returns current server time
    :param auth: the AuthBase instance for authentication
    :return: configured WebAssistantsFactory
    """
    throttler = throttler or create_throttler()
    time_synchronizer = time_synchronizer or TimeSynchronizer()
    time_provider = time_provider or (lambda: get_current_server_time(
        throttler=throttler,
        domain=domain,
    ))
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        auth=auth,
        rest_pre_processors=[
            TimeSynchronizerRESTPreProcessor(
                synchronizer=time_synchronizer,
                time_provider=time_provider
            ),
        ])
    return api_factory


def build_api_factory_without_time_synchronizer_pre_processor(
        throttler: AsyncThrottler
) -> WebAssistantsFactory:
    """
    Creates a WebAssistantsFactory without time synchronization.
    Used for getting server time.

    :param throttler: the AsyncThrottler to use
    :return: WebAssistantsFactory without time sync
    """
    api_factory = WebAssistantsFactory(throttler=throttler)
    return api_factory


def create_throttler() -> AsyncThrottler:
    """
    Creates an AsyncThrottler with Gemini rate limits.

    :return: AsyncThrottler configured for Gemini
    """
    return AsyncThrottler(CONSTANTS.RATE_LIMITS)


async def get_current_server_time(
        throttler: Optional[AsyncThrottler] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
) -> float:
    """
    Gets the current server time from Gemini.

    Gemini doesn't have a dedicated time endpoint, so we return
    current system time. The nonce validation has a ±30 second window.

    :param throttler: the AsyncThrottler to use
    :param domain: the Gemini domain
    :return: current time in seconds
    """
    # Gemini nonce validation has ±30 second window
    # System time is sufficient given this tolerance
    return time.time()


def convert_from_exchange_symbol(exchange_symbol: str) -> Optional[str]:
    """
    Converts Gemini symbol format to Hummingbot format.

    Gemini: btcusd, ethbtc (lowercase, no separator)
    Hummingbot: BTC-USD, ETH-BTC (uppercase with hyphen)

    :param exchange_symbol: symbol in Gemini format
    :return: symbol in Hummingbot format, or None if invalid
    """
    if not exchange_symbol:
        return None

    symbol_upper = exchange_symbol.upper()

    # Known quote currencies (order matters - try longer symbols first)
    quote_currencies = [
        "USDT", "GUSD", "USD", "EUR", "GBP", "SGD", "HKD", "JPY",
        "BTC", "ETH", "DAI", "BCH", "LTC"
    ]

    # Try to match known quote currencies
    for quote in quote_currencies:
        if symbol_upper.endswith(quote):
            base = symbol_upper[:-len(quote)]
            if base:  # Ensure base is not empty
                return f"{base}-{quote}"

    # Fallback: assume 3-letter base currency for common pairs
    # This handles less common quote currencies
    if len(symbol_upper) >= 6:
        base = symbol_upper[:3]
        quote = symbol_upper[3:]
        return f"{base}-{quote}"

    return None


def convert_to_exchange_symbol(hb_trading_pair: str) -> str:
    """
    Converts Hummingbot format to Gemini symbol format.

    Hummingbot: BTC-USD -> Gemini: btcusd
    Hummingbot: ETH-BTC -> Gemini: ethbtc

    :param hb_trading_pair: trading pair in Hummingbot format
    :return: symbol in Gemini format
    """
    return hb_trading_pair.replace("-", "").lower()
