import asyncio
import base64
import hashlib
import hmac
import json
from typing import Any, Dict

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class GeminiAuth(AuthBase):
    """
    Gemini authentication using HMAC-SHA384.

    Critical differences from other exchanges:
    1. Uses SHA384 (not SHA256/SHA512)
    2. Nonce in seconds (not milliseconds)
    3. Payload is base64-encoded JSON
    4. Signature computed on base64 payload (not raw JSON)
    5. WebSocket must auth during handshake (cannot post-auth)
    """

    def __init__(self, api_key: str, secret_key: str, time_provider: TimeSynchronizer):
        """
        Initialize Gemini authenticator.

        :param api_key: Gemini API key
        :param secret_key: Gemini API secret
        :param time_provider: TimeSynchronizer for accurate timestamps
        """
        self._api_key = api_key
        self._secret_key = secret_key
        self._time_provider = time_provider
        self._last_nonce = 0
        self._nonce_lock = asyncio.Lock()

    async def _get_nonce(self) -> int:
        """
        Generates monotonic nonce in seconds.

        Gemini requirements:
        - Nonce must be in seconds (not milliseconds)
        - Nonce must be strictly increasing per API key
        - Nonce must be within ±30 seconds of server time

        :return: monotonic nonce in seconds
        """
        async with self._nonce_lock:
            # Get current time in seconds (not milliseconds)
            current_time = int(self._time_provider.time())

            # Ensure monotonic increase
            if current_time <= self._last_nonce:
                nonce = self._last_nonce + 1
            else:
                nonce = current_time

            self._last_nonce = nonce
            return nonce

    def _generate_signature(self, b64_payload: str) -> str:
        """
        Generates HMAC-SHA384 signature.

        Critical: Signature is computed on the base64-encoded payload,
        not the raw JSON string.

        :param b64_payload: base64-encoded payload string
        :return: hex-encoded HMAC-SHA384 signature
        """
        signature = hmac.new(
            self._secret_key.encode(),
            b64_payload.encode(),
            hashlib.sha384
        ).hexdigest()
        return signature

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Adds Gemini authentication to REST request.

        Headers added:
        - X-GEMINI-APIKEY: API key
        - X-GEMINI-PAYLOAD: Base64-encoded JSON
        - X-GEMINI-SIGNATURE: Hex HMAC-SHA384 of payload
        - Content-Type: text/plain (Gemini requirement)

        :param request: the request to authenticate
        :return: authenticated request
        """
        nonce = await self._get_nonce()

        # Build payload dictionary
        # CRITICAL: Must include 'request' field with endpoint path
        payload_dict = {
            "request": request.url.path,  # e.g., "/v1/order/new"
            "nonce": nonce,
        }

        # Merge request data into payload
        if request.data:
            if isinstance(request.data, str):
                # Parse JSON string
                data_dict = json.loads(request.data)
            else:
                data_dict = request.data
            payload_dict.update(data_dict)

        # Convert to JSON and base64 encode
        payload_json = json.dumps(payload_dict)
        b64_payload = base64.b64encode(payload_json.encode()).decode()

        # Generate HMAC-SHA384 signature on base64 payload
        signature = self._generate_signature(b64_payload)

        # Set headers
        headers = request.headers or {}
        headers.update({
            "X-GEMINI-APIKEY": self._api_key,
            "X-GEMINI-PAYLOAD": b64_payload,
            "X-GEMINI-SIGNATURE": signature,
            "Content-Type": "text/plain"  # Gemini requires this
        })
        request.headers = headers

        # Clear request.data since everything is in the payload header
        request.data = None

        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        Generates WebSocket authentication for handshake.

        CRITICAL: Gemini requires authentication DURING initial handshake.
        Cannot authenticate after connection is established.

        :param request: the WebSocket request to authenticate
        :return: authenticated request with headers
        """
        nonce = await self._get_nonce()

        # WebSocket auth payload
        # The path "/v1/order/events" is used in the signature,
        # but the actual WebSocket URL is wss://ws.gemini.com
        payload_dict = {
            "request": "/v1/order/events",
            "nonce": nonce
        }

        payload_json = json.dumps(payload_dict)
        b64_payload = base64.b64encode(payload_json.encode()).decode()

        signature = self._generate_signature(b64_payload)

        # Add auth headers to WebSocket handshake
        headers = request.headers or {}
        headers.update({
            "X-GEMINI-APIKEY": self._api_key,
            "X-GEMINI-PAYLOAD": b64_payload,
            "X-GEMINI-SIGNATURE": signature
        })
        request.headers = headers

        return request
