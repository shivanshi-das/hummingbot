import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import hummingbot.connector.exchange.gemini.gemini_constants as CONSTANTS
import hummingbot.connector.exchange.gemini.gemini_utils as utils
import hummingbot.connector.exchange.gemini.gemini_web_utils as web_utils
from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange.gemini.gemini_api_order_book_data_source import GeminiAPIOrderBookDataSource
from hummingbot.connector.exchange.gemini.gemini_api_user_stream_data_source import GeminiAPIUserStreamDataSource
from hummingbot.connector.exchange.gemini.gemini_auth import GeminiAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.api_throttler.data_types import RateLimit
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class GeminiExchange(ExchangePyBase):
    """
    Gemini exchange connector.

    Key features:
    - HMAC-SHA384 authentication
    - Seconds-based monotonic nonce
    - No native market orders (convert to limit)
    - Multi-domain support (main/sandbox)
    - WebSocket auth during handshake
    """

    web_utils = web_utils

    def __init__(
        self,
        gemini_api_key: str,
        gemini_api_secret: str,
        balance_asset_limit: Optional[Dict[str, Dict[str, Decimal]]] = None,
        rate_limits_share_pct: Decimal = Decimal("100"),
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
        domain: str = CONSTANTS.DEFAULT_DOMAIN
    ):
        self._api_key = gemini_api_key
        self._secret_key = gemini_api_secret
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs or []
        super().__init__(balance_asset_limit, rate_limits_share_pct)

    # ========== Required Properties ==========

    @property
    def name(self) -> str:
        """Exchange name."""
        if self._domain == "gemini_main":
            return "gemini"
        else:
            return f"gemini_{self._domain}"

    @property
    def authenticator(self) -> AuthBase:
        """Returns GeminiAuth instance."""
        return GeminiAuth(
            api_key=self._api_key,
            secret_key=self._secret_key,
            time_provider=self._time_synchronizer
        )

    @property
    def rate_limits_rules(self) -> List[RateLimit]:
        """Returns Gemini rate limits."""
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        """Returns domain (gemini_main or gemini_sandbox)."""
        return self._domain

    @property
    def client_order_id_max_length(self) -> int:
        """Maximum client order ID length (37 chars)."""
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self) -> str:
        """Client order ID prefix."""
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_rules_request_path(self) -> str:
        """Path for trading rules request."""
        return CONSTANTS.SYMBOLS_PATH_URL

    @property
    def trading_pairs_request_path(self) -> str:
        """Path for trading pairs request."""
        return CONSTANTS.SYMBOLS_PATH_URL

    @property
    def check_network_request_path(self) -> str:
        """Path for network check request."""
        return CONSTANTS.SYMBOLS_PATH_URL

    @property
    def trading_pairs(self) -> List[str]:
        """Returns list of trading pairs."""
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        """Gemini returns final state immediately on cancel."""
        return True

    @property
    def is_trading_required(self) -> bool:
        """Whether trading is required."""
        return self._trading_required

    def supported_order_types(self) -> List[OrderType]:
        """Supported order types."""
        return [OrderType.LIMIT, OrderType.MARKET, OrderType.LIMIT_MAKER]

    # ========== Error Detection Methods ==========

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception) -> bool:
        """Check if error is related to nonce/timestamp."""
        error_str = str(request_exception)
        return CONSTANTS.ERROR_INVALID_NONCE in error_str or "timestamp" in error_str.lower()

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        """Check if order not found during status check."""
        error_str = str(status_update_exception)
        return CONSTANTS.ERROR_ORDER_NOT_FOUND in error_str or "order" in error_str.lower()

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        """Check if order not found during cancellation."""
        return self._is_order_not_found_during_status_update_error(cancelation_exception)

    # ========== Factory Methods ==========

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        """Create web assistants factory."""
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
            auth=self._auth
        )

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        """Create order book data source."""
        return GeminiAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            domain=self._domain,
            api_factory=self._web_assistants_factory,
            throttler=self._throttler
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        """Create user stream data source."""
        return GeminiAPIUserStreamDataSource(
            auth=self._auth,
            domain=self._domain,
            api_factory=self._web_assistants_factory,
            throttler=self._throttler
        )

    # ========== Order Placement and Cancellation ==========

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
        """
        Places order on Gemini.

        CRITICAL: Gemini doesn't support market orders natively.
        Must convert to limit order with price buffer.
        """
        symbol = web_utils.convert_to_exchange_symbol(trading_pair)

        # Handle market orders - convert to limit with buffer
        if order_type == OrderType.MARKET:
            order_book = self.get_order_book(trading_pair)

            if trade_type == TradeType.BUY:
                # Market buy: use best ask + buffer
                best_ask = order_book.get_price(False)  # False = ask
                buffer_pct = utils.get_market_order_buffer_pct()
                price = best_ask * (Decimal("1") + buffer_pct)
            else:
                # Market sell: use best bid - buffer
                best_bid = order_book.get_price(True)  # True = bid
                buffer_pct = utils.get_market_order_buffer_pct()
                price = best_bid * (Decimal("1") - buffer_pct)

            # Convert to limit order
            order_type = OrderType.LIMIT

        # Build order parameters
        order_data = {
            "symbol": symbol,
            "amount": str(amount),
            "price": str(price),
            "side": "buy" if trade_type == TradeType.BUY else "sell",
            "type": CONSTANTS.GEMINI_ORDER_TYPE_LIMIT,
            "client_order_id": order_id
        }

        # Add execution options
        if order_type == OrderType.LIMIT_MAKER:
            order_data["options"] = [CONSTANTS.ORDER_OPTION_MAKER_OR_CANCEL]
        else:
            order_data["options"] = []

        # Send request
        url = web_utils.rest_url(CONSTANTS.ORDER_NEW_PATH_URL, self._domain)
        response = await self._api_post(
            path_url=url,
            data=order_data,
            is_auth_required=True,
            limit_id="PRIVATE_ENDPOINTS"
        )

        # Extract order ID and timestamp
        exchange_order_id = str(response["order_id"])
        timestamp = response["timestampms"] / 1000.0

        return exchange_order_id, timestamp

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        """Cancel order via POST /v1/order/cancel."""
        cancel_data = {"order_id": tracked_order.exchange_order_id}

        url = web_utils.rest_url(CONSTANTS.ORDER_CANCEL_PATH_URL, self._domain)
        response = await self._api_post(
            path_url=url,
            data=cancel_data,
            is_auth_required=True,
            limit_id="PRIVATE_ENDPOINTS"
        )

        # Gemini returns final order state immediately
        return response.get("is_cancelled", False)

    # ========== Order Status and Updates ==========

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        """Get order status from Gemini."""
        order_data = {"order_id": tracked_order.exchange_order_id}

        url = web_utils.rest_url(CONSTANTS.ORDER_STATUS_PATH_URL, self._domain)
        response = await self._api_post(
            path_url=url,
            data=order_data,
            is_auth_required=True,
            limit_id="PRIVATE_ENDPOINTS"
        )

        # Parse order state from response flags
        new_state = utils.parse_order_status(response)

        return OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=response.get("timestampms", 0) / 1000.0,
            new_state=new_state,
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=str(response["order_id"])
        )

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        """Get all fills for an order."""
        symbol = web_utils.convert_to_exchange_symbol(order.trading_pair)

        trade_data = {
            "symbol": symbol,
            "limit_trades": 500  # Max per request
        }

        url = web_utils.rest_url(CONSTANTS.MY_TRADES_PATH_URL, self._domain)
        response = await self._api_post(
            path_url=url,
            data=trade_data,
            is_auth_required=True,
            limit_id="PRIVATE_ENDPOINTS"
        )

        # Filter trades for this specific order
        trade_updates = []
        for trade in response:
            if str(trade.get("order_id")) != str(order.exchange_order_id):
                continue

            # Determine if maker or taker
            is_maker = not trade.get("aggressor", True)  # aggressor=True means taker

            trade_update = TradeUpdate(
                trade_id=str(trade["tid"]),
                client_order_id=order.client_order_id,
                exchange_order_id=str(trade["order_id"]),
                trading_pair=order.trading_pair,
                fill_timestamp=trade.get("timestampms", 0) / 1000.0,
                fill_price=Decimal(trade["price"]),
                fill_base_amount=Decimal(trade["amount"]),
                fill_quote_amount=Decimal(trade["price"]) * Decimal(trade["amount"]),
                fee=TradeFeeBase(
                    amount=Decimal(trade.get("fee_amount", "0")),
                    flat_fees=[],
                    percent=Decimal("0")
                ),
                is_maker=is_maker
            )

            trade_updates.append(trade_update)

        return trade_updates

    # ========== Balance and Trading Rules ==========

    async def _update_balances(self):
        """Fetch account balances."""
        url = web_utils.rest_url(CONSTANTS.BALANCES_PATH_URL, self._domain)
        response = await self._api_post(
            path_url=url,
            data={},
            is_auth_required=True,
            limit_id="PRIVATE_ENDPOINTS"
        )

        balances = {}
        for balance_entry in response:
            if balance_entry.get("type") != "exchange":
                continue  # Skip non-spot balances

            currency = balance_entry["currency"]
            balances[currency] = {
                "total": Decimal(balance_entry["amount"]),
                "available": Decimal(balance_entry["available"])
            }

        self._account_balances = {k: v["total"] for k, v in balances.items()}
        self._account_available_balances = {k: v["available"] for k, v in balances.items()}

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        """Parse trading rules from symbol details."""
        symbols = exchange_info_dict  # Should be array of symbols

        trading_rules = []
        for symbol in symbols:
            # Get detailed info for each symbol
            url = web_utils.rest_url(
                f"{CONSTANTS.SYMBOL_DETAILS_PATH_URL}/{symbol}",
                self._domain
            )
            details = await self._api_get(path_url=url, limit_id="PUBLIC_ENDPOINTS")

            # Filter by product_type == "spot"
            if not utils.is_spot_symbol(details):
                continue

            if details.get("status") != "open":
                continue  # Skip closed markets

            trading_pair = web_utils.convert_from_exchange_symbol(symbol)
            if not trading_pair:
                continue

            trading_rule = TradingRule(
                trading_pair=trading_pair,
                min_order_size=Decimal(details["min_order_size"]),
                min_price_increment=Decimal(str(details["tick_size"])),
                min_base_amount_increment=Decimal(str(details.get("quote_increment", details["tick_size"]))),
                max_order_size=Decimal("1000000")  # Gemini doesn't publish max
            )

            trading_rules.append(trading_rule)

        return trading_rules

    # ========== Fee Handling ==========

    def _get_fee(
        self,
        base_currency: str,
        quote_currency: str,
        order_type: OrderType,
        order_side: TradeType,
        amount: Decimal,
        price: Decimal = s_decimal_NaN,
        is_maker: Optional[bool] = None
    ) -> TradeFeeBase:
        """
        Get trading fee.

        Gemini default fees:
        - Maker: 0.25%
        - Taker: 0.35%
        """
        is_maker = is_maker or (order_type == OrderType.LIMIT_MAKER)
        fee_percent = Decimal(str(CONSTANTS.DEFAULT_MAKER_FEE)) if is_maker else Decimal(str(CONSTANTS.DEFAULT_TAKER_FEE))

        return DeductedFromReturnsTradeFee(percent=fee_percent)

    async def _update_trading_fees(self):
        """
        Update trading fees from API.

        Gemini doesn't have a dedicated fee endpoint.
        Fee tier is determined by 30-day volume.
        Using default fees.
        """
        pass  # Use default fees

    # ========== User Stream Event Listener ==========

    async def _user_stream_event_listener(self):
        """Listen to user stream and process events."""
        async for event_message in self._iter_user_event_queue():
            try:
                # Event already parsed by user stream data source
                if isinstance(event_message, OrderUpdate):
                    self._order_tracker.process_order_update(event_message)
                elif isinstance(event_message, TradeUpdate):
                    self._order_tracker.process_trade_update(event_message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error in user stream listener")

    # ========== Symbol Initialization ==========

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        """Build trading pair symbol map from exchange info."""
        symbols = exchange_info  # Should be array of symbols: ["btcusd", "ethbtc", ...]

        self._trading_pair_symbol_map = {}
        for symbol in symbols:
            trading_pair = web_utils.convert_from_exchange_symbol(symbol)
            if trading_pair:
                self._trading_pair_symbol_map[trading_pair] = symbol
