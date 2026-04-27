import asyncio
from decimal import Decimal
from typing import Optional

import hummingbot.connector.exchange.gemini.gemini_constants as CONSTANTS
import hummingbot.connector.exchange.gemini.gemini_web_utils as web_utils
from hummingbot.connector.exchange.gemini.gemini_auth import GeminiAuth
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.data_type.in_flight_order import OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.trade_fee import TradeFee, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import WSRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger


class GeminiAPIUserStreamDataSource(UserStreamTrackerDataSource):
    """
    User stream data source for Gemini Order Events WebSocket.

    CRITICAL: Authentication must happen during WebSocket handshake.
    Gemini does NOT support post-connection authentication.

    Events received:
    - subscription_ack: Subscription confirmation
    - heartbeat: Connection keep-alive (every 5 seconds)
    - initial: Snapshot of existing orders
    - accepted, booked, fill, cancelled, etc.: Order updates
    """

    HEARTBEAT_TIME_INTERVAL = 30.0
    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        auth: GeminiAuth,
        domain: str,
        api_factory: WebAssistantsFactory,
        throttler: Optional[AsyncThrottler] = None
    ):
        super().__init__()
        self._auth = auth
        self._domain = domain
        self._api_factory = api_factory
        self._throttler = throttler or web_utils.create_throttler()
        self._last_recv_time = 0

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = HummingbotLogger.logger_name_for_class(cls)
        return cls._logger

    async def _connected_websocket_assistant(self) -> WSAssistant:
        """
        Creates authenticated WebSocket connection.

        CRITICAL IMPLEMENTATION:
        Gemini requires auth headers in initial handshake.
        Cannot send auth message after connection.

        WebSocket URL: wss://ws.gemini.com (NOT wss://api.gemini.com/v1/order/events)
        Auth payload 'request' field: "/v1/order/events" (used in signature, not URL)
        """
        ws = await self._api_factory.get_ws_assistant()
        ws_url = web_utils.wss_url(self._domain)

        # Generate authentication request BEFORE connection
        auth_request = WSRequest()
        auth_request = await self._auth.ws_authenticate(auth_request)

        # Connect with auth headers in handshake
        await ws.connect(ws_url, ws_request=auth_request, ping_timeout=CONSTANTS.WS_HEARTBEAT_INTERVAL)

        return ws

    async def _process_order_update(self, event_data: dict, output: asyncio.Queue):
        """
        Processes order event into OrderUpdate.

        Event format varies by type, but common fields:
        {
          "type": "fill",
          "order_id": "109535955",
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
          "client_order_id": "my-order-123",
          "fill": {  # Only present on fill events
            "trade_id": "109535970",
            "liquidity": "Maker",
            "price": "3592.23",
            "amount": "1",
            "fee": "8.980575",
            "fee_currency": "USD"
          }
        }
        """
        event_type = event_data.get("type")
        order_id = str(event_data.get("order_id", ""))
        symbol = event_data.get("symbol", "")
        trading_pair = web_utils.convert_from_exchange_symbol(symbol)
        timestamp = event_data.get("timestampms", 0) / 1000.0

        # Determine order state
        new_state = CONSTANTS.ORDER_STATE.get(event_type, OrderState.OPEN)

        # For fill events, check if completely filled
        if event_type == CONSTANTS.WS_ORDER_EVENT_FILL:
            remaining = Decimal(str(event_data.get("remaining_amount", "0")))
            if remaining == Decimal("0"):
                new_state = OrderState.FILLED
            else:
                new_state = OrderState.PARTIALLY_FILLED

        # Create order update
        order_update = OrderUpdate(
            trading_pair=trading_pair,
            update_timestamp=timestamp,
            new_state=new_state,
            client_order_id=event_data.get("client_order_id"),
            exchange_order_id=order_id
        )

        output.put_nowait(order_update)

        # If fill event, also create trade update
        if event_type == CONSTANTS.WS_ORDER_EVENT_FILL and "fill" in event_data:
            fill_data = event_data["fill"]

            # Determine if maker or taker
            is_maker = (fill_data.get("liquidity") == "Maker")

            trade_update = TradeUpdate(
                trade_id=str(fill_data.get("trade_id", "")),
                client_order_id=event_data.get("client_order_id"),
                exchange_order_id=order_id,
                trading_pair=trading_pair,
                fill_timestamp=timestamp,
                fill_price=Decimal(fill_data.get("price", "0")),
                fill_base_amount=Decimal(fill_data.get("amount", "0")),
                fill_quote_amount=Decimal(fill_data.get("price", "0")) * Decimal(fill_data.get("amount", "0")),
                fee=TradeFee(
                    amount=Decimal(fill_data.get("fee", "0")),
                    flat_fees=[],
                    percent=Decimal("0")
                ),
                is_maker=is_maker
            )

            output.put_nowait(trade_update)

    async def listen_for_user_stream(self, output: asyncio.Queue):
        """Main listener for user stream events."""
        ws = None
        while True:
            try:
                ws = await self._connected_websocket_assistant()
                self._last_recv_time = self._time()

                # No explicit subscription needed - auth grants access

                async for ws_response in ws.iter_messages():
                    data = ws_response.data
                    event_type = data.get("type")

                    if event_type == CONSTANTS.WS_ORDER_EVENT_HEARTBEAT:
                        # Heartbeat - connection alive
                        self._last_recv_time = self._time()
                        continue

                    elif event_type == CONSTANTS.WS_ORDER_EVENT_SUBSCRIPTION_ACK:
                        # Subscription acknowledged
                        self.logger().info("Gemini order events subscription confirmed")
                        continue

                    elif event_type in [
                        CONSTANTS.WS_ORDER_EVENT_INITIAL,
                        CONSTANTS.WS_ORDER_EVENT_ACCEPTED,
                        CONSTANTS.WS_ORDER_EVENT_BOOKED,
                        CONSTANTS.WS_ORDER_EVENT_FILL,
                        CONSTANTS.WS_ORDER_EVENT_CANCELLED,
                        CONSTANTS.WS_ORDER_EVENT_CLOSED,
                        CONSTANTS.WS_ORDER_EVENT_REJECTED,
                        CONSTANTS.WS_ORDER_EVENT_CANCEL_REJECTED
                    ]:
                        # Order state changes
                        await self._process_order_update(data, output)

                    self._last_recv_time = self._time()

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error(
                    "Error in user stream WebSocket. Retrying in 5s...",
                    exc_info=True
                )
                await self._sleep(5.0)
            finally:
                ws and await ws.disconnect()
