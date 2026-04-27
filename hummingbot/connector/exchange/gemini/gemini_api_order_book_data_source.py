import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import hummingbot.connector.exchange.gemini.gemini_constants as CONSTANTS
import hummingbot.connector.exchange.gemini.gemini_web_utils as web_utils
from hummingbot.connector.exchange.gemini.gemini_order_book import GeminiOrderBook
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange.gemini.gemini_exchange import GeminiExchange


class GeminiAPIOrderBookDataSource(OrderBookTrackerDataSource):
    """
    Order book data source for Gemini Market Data v2 WebSocket.

    Connects to wss://api.gemini.com/v2/marketdata for:
    - Level 2 order book updates (l2_updates)
    - Trade events
    """

    HEARTBEAT_TIME_INTERVAL = 30.0
    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        trading_pairs: List[str],
        connector: 'GeminiExchange',
        domain: str,
        api_factory: WebAssistantsFactory,
        throttler: Optional[AsyncThrottler] = None
    ):
        super().__init__(trading_pairs)
        self._connector = connector
        self._domain = domain
        self._api_factory = api_factory
        self._throttler = throttler or web_utils.create_throttler()
        self._last_ws_message_time = 0

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = HummingbotLogger.logger_name_for_class(cls)
        return cls._logger

    @classmethod
    def trading_pair_symbol_map_ready(cls) -> bool:
        """Indicates if trading pair symbol map is ready."""
        return True

    async def get_last_traded_prices(
        self,
        trading_pairs: List[str],
        domain: Optional[str] = None
    ) -> Dict[str, float]:
        """Get last traded prices for trading pairs."""
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        """
        Fetches order book snapshot via REST.

        Endpoint: GET /v1/book/{symbol}
        Returns: {"bids": [[price, amount]], "asks": [[price, amount]]}
        """
        symbol = web_utils.convert_to_exchange_symbol(trading_pair)
        url = web_utils.rest_url(
            f"{CONSTANTS.ORDER_BOOK_PATH_URL}/{symbol}",
            self._domain
        )

        request = RESTRequest(
            method=RESTMethod.GET,
            url=url,
            throttler_limit_id="PUBLIC_ENDPOINTS"
        )

        rest_assistant = await self._api_factory.get_rest_assistant()
        response = await rest_assistant.call(request)

        if response.status != 200:
            raise IOError(f"Failed to fetch order book for {trading_pair}: {response.status}")

        data = await response.json()
        return data

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        """Gets order book snapshot and creates OrderBookMessage."""
        snapshot = await self._request_order_book_snapshot(trading_pair)
        snapshot["trading_pair"] = trading_pair
        snapshot_timestamp = self._time()

        snapshot_msg = GeminiOrderBook.snapshot_message_from_exchange(
            snapshot,
            snapshot_timestamp
        )
        return snapshot_msg

    async def _subscribe_channels(self, ws: WSAssistant):
        """
        Subscribes to L2 order book and trades for all trading pairs.

        Gemini subscription format:
        {
          "type": "subscribe",
          "subscriptions": [
            {"name": "l2", "symbols": ["BTCUSD", "ETHUSD"]}
          ]
        }
        """
        # Convert all trading pairs to exchange symbols (uppercase)
        symbols = [
            web_utils.convert_to_exchange_symbol(pair).upper()
            for pair in self._trading_pairs
        ]

        # Subscribe to L2 order book updates
        subscribe_payload = {
            "type": CONSTANTS.WS_MARKET_DATA_SUBSCRIPTION,
            "subscriptions": [
                {
                    "name": "l2",
                    "symbols": symbols
                }
            ]
        }

        subscribe_request = WSJSONRequest(payload=subscribe_payload)
        await ws.send(subscribe_request)

        self.logger().info(f"Subscribed to L2 order book for {len(symbols)} symbols")

    async def _parse_order_book_diff_message(
        self,
        raw_message: Dict[str, Any],
        message_queue: asyncio.Queue
    ):
        """
        Parses L2 update message.

        Message format:
        {
          "type": "l2_updates",
          "symbol": "BTCUSD",
          "changes": [
            ["buy", "45000.00", "0.5"],    # side, price, amount
            ["sell", "45001.00", "0"]       # amount 0 = remove level
          ],
          "timestamp": 1714052400000,
          "timestampms": 1714052400000
        }
        """
        if raw_message.get("type") != CONSTANTS.WS_MARKET_DATA_L2_UPDATES:
            return

        symbol = raw_message.get("symbol", "").lower()
        trading_pair = web_utils.convert_from_exchange_symbol(symbol)

        if not trading_pair or trading_pair not in self._trading_pairs:
            return

        changes = raw_message.get("changes", [])
        timestamp_ms = raw_message.get("timestampms", raw_message.get("timestamp"))
        timestamp = timestamp_ms / 1000.0 if timestamp_ms else self._time()

        # Separate bids and asks
        bids = []
        asks = []

        for change in changes:
            side, price, amount = change
            price_float = float(price)
            amount_float = float(amount)

            if side == "buy":
                bids.append((price_float, amount_float))
            elif side == "sell":
                asks.append((price_float, amount_float))

        # Create order book message
        order_book_message_content = {
            "trading_pair": trading_pair,
            "bids": bids,
            "asks": asks
        }

        order_book_message = GeminiOrderBook.diff_message_from_exchange(
            {**raw_message, **order_book_message_content},
            timestamp
        )

        message_queue.put_nowait(order_book_message)

    async def _parse_trade_message(
        self,
        raw_message: Dict[str, Any],
        message_queue: asyncio.Queue
    ):
        """
        Parses trade events from L2 updates.

        Trades are included in l2_updates message:
        {
          "type": "l2_updates",
          "symbol": "BTCUSD",
          "changes": [...],
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
          ]
        }
        """
        trades = raw_message.get("trades", [])

        for trade in trades:
            symbol = trade.get("symbol", "").lower()
            trading_pair = web_utils.convert_from_exchange_symbol(symbol)

            if not trading_pair or trading_pair not in self._trading_pairs:
                continue

            trade["trading_pair"] = trading_pair

            trade_message = GeminiOrderBook.trade_message_from_exchange(trade)
            message_queue.put_nowait(trade_message)

    async def listen_for_subscriptions(self):
        """Main WebSocket listener for market data."""
        ws = None
        while True:
            try:
                ws_url = web_utils.wss_market_data_url(self._domain)
                ws = await self._api_factory.get_ws_assistant()
                await ws.connect(ws_url, ping_timeout=CONSTANTS.WS_HEARTBEAT_INTERVAL)

                await self._subscribe_channels(ws)
                self._last_ws_message_time = self._time()

                async for ws_response in ws.iter_messages():
                    data = ws_response.data

                    msg_type = data.get("type")

                    if msg_type == CONSTANTS.WS_MARKET_DATA_L2_UPDATES:
                        # Order book updates and trades
                        await self._parse_order_book_diff_message(
                            data,
                            self._message_queue[data.get("symbol", "").lower()]
                        )
                        await self._parse_trade_message(
                            data,
                            self._message_queue[data.get("symbol", "").lower()]
                        )
                        self._last_ws_message_time = self._time()

                    elif msg_type == CONSTANTS.WS_MARKET_DATA_HEARTBEAT:
                        # Gemini heartbeat
                        self._last_ws_message_time = self._time()

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error(
                    "Unexpected error in order book WebSocket. Retrying in 5s...",
                    exc_info=True
                )
                await self._sleep(5.0)
            finally:
                ws and await ws.disconnect()

    async def listen_for_order_book_diffs(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        """Listens for order book diff events from message queue."""
        message_queue = self._message_queue
        while True:
            try:
                async for message in message_queue:
                    if isinstance(message, OrderBookMessage):
                        output.put_nowait(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error(
                    "Unexpected error listening for order book diffs.",
                    exc_info=True
                )
                await self._sleep(5.0)

    async def listen_for_trades(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        """Listens for trade events from message queue."""
        message_queue = self._message_queue
        while True:
            try:
                async for message in message_queue:
                    if isinstance(message, OrderBookMessage) and message.type == OrderBookMessageType.TRADE:
                        output.put_nowait(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error(
                    "Unexpected error listening for trades.",
                    exc_info=True
                )
                await self._sleep(5.0)

    async def listen_for_order_book_snapshots(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        """Periodically requests order book snapshots."""
        while True:
            try:
                for trading_pair in self._trading_pairs:
                    try:
                        snapshot_msg = await self._order_book_snapshot(trading_pair)
                        output.put_nowait(snapshot_msg)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        self.logger().error(
                            f"Error fetching snapshot for {trading_pair}.",
                            exc_info=True
                        )
                        await self._sleep(5.0)

                # Request snapshot every 60 seconds
                await self._sleep(60.0)

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error(
                    "Unexpected error in order book snapshot loop.",
                    exc_info=True
                )
                await self._sleep(5.0)
