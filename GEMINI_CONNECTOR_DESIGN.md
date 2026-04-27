# Gemini Exchange Connector - Technical Design

**Date:** April 27, 2026
**Type:** CEX Spot Connector
**Status:** New implementation from scratch

---

## 1. Gemini API Specifications

### 1.1 Endpoints

**REST API:**
```
Production: https://api.gemini.com
Sandbox:    https://api.sandbox.gemini.com
Version:    v1
```

**WebSocket API:**
```
Production:    wss://ws.gemini.com
Sandbox:       wss://ws.sandbox.gemini.com
Market Data:   wss://api.gemini.com/v2/marketdata
Protocol:      Order Events API (private) + Market Data v2 (public)
```

**Performance Tiers:**
- Tier 2 (p99~15ms): Public internet via AWS us-east-1
- Tier 1 (p99~10ms): Direct regional connection (requires onboarding)
- Tier 0 (p99~5ms): Local Zone access (requires onboarding)

**Rate Limits:**
- Public REST: 120 requests/minute
- Private REST: Use conservative limits (no published rate)
- WebSocket: Low-latency streaming with heartbeat support

### 1.2 Authentication

**Method:** HMAC-SHA384

**Headers:**
```
X-GEMINI-APIKEY: <api_key>
X-GEMINI-PAYLOAD: <base64_json_payload>
X-GEMINI-SIGNATURE: <hex_hmac_sha384>
```

**Payload:**
```json
{
  "request": "/v1/order/new",
  "nonce": <seconds_timestamp>,
  "symbol": "btcusd",
  "amount": "1.0",
  "price": "45000.00",
  "side": "buy",
  "type": "exchange limit"
}
```

**Signature Generation:**
```python
payload = {"request": "/v1/order/new", "nonce": seconds_timestamp, ...}
b64_payload = base64.b64encode(json.dumps(payload).encode())
signature = hmac.new(api_secret.encode(), b64_payload, hashlib.sha384).hexdigest()
```

**Nonce Requirements:**
- Seconds-based (not milliseconds)
- Monotonic counter to prevent collisions
- Strictly increasing per API key

**WebSocket Authentication:**
- Must authenticate during initial handshake
- Cannot authenticate after connection established
- Uses same HMAC-SHA384 scheme

### 1.3 Key Endpoints

**Public REST:**
- `GET /v1/symbols` - List all trading pairs
- `GET /v1/symbols/details/{symbol}` - Symbol details (tick_size, min_order_size)
- `GET /v1/book/{symbol}` - Order book snapshot with bids/asks arrays
- `GET /v1/trades/{symbol}` - Trade history (limited to 7 days, 500 records)
- `GET /v1/pubticker/{symbol}` - Ticker (deprecated, use v2)
- `GET /v2/ticker/{symbol}` - Ticker v2 with OHLC data

**Private REST:**
- `POST /v1/order/new` - Place order (exchange limit/market/stop-limit)
- `POST /v1/order/cancel` - Cancel order by order_id
- `POST /v1/order/status` - Order status by order_id or client_order_id
- `POST /v1/orders` - List active orders
- `POST /v1/balances` - Account balances (currency, amount, available)
- `POST /v1/mytrades` - Trade fills with fee details

**WebSocket Order Events:**
- Connection: `wss://ws.gemini.com` (authenticated during handshake)
- Event types: `subscription_ack`, `heartbeat`, `initial`, `accepted`, `rejected`, `booked`, `fill`, `cancelled`, `cancel_rejected`, `closed`
- Optional: `?cancelOnDisconnect=true` for safety

**WebSocket Market Data v2:**
- Connection: `wss://api.gemini.com/v2/marketdata`
- Subscriptions: `l2` (Level 2 orderbook), `candles`, `trades`
- Optional: `?snapshot=-1` for full orderbook snapshot

### 1.4 Trading Pairs

**Format Conversion:**
```
Exchange:   btcusd, ethusd (lowercase, no separator)
Hummingbot: BTC-USD, ETH-USD (uppercase with hyphen)
```

**Derivative Filtering:**
- Exclude hyphenated symbols (BTC-PERP) for spot connector

### 1.5 Order Types

| Type | Support | Implementation |
|------|---------|----------------|
| LIMIT | Native | Direct submission |
| MARKET | No | Convert to limit with price buffer |
| STOP_LIMIT | Native | Direct submission |

**Market Order Conversion:**
1. Fetch current price from order book
2. Apply buffer (e.g., +2% buy, -2% sell)
3. Submit as limit order

### 1.6 Gemini-Specific Quirks

**Timestamp Precision:**
- REST order responses include both `timestamp` (seconds) and `timestampms` (milliseconds)
- WebSocket messages use Unix milliseconds for consistency
- Ticker endpoints return millisecond timestamps in volume data

**Nonce Requirements:**
- Time-based nonce must be within ±30 seconds of server time
- Non-time-based nonce must be strictly increasing per session
- Use monotonic counter to prevent collisions

**Order Response Fields:**
- All orders include: `order_id`, `symbol`, `exchange`, `price`, `avg_execution_price`, `side`, `type`
- Status flags: `is_live` (active on book), `is_cancelled`, `is_hidden`, `was_forced`
- Amounts: `original_amount`, `executed_amount`, `remaining_amount`
- Optional: `client_order_id`, `options` array, `reason` (for cancellations)
- Fill details: `trades` array (only when `include_trades=true`)

**Fill Event Format:**
- Fill events include nested `fill` object with:
  - `trade_id`, `liquidity` (Taker/Maker), `price`, `amount`
  - `fee`, `fee_currency`

**Cancellation Reasons:**
- `MakerOrCancelWouldTake`, `ImmediateOrCancelWouldPost`, `FillOrKillWouldNotFill`
- `ExceedsPriceLimits`, `SelfCrossPrevented`, `Requested`
- `MarketClosed`, `TradingClosed`

**WebSocket Subscription Format:**
```json
{
  "type": "subscribe",
  "subscriptions": [
    {"name": "l2", "symbols": ["BTCUSD", "ETHUSD"]}
  ]
}
```

**Market Data v2 Updates:**
```json
{
  "type": "l2_updates",
  "symbol": "BTCUSD",
  "changes": [["buy", "9122.04", "0.00121425"]],
  "trades": [{"type": "trade", "eventid": 169841458, ...}]
}
```

### 1.7 API Request/Response Examples

**Order Placement Request:**
```json
POST /v1/order/new
Headers:
  X-GEMINI-APIKEY: account-T4KbUObJSd2FKT6DJsK
  X-GEMINI-PAYLOAD: eyJyZXF1ZXN0IjoiL3YxL29yZGVyL25ldyIsIm5vbmNlIjoxNzE0MDUyNDAwLCJzeW1ib2wiOiJidGN1c2QiLCJhbW91bnQiOiIwLjAxIiwicHJpY2UiOiI0NTAwMC4wMCIsInNpZGUiOiJidXkiLCJ0eXBlIjoiZXhjaGFuZ2UgbGltaXQifQ==
  X-GEMINI-SIGNATURE: 3d3f3a89c0e1bfa4aa...

Decoded Payload:
{
  "request": "/v1/order/new",
  "nonce": 1714052400,
  "symbol": "btcusd",
  "amount": "0.01",
  "price": "45000.00",
  "side": "buy",
  "type": "exchange limit",
  "client_order_id": "HBOT-GEMINI-1234567890",
  "options": []
}
```

**Order Placement Response (Partially Filled):**
```json
{
  "order_id": "109535955",
  "id": "109535955",
  "symbol": "btcusd",
  "exchange": "gemini",
  "avg_execution_price": "3592.23",
  "side": "buy",
  "type": "exchange limit",
  "timestamp": "1547743216",
  "timestampms": 1547743216580,
  "is_live": true,
  "is_cancelled": false,
  "is_hidden": false,
  "was_forced": false,
  "executed_amount": "0.5",
  "remaining_amount": "0.5",
  "original_amount": "1",
  "price": "3592.23",
  "client_order_id": "my-order-123",
  "options": ["maker-or-cancel"],
  "reason": null
}
```

**Order Placement Response (Pending/Open):**
```json
{
  "order_id": "109944118",
  "symbol": "btcusd",
  "side": "buy",
  "type": "exchange limit",
  "timestampms": 1547743998712,
  "is_live": true,
  "is_cancelled": false,
  "avg_execution_price": "0",
  "executed_amount": "0",
  "remaining_amount": "1",
  "original_amount": "1",
  "price": "3590.00"
}
```

**Order Placement Response (Filled):**
```json
{
  "order_id": "109535955",
  "symbol": "btcusd",
  "side": "sell",
  "type": "exchange limit",
  "timestampms": 1547743216580,
  "is_live": false,
  "is_cancelled": false,
  "avg_execution_price": "3592.23",
  "executed_amount": "1",
  "remaining_amount": "0",
  "original_amount": "1",
  "price": "3592.23"
}
```

**Order Status Response:**
```json
{
  "order_id": "109535955",
  "symbol": "btcusd",
  "is_live": false,
  "is_cancelled": false,
  "avg_execution_price": "3592.23",
  "executed_amount": "1",
  "remaining_amount": "0"
}
```

**Status Values (derived from fields):**
- **Pending**: `is_live: true`, `executed_amount: "0"`
- **Booked**: `is_live: true`, `executed_amount > 0`, `remaining_amount > 0`
- **Filled**: `is_live: false`, `remaining_amount: "0"`, `is_cancelled: false`
- **Cancelled**: `is_cancelled: true`
- **Rejected**: `reason` field present, `is_live: false`, `is_cancelled: false`

**My Trades Response:**
```json
[
  {
    "price": "3592.23",
    "amount": "1",
    "timestamp": 1547743216,
    "timestampms": 1547743216580,
    "type": "Sell",
    "aggressor": true,
    "fee_currency": "USD",
    "fee_amount": "8.980575",
    "tid": 109535970,
    "order_id": "109535955",
    "exchange": "gemini",
    "is_auction_fill": false,
    "is_clearing_fill": false,
    "symbol": "btcusd",
    "client_order_id": "my-order-123"
  }
]
```

**Fee Representation:**
- `fee_currency`: Currency of the fee (usually quote currency)
- `fee_amount`: Decimal string representing the fee
- Fees are always positive values
- `aggressor`: true = Taker, false = Maker

**Balances Response:**
```json
[
  {
    "type": "exchange",
    "currency": "BTC",
    "amount": "10.52341234",
    "available": "10.00000000",
    "availableForWithdrawal": "10.00000000"
  },
  {
    "type": "exchange",
    "currency": "USD",
    "amount": "50423.67",
    "available": "48000.00",
    "availableForWithdrawal": "48000.00"
  }
]
```

**Field Meanings:**
- `amount`: Total balance (available + held in orders)
- `available`: Available for trading (amount - on_hold)
- `availableForWithdrawal`: Available for withdrawal (may differ due to withdrawal rules)
- `type`: Always "exchange" for spot balances

**WebSocket Order Events (Subscription Acknowledgement):**
```json
{
  "type": "subscription_ack",
  "accountId": 5365,
  "subscriptionId": "ws-order-events-5365-b8bk32clqeb13g9tk8p0",
  "symbolFilter": ["btcusd"],
  "eventTypeFilter": ["fill", "closed"]
}
```

**WebSocket Order Events (Heartbeat - every 5 seconds):**
```json
{
  "type": "heartbeat",
  "timestampms": 1547742998508,
  "sequence": 31,
  "trace_id": "b8biknoqppr32kc7gfgg",
  "socket_sequence": 37
}
```

**WebSocket Order Events (Initial Orders):**
```json
{
  "type": "initial",
  "order_id": "109535955",
  "symbol": "btcusd",
  "side": "buy",
  "order_type": "exchange limit",
  "timestampms": 1547743216580,
  "is_live": true,
  "is_cancelled": false,
  "price": "3592.23",
  "remaining_amount": "1",
  "original_amount": "1",
  "socket_sequence": 0
}
```

**WebSocket Order Events (Accepted):**
```json
{
  "type": "accepted",
  "order_id": "109535955",
  "event_id": "109535956",
  "symbol": "btcusd",
  "side": "buy",
  "timestampms": 1547743216580,
  "socket_sequence": 1
}
```

**WebSocket Order Events (Booked):**
```json
{
  "type": "booked",
  "order_id": "109535955",
  "event_id": "109535957",
  "symbol": "btcusd",
  "price": "3592.23",
  "remaining_amount": "1",
  "socket_sequence": 2
}
```

**WebSocket Order Events (Fill):**
```json
{
  "type": "fill",
  "order_id": "109535955",
  "api_session": "UI",
  "symbol": "btcusd",
  "side": "sell",
  "order_type": "exchange limit",
  "timestampms": 1547743216580,
  "is_live": false,
  "is_cancelled": false,
  "avg_execution_price": "3592.23",
  "executed_amount": "1",
  "remaining_amount": "0",
  "original_amount": "1",
  "price": "3592.23",
  "fill": {
    "trade_id": "109535970",
    "liquidity": "Maker",
    "price": "3592.23",
    "amount": "1",
    "fee": "8.980575",
    "fee_currency": "USD"
  },
  "socket_sequence": 81
}
```

**WebSocket Order Events (Cancelled):**
```json
{
  "type": "cancelled",
  "order_id": "109944118",
  "event_id": "109964524",
  "cancel_command_id": "109964523",
  "reason": "Requested",
  "symbol": "bchusd",
  "is_live": false,
  "is_cancelled": true,
  "socket_sequence": 22
}
```

**WebSocket Order Events (Rejected):**
```json
{
  "type": "rejected",
  "order_id": "104246",
  "event_id": "104247",
  "reason": "InvalidPrice",
  "symbol": "btcusd",
  "is_live": false,
  "socket_sequence": 310311
}
```

**WebSocket Order Events (Closed):**
```json
{
  "type": "closed",
  "order_id": "109535955",
  "symbol": "btcusd",
  "socket_sequence": 99
}
```

**WebSocket Market Data v2 Subscription:**
```json
{
  "type": "subscribe",
  "subscriptions": [
    {
      "name": "l2",
      "symbols": ["BTCUSD", "ETHUSD"]
    }
  ]
}
```

**WebSocket Market Data v2 Updates:**
```json
{
  "type": "l2_updates",
  "symbol": "BTCUSD",
  "changes": [
    ["buy", "45000.00", "0.5"],
    ["sell", "45001.00", "0.75"]
  ],
  "trades": [
    {
      "type": "trade",
      "symbol": "BTCUSD",
      "eventId": 169841458,
      "timestamp": 1560976400428,
      "price": "45000.50",
      "quantity": "0.01",
      "side": "sell"
    }
  ],
  "auction_events": []
}
```

### 1.8 Symbol Details and Trading Rules

**Get All Symbols (`GET /v1/symbols`):**
```json
["btcusd", "ethbtc", "ethusd", "ltcusd", "bchusd", "zecusd"]
```

**Get Symbol Details (`GET /v1/symbols/details/{symbol}`):**
```json
{
  "symbol": "btcusd",
  "base_currency": "BTC",
  "quote_currency": "USD",
  "tick_size": 1e-2,
  "quote_increment": 0.01,
  "min_order_size": "0.00001",
  "status": "open",
  "wrap_enabled": false,
  "product_type": "spot"
}
```

**Field Meanings:**
- `tick_size` / `quote_increment`: Minimum price increment (0.01 = $0.01 for USD pairs)
- `min_order_size`: Minimum order quantity in base currency
- `status`: "open" (tradeable) or "closed" (not tradeable)
- `product_type`: Always "spot" for spot connector

### 1.9 Error Responses

**Rate Limit (429):**
```json
{
  "result": "error",
  "reason": "RateLimited",
  "message": "Rate limit exceeded"
}
```

**Authentication Failure (401):**
```json
{
  "result": "error",
  "reason": "InvalidSignature",
  "message": "InvalidSignature"
}
```

**Missing API Key (401):**
```json
{
  "result": "error",
  "reason": "MissingApiKey",
  "message": "Missing X-GEMINI-APIKEY header"
}
```

**Invalid Order (400):**
```json
{
  "result": "error",
  "reason": "InvalidPrice",
  "message": "Invalid price"
}
```

**Common Error Reasons:**
- `InvalidPrice` - Price outside valid range or wrong increment
- `InvalidQuantity` - Quantity below min or above max
- `InvalidSymbol` - Trading pair doesn't exist
- `MarketNotOpen` - Market is closed
- `InsufficientFunds` - Not enough balance
- `InvalidJson` - Malformed JSON request
- `DuplicatedClientOrderId` - Client order ID already used

**Forbidden (403):**
```json
{
  "result": "error",
  "reason": "AccessForbidden",
  "message": "Access forbidden"
}
```

### 1.10 Quick Reference

| Feature | Value |
|---------|-------|
| Symbol format | Lowercase, no separator: `"btcusd"` |
| Order type strings | `"exchange limit"`, `"exchange market"`, `"exchange stop limit"` |
| Execution options | `"maker-or-cancel"`, `"immediate-or-cancel"`, `"fill-or-kill"` |
| Client order ID | Supported, max 37 chars, field: `client_order_id` |
| Timestamp fields | Both `timestamp` (seconds, string) and `timestampms` (ms, integer) |
| Side values | `"buy"`, `"sell"` |
| Liquidity | `"Maker"`, `"Taker"` |
| Status derivation | Use `is_live`, `is_cancelled`, `remaining_amount` |
| WebSocket sequence | `socket_sequence` - zero-indexed, monotonic |
| Fee representation | `fee_amount` (positive decimal), `fee_currency` |
| Aggressor field | `true` = Taker, `false` = Maker |

---

## 2. Architecture

### 2.1 Class Hierarchy

```
ConnectorBase (connector_base.pyx)
└── ExchangeBase (exchange_base.pyx)
    └── ExchangePyBase (exchange_py_base.py)
        └── GeminiExchange (gemini_exchange.py)
```

### 2.2 Required Components

```
GeminiExchange
├── GeminiAuth (HMAC-SHA384 signature generation)
├── GeminiWebUtils (URL builders, API factory)
├── GeminiUtils (symbol conversion, timestamp handling)
├── GeminiAPIOrderBookDataSource (WebSocket order book streaming)
├── GeminiAPIUserStreamDataSource (authenticated WebSocket user stream)
└── GeminiOrderBook (message parsing)
```

### 2.3 File Structure

```
hummingbot/connector/exchange/gemini/
├── __init__.py
├── dummy.pyx / dummy.pxd
├── gemini_exchange.py                      # Main connector class
├── gemini_auth.py                          # HMAC-SHA384 authentication
├── gemini_constants.py                     # Endpoints, rate limits, mappings
├── gemini_web_utils.py                     # URL builders, API factory
├── gemini_utils.py                         # Symbol conversion, helpers
├── gemini_api_order_book_data_source.py   # Order book WebSocket
├── gemini_api_user_stream_data_source.py  # User stream WebSocket
└── gemini_order_book.py                    # Message parsing

test/hummingbot/connector/exchange/gemini/
├── test_gemini_auth.py
├── test_gemini_exchange.py
├── test_gemini_order_book.py
├── test_gemini_utils.py
└── test_gemini_web_utils.py
```

---

## 3. Implementation Details

### 3.1 Constants (gemini_constants.py)

```python
from hummingbot.core.api_throttler.data_types import RateLimit, LinkedLimitWeightPair
from hummingbot.core.data_type.in_flight_order import OrderState

DEFAULT_DOMAIN = "gemini_main"

# Domain-based URLs
REST_URLS = {
    "gemini_main": "https://api.gemini.com",
    "gemini_sandbox": "https://api.sandbox.gemini.com"
}

WSS_URLS = {
    "gemini_main": "wss://ws.gemini.com",
    "gemini_sandbox": "wss://ws.sandbox.gemini.com"
}

WSS_MARKET_DATA_URLS = {
    "gemini_main": "wss://api.gemini.com/v2/marketdata",
    "gemini_sandbox": "wss://api.sandbox.gemini.com/v2/marketdata"
}

# Order ID configuration
HBOT_ORDER_ID_PREFIX = "HBOT-GEMINI-"
MAX_ORDER_ID_LEN = 32

# Rate limits
REQUEST_WEIGHT = "REQUEST_WEIGHT"
ONE_MINUTE = 60
MAX_REQUEST = 5000

RATE_LIMITS = [
    RateLimit(
        limit_id=REQUEST_WEIGHT,
        limit=120,
        time_interval=ONE_MINUTE
    ),
]

# Order state mapping (from WebSocket event types)
ORDER_STATE = {
    "accepted": OrderState.PENDING_CREATE,
    "booked": OrderState.OPEN,
    "fill": OrderState.PARTIALLY_FILLED,  # Check remaining_amount for complete fill
    "closed": OrderState.FILLED,
    "cancelled": OrderState.CANCELED,
    "rejected": OrderState.FAILED,
    "cancel_rejected": OrderState.FAILED,
}

# Additional order status flags (from REST responses)
# is_live=True: Order is active on book (OrderState.OPEN)
# is_cancelled=True: Order was cancelled (OrderState.CANCELED)
# remaining_amount=0: Order completely filled (OrderState.FILLED)

# Public endpoints
SYMBOLS_PATH_URL = "/v1/symbols"
SYMBOL_DETAILS_PATH_URL = "/v1/symbols/details"  # + /{symbol}
BOOK_PATH_URL = "/v1/book"  # + /{symbol}
TRADES_PATH_URL = "/v1/trades"  # + /{symbol}
TICKER_PATH_URL = "/v1/pubticker"  # + /{symbol} (deprecated)
TICKER_V2_PATH_URL = "/v2/ticker"  # + /{symbol}

# Private endpoints
BALANCES_PATH_URL = "/v1/balances"
ORDER_NEW_PATH_URL = "/v1/order/new"
ORDER_CANCEL_PATH_URL = "/v1/order/cancel"
ORDER_STATUS_PATH_URL = "/v1/order/status"
ACTIVE_ORDERS_PATH_URL = "/v1/orders"
MY_TRADES_PATH_URL = "/v1/mytrades"
```

### 3.2 Web Utils (gemini_web_utils.py)

```python
from typing import Optional
from hummingbot.connector.exchange.gemini import gemini_constants as CONSTANTS
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler

def get_rest_url_for_endpoint(endpoint: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """Build REST URL for endpoint."""
    base_url = CONSTANTS.REST_URLS[domain]
    return f"{base_url}{endpoint}"

def get_wss_url(domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """Get WebSocket URL for domain."""
    return CONSTANTS.WSS_URLS[domain]

def build_api_factory(domain: str = CONSTANTS.DEFAULT_DOMAIN) -> WebAssistantsFactory:
    """Create API factory with throttler."""
    throttler = AsyncThrottler(CONSTANTS.RATE_LIMITS)
    return WebAssistantsFactory(throttler=throttler)

def convert_from_exchange_trading_pair(exchange_symbol: str) -> str:
    """Convert exchange symbol to Hummingbot format.

    Example: btcusd -> BTC-USD
    """
    # Implementation: parse lowercase symbol and add hyphen
    pass

def convert_to_exchange_trading_pair(hb_trading_pair: str) -> str:
    """Convert Hummingbot trading pair to exchange format.

    Example: BTC-USD -> btcusd
    """
    # Implementation: remove hyphen and lowercase
    pass
```

### 3.3 Authentication (gemini_auth.py)

```python
import base64
import hashlib
import hmac
import json
import time
from typing import Dict, Any
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest

class GeminiAuth(AuthBase):
    def __init__(self, api_key: str, secret_key: str, domain: str):
        self._api_key = api_key
        self._api_secret = secret_key
        self._domain = domain
        self._last_nonce = 0

    def _get_nonce(self) -> int:
        """Generate monotonic nonce in seconds."""
        nonce = int(time.time())
        if nonce <= self._last_nonce:
            nonce = self._last_nonce + 1
        self._last_nonce = nonce
        return nonce

    def add_auth_to_params(
        self,
        request: RESTRequest
    ) -> RESTRequest:
        """Add authentication headers to REST request."""
        payload = {
            "request": request.url.path,
            "nonce": self._get_nonce(),
            **request.data
        }

        # Base64 encode
        b64_payload = base64.b64encode(
            json.dumps(payload).encode()
        )

        # HMAC-SHA384 signature
        signature = hmac.new(
            self._api_secret.encode(),
            b64_payload,
            hashlib.sha384
        ).hexdigest()

        # Add headers
        request.headers = {
            "X-GEMINI-APIKEY": self._api_key,
            "X-GEMINI-PAYLOAD": b64_payload.decode(),
            "X-GEMINI-SIGNATURE": signature,
            "Content-Type": "text/plain"
        }

        return request

    async def ws_authenticate(self, ws: WSAssistant) -> WSRequest:
        """Generate WebSocket authentication request for handshake."""
        # Create auth payload similar to REST
        payload = {
            "request": "/v1/order/events",
            "nonce": self._get_nonce()
        }

        b64_payload = base64.b64encode(json.dumps(payload).encode())
        signature = hmac.new(
            self._api_secret.encode(),
            b64_payload,
            hashlib.sha384
        ).hexdigest()

        # Return auth headers for WebSocket handshake
        return WSRequest(
            headers={
                "X-GEMINI-APIKEY": self._api_key,
                "X-GEMINI-PAYLOAD": b64_payload.decode(),
                "X-GEMINI-SIGNATURE": signature
            }
        )
```

### 3.4 Exchange Class (gemini_exchange.py)

```python
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.exchange.gemini import gemini_constants as CONSTANTS
from hummingbot.connector.exchange.gemini.gemini_auth import GeminiAuth
from hummingbot.connector.exchange.gemini import gemini_web_utils as web_utils
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

class GeminiExchange(ExchangePyBase):

    def __init__(
        self,
        client_config_map: "ClientConfigMap",
        gemini_api_key: str,
        gemini_api_secret: str,
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
        domain: str = CONSTANTS.DEFAULT_DOMAIN
    ):
        self._domain = domain
        self._api_key = gemini_api_key
        self._api_secret = gemini_api_secret
        self._trading_pairs = trading_pairs or []
        self._trading_required = trading_required
        super().__init__(client_config_map)

    # Properties
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def authenticator(self) -> GeminiAuth:
        return GeminiAuth(
            api_key=self._api_key,
            secret_key=self._api_secret,
            domain=self._domain
        )

    @property
    def rate_limits_rules(self) -> List[RateLimit]:
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def client_order_id_max_length(self) -> int:
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self) -> str:
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_pairs(self) -> List[str]:
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True  # Gemini returns final state on cancel

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    def supported_order_types(self) -> List[OrderType]:
        return [OrderType.LIMIT, OrderType.MARKET, OrderType.LIMIT_MAKER]

    # Factory methods
    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(domain=self._domain)

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return GeminiAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            domain=self._domain,
            api_factory=self._web_assistants_factory
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        return GeminiAPIUserStreamDataSource(
            auth=self.authenticator,
            domain=self._domain,
            api_factory=self._web_assistants_factory
        )

    # Order management (abstract methods - must implement)
    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        price: Decimal,
        **kwargs
    ) -> Tuple[str, float]:
        """Place order on Gemini."""
        # Convert market orders to limit orders with buffer
        if order_type == OrderType.MARKET:
            # Fetch current price and apply buffer
            order_type = OrderType.LIMIT
            # price = adjusted_price_with_buffer

        symbol = web_utils.convert_to_exchange_trading_pair(trading_pair)

        data = {
            "symbol": symbol,
            "amount": str(amount),
            "price": str(price),
            "side": "buy" if trade_type == TradeType.BUY else "sell",
            "type": "exchange limit",  # Gemini order type
            "options": ["maker-or-cancel"] if order_type == OrderType.LIMIT_MAKER else []
        }

        url = web_utils.get_rest_url_for_endpoint(
            CONSTANTS.ORDER_NEW_PATH_URL,
            self._domain
        )

        response = await self._api_post(
            path_url=url,
            data=data,
            is_auth_required=True
        )

        exchange_order_id = response["order_id"]
        timestamp = response["timestampms"] / 1000

        return exchange_order_id, timestamp

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        """Cancel order on Gemini."""
        data = {"order_id": tracked_order.exchange_order_id}

        url = web_utils.get_rest_url_for_endpoint(
            CONSTANTS.ORDER_CANCEL_PATH_URL,
            self._domain
        )

        await self._api_post(
            path_url=url,
            data=data,
            is_auth_required=True
        )

    async def _request_order_status(
        self, tracked_order: InFlightOrder
    ) -> OrderUpdate:
        """Fetch order status from Gemini."""
        data = {"order_id": tracked_order.exchange_order_id}

        url = web_utils.get_rest_url_for_endpoint(
            CONSTANTS.ORDER_STATUS_PATH_URL,
            self._domain
        )

        response = await self._api_post(
            path_url=url,
            data=data,
            is_auth_required=True
        )

        new_state = CONSTANTS.ORDER_STATE.get(
            response["status"],
            OrderState.OPEN
        )

        return OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=response["order_id"],
            trading_pair=tracked_order.trading_pair,
            update_timestamp=response["timestampms"] / 1000,
            new_state=new_state
        )

    async def _all_trade_updates_for_order(
        self, tracked_order: InFlightOrder
    ) -> List[TradeUpdate]:
        """Fetch all trade fills for order from /v1/mytrades."""
        symbol = web_utils.convert_to_exchange_trading_pair(
            tracked_order.trading_pair
        )

        data = {"symbol": symbol}

        url = web_utils.get_rest_url_for_endpoint(
            CONSTANTS.MY_TRADES_PATH_URL,
            self._domain
        )

        response = await self._api_post(
            path_url=url,
            data=data,
            is_auth_required=True
        )

        # Filter trades for this order and convert to TradeUpdate
        trade_updates = []
        for trade in response:
            if trade["order_id"] == tracked_order.exchange_order_id:
                trade_updates.append(
                    TradeUpdate(
                        trade_id=trade["tid"],
                        client_order_id=tracked_order.client_order_id,
                        exchange_order_id=trade["order_id"],
                        trading_pair=tracked_order.trading_pair,
                        fill_timestamp=trade["timestampms"] / 1000,
                        fill_price=Decimal(trade["price"]),
                        fill_base_amount=Decimal(trade["amount"]),
                        fill_quote_amount=Decimal(trade["price"]) * Decimal(trade["amount"]),
                        fee=self._get_fee(
                            base_currency=tracked_order.base_asset,
                            quote_currency=tracked_order.quote_asset,
                            order_type=tracked_order.order_type,
                            order_side=tracked_order.trade_type,
                            amount=Decimal(trade["amount"]),
                            price=Decimal(trade["price"])
                        )
                    )
                )

        return trade_updates

    # Account management
    async def _update_balances(self):
        """Fetch and update account balances."""
        url = web_utils.get_rest_url_for_endpoint(
            CONSTANTS.BALANCES_PATH_URL,
            self._domain
        )

        response = await self._api_post(
            path_url=url,
            data={},
            is_auth_required=True
        )

        balances = {}
        for balance_entry in response:
            currency = balance_entry["currency"]
            balances[currency] = {
                "total": Decimal(balance_entry["amount"]),
                "available": Decimal(balance_entry["available"])
            }

        self._account_balances = {k: v["total"] for k, v in balances.items()}
        self._account_available_balances = {k: v["available"] for k, v in balances.items()}

    async def _update_trading_fees(self):
        """Fetch and update trading fee schedule."""
        # Gemini typically has 0.25% maker/taker for API users
        # Could be fetched from account endpoint if available
        pass

    async def _update_trading_rules(self):
        """Fetch and update trading rules (min size, increment, etc.)."""
        # Fetch from /v1/symbols/details/{symbol} endpoint
        pass

    # Utilities
    def _get_fee(
        self,
        base_currency: str,
        quote_currency: str,
        order_type: OrderType,
        order_side: TradeType,
        amount: Decimal,
        price: Decimal,
        is_maker: Optional[bool] = None
    ) -> TradeFeeBase:
        """Calculate trading fee."""
        # Default Gemini fee is 0.25% for both maker and taker
        fee_percent = Decimal("0.0025")
        return TradeFeeBase.new_spot_fee(
            fee_schema=self.trade_fee_schema(),
            trade_type=order_side,
            percent=fee_percent
        )

    def _format_trading_rules(
        self, exchange_info: Dict[str, Any]
    ) -> List[TradingRule]:
        """Parse exchange info into TradingRule objects."""
        # Parse symbol details into TradingRule format
        pass

    async def _initialize_trading_pair_symbols_from_exchange_info(
        self, exchange_info: Dict[str, Any]
    ):
        """Map exchange symbols to Hummingbot trading pairs."""
        # Filter out derivative symbols (hyphenated)
        # Convert to Hummingbot format
        pass
```

### 3.5 Order Book Data Source (gemini_api_order_book_data_source.py)

```python
from typing import Dict, List, Any
import asyncio
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.web_assistant.connections.data_types import WSRequest
from hummingbot.connector.exchange.gemini import gemini_constants as CONSTANTS
from hummingbot.connector.exchange.gemini import gemini_web_utils as web_utils

class GeminiAPIOrderBookDataSource(OrderBookTrackerDataSource):

    def __init__(
        self,
        trading_pairs: List[str],
        domain: str,
        api_factory: WebAssistantsFactory
    ):
        super().__init__(trading_pairs)
        self._domain = domain
        self._api_factory = api_factory

    async def _request_order_book_snapshot(
        self, trading_pair: str
    ) -> Dict[str, Any]:
        """Fetch order book snapshot via REST."""
        symbol = web_utils.convert_to_exchange_trading_pair(trading_pair)
        url = web_utils.get_rest_url_for_endpoint(
            f"{CONSTANTS.BOOK_PATH_URL}/{symbol}",
            self._domain
        )

        response = await self._api_get(url)
        return response

    async def _subscribe_channels(self, ws: WSAssistant):
        """Subscribe to order book WebSocket channels."""
        for trading_pair in self._trading_pairs:
            symbol = web_utils.convert_to_exchange_trading_pair(trading_pair)

            # Subscribe to order book depth updates
            subscribe_depth = {
                "type": "subscribe",
                "subscriptions": [
                    {
                        "name": f"{symbol}@depth",
                        "symbols": [symbol]
                    }
                ]
            }
            await ws.send(subscribe_depth)

            # Subscribe to trades
            subscribe_trades = {
                "type": "subscribe",
                "subscriptions": [
                    {
                        "name": f"{symbol}@trade",
                        "symbols": [symbol]
                    }
                ]
            }
            await ws.send(subscribe_trades)

    async def _parse_order_book_diff_message(
        self, raw_message: Dict[str, Any], message_queue: asyncio.Queue
    ):
        """Parse differential order book update."""
        if "changes" in raw_message:
            trading_pair = web_utils.convert_from_exchange_trading_pair(
                raw_message["symbol"]
            )

            order_book_message = OrderBookMessage(
                OrderBookMessageType.DIFF,
                {
                    "trading_pair": trading_pair,
                    "update_id": raw_message.get("eventId", 0),
                    "bids": self._parse_bids(raw_message["changes"]),
                    "asks": self._parse_asks(raw_message["changes"])
                },
                timestamp=raw_message["timestamp"] / 1000
            )
            message_queue.put_nowait(order_book_message)

    async def _parse_trade_message(
        self, raw_message: Dict[str, Any], message_queue: asyncio.Queue
    ):
        """Parse trade message (identified by 't' field)."""
        if "t" in raw_message:  # Trade message
            trading_pair = web_utils.convert_from_exchange_trading_pair(
                raw_message["symbol"]
            )

            trade_message = OrderBookMessage(
                OrderBookMessageType.TRADE,
                {
                    "trading_pair": trading_pair,
                    "trade_type": float(raw_message["side"]),
                    "trade_id": raw_message["t"],
                    "price": float(raw_message["price"]),
                    "amount": float(raw_message["amount"])
                },
                timestamp=raw_message["timestamp"] / 1000
            )
            message_queue.put_nowait(trade_message)

    def _parse_bids(self, changes: List[List]) -> List[Tuple[float, float]]:
        """Parse bid changes into (price, amount) tuples."""
        return [(float(change[1]), float(change[2]))
                for change in changes if change[0] == "buy"]

    def _parse_asks(self, changes: List[List]) -> List[Tuple[float, float]]:
        """Parse ask changes into (price, amount) tuples."""
        return [(float(change[1]), float(change[2]))
                for change in changes if change[0] == "sell"]
```

### 3.6 User Stream Data Source (gemini_api_user_stream_data_source.py)

```python
from typing import Dict, Any
import asyncio
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.connector.exchange.gemini import gemini_constants as CONSTANTS
from hummingbot.connector.exchange.gemini import gemini_web_utils as web_utils
from hummingbot.connector.exchange.gemini.gemini_auth import GeminiAuth
from hummingbot.core.data_type.in_flight_order import OrderUpdate
from decimal import Decimal

class GeminiAPIUserStreamDataSource(UserStreamTrackerDataSource):

    def __init__(
        self,
        auth: GeminiAuth,
        domain: str,
        api_factory: WebAssistantsFactory
    ):
        super().__init__()
        self._auth = auth
        self._domain = domain
        self._api_factory = api_factory

    async def _connected_websocket_assistant(self) -> WSAssistant:
        """Create authenticated WebSocket connection."""
        ws_url = web_utils.get_wss_url(self._domain)
        ws = await self._api_factory.get_ws_assistant()

        # Authenticate during connection (Gemini requirement)
        auth_request = await self._auth.ws_authenticate(ws)
        await ws.connect(ws_url, auth_request)

        return ws

    async def _subscribe_channels(self, ws: WSAssistant):
        """Subscribe to user stream channels."""
        subscribe_request = {
            "type": "subscribe",
            "subscriptions": [
                {"name": "account.order_events"},
                {"name": "account.balance_events"}
            ]
        }
        await ws.send(subscribe_request)

    async def _process_event_message(
        self, event_message: Dict[str, Any], queue: asyncio.Queue
    ):
        """Process user stream event."""
        event_type = event_message.get("type")

        if event_type in ["fill", "booked", "cancelled"]:
            # Order update event
            order_update = OrderUpdate(
                client_order_id=event_message.get("client_order_id"),
                exchange_order_id=event_message["order_id"],
                trading_pair=web_utils.convert_from_exchange_trading_pair(
                    event_message["symbol"]
                ),
                update_timestamp=event_message["timestamp_ns"] / 1e9,
                new_state=CONSTANTS.ORDER_STATE.get(
                    event_type,
                    OrderState.OPEN
                )
            )
            queue.put_nowait(order_update)

        elif event_type == "balance_update":
            # Balance update event
            # Process balance change
            pass
```

### 3.7 Configuration (conf/connectors/gemini.yml)

```yaml
gemini_api_key: ""
gemini_api_secret: ""
gemini_domain: "gemini_main"  # or "gemini_sandbox"
gemini_rate_limits_enabled: true
gemini_max_requests_per_minute: 120
gemini_client_order_id_prefix: "HBOT-GEMINI-"
gemini_cancel_on_disconnect: true
gemini_enable_time_sync: true
```

---

## 4. Testing Requirements

### 4.1 Unit Tests (80%+ coverage)

**test_gemini_auth.py:**
- HMAC-SHA384 signature generation
- Nonce monotonicity (no collisions)
- Header construction
- Payload Base64 encoding

**test_gemini_exchange.py:**
- Order placement (limit, market conversion)
- Order cancellation
- Balance updates
- Trading rule validation
- Symbol mapping
- Multi-domain URL construction

**test_gemini_order_book.py:**
- Snapshot parsing
- Differential updates
- Trade message parsing

**test_gemini_utils.py:**
- Symbol conversion (BTC-USD <-> btcusd)
- Timestamp conversion (nanoseconds/milliseconds/seconds)

### 4.2 Integration Tests (Sandbox)

**Setup:**
```bash
# Create Gemini sandbox account: https://exchange.sandbox.gemini.com/
# Generate sandbox API keys

export GEMINI_API_KEY="sandbox_key"
export GEMINI_API_SECRET="sandbox_secret"
export GEMINI_DOMAIN="gemini_sandbox"
```

**Test Cases:**

**Connection:**
- REST API connectivity
- WebSocket connectivity
- Authentication success/failure

**Order Lifecycle:**
- Place limit order -> Fill
- Place limit order -> Cancel
- Place market order (converted to limit)
- Place stop-limit order

**Data Streaming:**
- Order book updates (snapshot + diffs)
- Trade streaming
- User stream updates
- WebSocket reconnection after disconnect

**Edge Cases:**
- Network failure during order placement
- Invalid order parameters (below min size)
- Rate limit exceeded (429 response)
- Time sync failure (signature rejection)

---

## 5. Implementation Checklist

### 5.1 Core Implementation

- [ ] Create file structure (10 files)
- [ ] Implement gemini_constants.py (URLs, rate limits, mappings)
- [ ] Implement gemini_auth.py (HMAC-SHA384)
- [ ] Implement gemini_web_utils.py (URL builders, symbol conversion)
- [ ] Implement gemini_utils.py (timestamp conversion, helpers)
- [ ] Implement gemini_exchange.py (all ExchangePyBase methods)
- [ ] Implement gemini_api_order_book_data_source.py
- [ ] Implement gemini_api_user_stream_data_source.py
- [ ] Implement gemini_order_book.py (message parsing)
- [ ] Create configuration file (conf/connectors/gemini.yml)

### 5.2 Testing

- [ ] Write unit tests (5 test files)
- [ ] Run unit tests (target 80%+ coverage)
- [ ] Create Gemini sandbox account
- [ ] Generate sandbox API keys
- [ ] Run sandbox integration tests
- [ ] Test order placement/cancellation
- [ ] Test balance updates
- [ ] Test order book streaming
- [ ] Test user stream
- [ ] Test domain switching (main <-> sandbox)
- [ ] Test error scenarios
- [ ] Run strategy test (pure market making)

### 5.3 Documentation

- [ ] User setup guide (API key creation)
- [ ] Sandbox setup instructions
- [ ] Configuration examples
- [ ] Troubleshooting guide

---

## 6. Key Implementation Notes

### 6.1 Critical Requirements

1. **HMAC-SHA384 (not SHA256)** - Different from most exchanges
2. **Nonce in seconds (not milliseconds)** - Must be monotonic
3. **WebSocket auth in handshake** - Cannot auth after connection
4. **Market orders must be converted** - Gemini doesn't support them natively
5. **Fill details require REST call** - WebSocket events lack per-fill data
6. **Time sync critical** - ±5 second tolerance for signatures
7. **Multi-domain support** - Production and sandbox from day one

### 6.2 Order State Mapping

```
Gemini WebSocket Event -> Hummingbot OrderState
accepted -> PENDING_CREATE (order accepted, not yet on book)
booked -> OPEN (order placed on order book)
fill -> PARTIALLY_FILLED (check remaining_amount for complete fill)
closed -> FILLED (order completely filled)
cancelled -> CANCELED
rejected -> FAILED
cancel_rejected -> FAILED

REST API Status Flags:
is_live=True -> OPEN
is_cancelled=True -> CANCELED
remaining_amount=0 -> FILLED
```

### 6.3 Timestamp Handling

```
Order events: nanoseconds (divide by 1e9)
Balance updates: milliseconds (divide by 1000)
REST responses: seconds (use directly)
```

---

## 7. References

**Gemini API Documentation:**
- [REST API - Market Data](https://docs.gemini.com/rest/market-data)
- [REST API - Orders](https://docs.gemini.com/rest/orders)
- [REST API - Fund Management](https://docs.gemini.com/rest/fund-management)
- [WebSocket API Overview](https://docs.gemini.com/websocket/overview/introduction)
- [WebSocket API Reference](https://docs.gemini.com/websocket-api/)
- [WebSocket Order Events](https://docs.gemini.com/websocket/order-events/event-types)
- [WebSocket Market Data v2](https://docs.gemini.com/websocket/market-data/v2/about)
- [WebSocket Level 2 Data](https://docs.gemini.com/websocket/market-data/v2/level-2-data)
- [Authentication Guide](https://docs.gemini.com/rest-api/#authentication)
- [Sandbox Environment](https://docs.sandbox.gemini.com/)
- [Sandbox Registration](https://exchange.sandbox.gemini.com/)

**Hummingbot Architecture:**
- ExchangePyBase: `/hummingbot/connector/exchange_py_base.py`
- Example (Bybit): `/hummingbot/connector/exchange/bybit/`
- Example (Binance): `/hummingbot/connector/exchange/binance/`
- Paper Trading: `/hummingbot/connector/exchange/paper_trade/`

**Additional Resources:**
- [Gemini API Guide - AlgoTrading101](https://algotrading101.com/learn/gemini-api-guide/)
- [Gemini Python Wrapper](https://github.com/eliasbenaddou/gemini_api)
- [New WebSockets API Announcement](https://www.gemini.com/blog/new-websockets-api)
