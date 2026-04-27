from typing import Dict, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType


class GeminiOrderBook(OrderBook):
    """Order book implementation for Gemini."""

    @classmethod
    def snapshot_message_from_exchange(
        cls,
        msg: Dict[str, any],
        timestamp: float,
        metadata: Optional[Dict] = None
    ) -> OrderBookMessage:
        """
        Creates a snapshot message from REST /v1/book/{symbol} response.

        Gemini format:
        {
          "bids": [
            {"price": "45000.00", "amount": "0.5", "timestamp": "1714052400"},
            ...
          ],
          "asks": [
            {"price": "45001.00", "amount": "0.75", "timestamp": "1714052401"},
            ...
          ]
        }

        :param msg: the REST response from the exchange
        :param timestamp: the snapshot timestamp
        :param metadata: extra information to add (e.g., trading_pair)
        :return: snapshot message
        """
        if metadata:
            msg.update(metadata)

        # Parse bids - each is a dict with price, amount, timestamp
        bids = [
            (float(bid["price"]), float(bid["amount"]))
            for bid in msg.get("bids", [])
        ]

        # Parse asks - each is a dict with price, amount, timestamp
        asks = [
            (float(ask["price"]), float(ask["amount"]))
            for ask in msg.get("asks", [])
        ]

        return OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            {
                "trading_pair": msg["trading_pair"],
                "update_id": int(timestamp * 1000),  # Use timestamp as update_id
                "bids": bids,
                "asks": asks
            },
            timestamp=timestamp
        )

    @classmethod
    def diff_message_from_exchange(
        cls,
        msg: Dict[str, any],
        timestamp: Optional[float] = None,
        metadata: Optional[Dict] = None
    ) -> OrderBookMessage:
        """
        Creates a diff message from WebSocket L2 updates.

        Gemini format:
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

        :param msg: the WebSocket update message
        :param timestamp: the update timestamp
        :param metadata: extra information to add
        :return: diff message
        """
        if metadata:
            msg.update(metadata)

        # Use timestampms for higher precision, fall back to timestamp
        timestamp_ms = msg.get("timestampms", msg.get("timestamp"))
        if timestamp is None and timestamp_ms:
            timestamp = timestamp_ms / 1000.0

        return OrderBookMessage(
            OrderBookMessageType.DIFF,
            {
                "trading_pair": msg["trading_pair"],
                "update_id": timestamp_ms or int(timestamp * 1000),
                "bids": msg.get("bids", []),
                "asks": msg.get("asks", [])
            },
            timestamp=timestamp
        )

    @classmethod
    def trade_message_from_exchange(
        cls,
        msg: Dict[str, any],
        metadata: Optional[Dict] = None
    ) -> OrderBookMessage:
        """
        Creates a trade message from WebSocket trade event.

        Gemini format (in l2_updates.trades array):
        {
          "type": "trade",
          "symbol": "BTCUSD",
          "eventId": 169841458,
          "timestamp": 1560976400428,
          "price": "45000.50",
          "quantity": "0.01",
          "side": "sell"
        }

        :param msg: the trade event details
        :param metadata: extra information to add
        :return: trade message
        """
        if metadata:
            msg.update(metadata)

        timestamp_ms = msg["timestamp"]
        trade_type = TradeType.SELL if msg["side"] == "sell" else TradeType.BUY

        return OrderBookMessage(
            OrderBookMessageType.TRADE,
            {
                "trading_pair": msg["trading_pair"],
                "trade_type": float(trade_type.value),
                "trade_id": str(msg["eventId"]),
                "update_id": timestamp_ms,
                "price": float(msg["price"]),
                "amount": float(msg["quantity"])
            },
            timestamp=timestamp_ms / 1000.0
        )
