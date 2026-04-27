from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

# Default domain (sandbox for safety)
DEFAULT_DOMAIN = "gemini_sandbox"

# REST API URLs
REST_URLS = {
    "gemini_main": "https://api.gemini.com",
    "gemini_sandbox": "https://api.sandbox.gemini.com",
}

# WebSocket URLs - Order Events (Private)
WSS_URLS = {
    "gemini_main": "wss://ws.gemini.com",
    "gemini_sandbox": "wss://ws.sandbox.gemini.com",
}

# WebSocket URLs - Market Data v2 (Public)
WSS_MARKET_DATA_URLS = {
    "gemini_main": "wss://api.gemini.com/v2/marketdata",
    "gemini_sandbox": "wss://api.sandbox.gemini.com/v2/marketdata",
}

# Client order ID configuration
HBOT_ORDER_ID_PREFIX = "HBOT-"
MAX_ORDER_ID_LEN = 37  # Gemini supports up to 37 characters

# Rate limiting
ONE_MINUTE = 60
PUBLIC_RATE_LIMIT = 120  # requests per minute (documented)
PRIVATE_RATE_LIMIT = 60  # requests per minute (conservative)

RATE_LIMITS = [
    RateLimit(
        limit_id="PUBLIC_ENDPOINTS",
        limit=PUBLIC_RATE_LIMIT,
        time_interval=ONE_MINUTE
    ),
    RateLimit(
        limit_id="PRIVATE_ENDPOINTS",
        limit=PRIVATE_RATE_LIMIT,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair("PUBLIC_ENDPOINTS", 1)]
    ),
]

# Public REST endpoints
SYMBOLS_PATH_URL = "/v1/symbols"
SYMBOL_DETAILS_PATH_URL = "/v1/symbols/details"  # Append /{symbol}
ORDER_BOOK_PATH_URL = "/v1/book"  # Append /{symbol}
TRADES_PATH_URL = "/v1/trades"  # Append /{symbol}
TICKER_PATH_URL = "/v1/pubticker"  # Append /{symbol} (deprecated)
TICKER_V2_PATH_URL = "/v2/ticker"  # Append /{symbol}

# Private REST endpoints (all POST)
BALANCES_PATH_URL = "/v1/balances"
ORDER_NEW_PATH_URL = "/v1/order/new"
ORDER_CANCEL_PATH_URL = "/v1/order/cancel"
ORDER_STATUS_PATH_URL = "/v1/order/status"
ACTIVE_ORDERS_PATH_URL = "/v1/orders"
MY_TRADES_PATH_URL = "/v1/mytrades"
PAST_TRADES_PATH_URL = "/v1/mytrades"

# Order state mappings from WebSocket event types
ORDER_STATE = {
    "accepted": OrderState.PENDING_CREATE,
    "booked": OrderState.OPEN,
    "fill": OrderState.PARTIALLY_FILLED,  # Check remaining_amount for FILLED
    "closed": OrderState.FILLED,
    "cancelled": OrderState.CANCELED,
    "rejected": OrderState.FAILED,
    "cancel_rejected": OrderState.FAILED,
}

# Gemini order type strings
GEMINI_ORDER_TYPE_LIMIT = "exchange limit"
GEMINI_ORDER_TYPE_MARKET = "exchange market"  # Not supported, convert to limit
GEMINI_ORDER_TYPE_STOP_LIMIT = "exchange stop limit"

# Order execution options
ORDER_OPTION_MAKER_OR_CANCEL = "maker-or-cancel"
ORDER_OPTION_IMMEDIATE_OR_CANCEL = "immediate-or-cancel"
ORDER_OPTION_FILL_OR_KILL = "fill-or-kill"
ORDER_OPTION_AUCTION_ONLY = "auction-only"
ORDER_OPTION_INDICATION_OF_INTEREST = "indication-of-interest"

# WebSocket Order Events message types
WS_ORDER_EVENT_SUBSCRIPTION_ACK = "subscription_ack"
WS_ORDER_EVENT_HEARTBEAT = "heartbeat"
WS_ORDER_EVENT_INITIAL = "initial"
WS_ORDER_EVENT_ACCEPTED = "accepted"
WS_ORDER_EVENT_REJECTED = "rejected"
WS_ORDER_EVENT_BOOKED = "booked"
WS_ORDER_EVENT_FILL = "fill"
WS_ORDER_EVENT_CANCELLED = "cancelled"
WS_ORDER_EVENT_CANCEL_REJECTED = "cancel_rejected"
WS_ORDER_EVENT_CLOSED = "closed"

# WebSocket Market Data v2 message types
WS_MARKET_DATA_L2_UPDATES = "l2_updates"
WS_MARKET_DATA_TRADES = "trade"
WS_MARKET_DATA_SUBSCRIPTION = "subscribe"
WS_MARKET_DATA_HEARTBEAT = "heartbeat"
WS_MARKET_DATA_UPDATE = "update"

# WebSocket heartbeat interval (seconds)
WS_HEARTBEAT_INTERVAL = 5  # Gemini sends heartbeats every 5 seconds

# Error reasons from API
ERROR_RATE_LIMITED = "RateLimited"
ERROR_INVALID_SIGNATURE = "InvalidSignature"
ERROR_MISSING_API_KEY = "MissingApiKey"
ERROR_INVALID_NONCE = "InvalidNonce"
ERROR_INVALID_PRICE = "InvalidPrice"
ERROR_INVALID_QUANTITY = "InvalidQuantity"
ERROR_INVALID_SYMBOL = "InvalidSymbol"
ERROR_INSUFFICIENT_FUNDS = "InsufficientFunds"
ERROR_MARKET_NOT_OPEN = "MarketNotOpen"
ERROR_DUPLICATED_ORDER_ID = "DuplicatedClientOrderId"
ERROR_ORDER_NOT_FOUND = "OrderNotFound"
ERROR_INVALID_JSON = "InvalidJson"

# Cancellation reasons
CANCEL_REASON_MAKER_OR_CANCEL = "MakerOrCancelWouldTake"
CANCEL_REASON_IOC = "ImmediateOrCancelWouldPost"
CANCEL_REASON_FOK = "FillOrKillWouldNotFill"
CANCEL_REASON_PRICE_LIMITS = "ExceedsPriceLimits"
CANCEL_REASON_SELF_CROSS = "SelfCrossPrevented"
CANCEL_REASON_REQUESTED = "Requested"
CANCEL_REASON_MARKET_CLOSED = "MarketClosed"
CANCEL_REASON_TRADING_CLOSED = "TradingClosed"

# Market order price buffer (configurable)
DEFAULT_MARKET_ORDER_BUFFER_PCT = 0.02  # 2%

# Trading fees (default, can be updated with API)
DEFAULT_MAKER_FEE = 0.0025  # 0.25%
DEFAULT_TAKER_FEE = 0.0035  # 0.35%
