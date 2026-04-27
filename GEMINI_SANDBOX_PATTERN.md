# Gemini Sandbox Implementation Pattern

Based on how other Hummingbot exchanges implement testnet/sandbox support (e.g., Bybit), here's the recommended pattern for Gemini:

## Implementation Pattern

### 1. Constants File (`gemini_constants.py`)

```python
from hummingbot.core.api_throttler.data_types import RateLimit

# Domain configuration
DEFAULT_DOMAIN = "gemini_main"

# Base URLs (domain-specific)
REST_URLS = {
    "gemini_main": "https://api.gemini.com",
    "gemini_sandbox": "https://api.sandbox.gemini.com"
}

WSS_URLS = {
    "gemini_main": "wss://api.gemini.com",
    "gemini_sandbox": "wss://api.sandbox.gemini.com"
}

# Order ID configuration
HBOT_ORDER_ID_PREFIX = "HBOT-GEMINI-"
MAX_ORDER_ID_LEN = 32

# Rate Limits (same for both domains)
REQUEST_WEIGHT = "REQUEST_WEIGHT"
ONE_MINUTE = 60

RATE_LIMITS = [
    RateLimit(
        limit_id=REQUEST_WEIGHT,
        limit=120,  # 120 requests per minute
        time_interval=ONE_MINUTE
    ),
]
```

### 2. Web Utils (`gemini_web_utils.py`)

```python
from typing import Optional
from hummingbot.connector.exchange.gemini import gemini_constants as CONSTANTS

def get_rest_url_for_endpoint(endpoint: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """Build REST URL for given endpoint and domain."""
    base_url = CONSTANTS.REST_URLS[domain]
    return f"{base_url}{endpoint}"

def get_wss_url(domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    """Get WebSocket URL for given domain."""
    return CONSTANTS.WSS_URLS[domain]
```

### 3. Exchange Class (`gemini_exchange.py`)

```python
class GeminiExchange(ExchangePyBase):
    def __init__(
        self,
        client_config_map: "ClientConfigMap",
        gemini_api_key: str,
        gemini_api_secret: str,
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,  # <-- Domain parameter
    ):
        self._domain = domain
        super().__init__(client_config_map)
        # ... rest of init

    @property
    def domain(self) -> str:
        return self._domain
```

### 4. Configuration File (`conf/connectors/gemini.yml`)

```yaml
# Gemini Exchange Connector Configuration

# API Credentials
gemini_api_key: ""
gemini_api_secret: ""

# Domain Selection
# Options: "gemini_main" (production), "gemini_sandbox" (testing)
gemini_domain: "gemini_main"
```

### 5. Usage Examples

#### Production Trading
```yaml
# conf/strategies/my_strategy.yml
exchange: gemini
gemini_domain: "gemini_main"  # Use production
market: BTC-USD
```

#### Sandbox Testing
```yaml
# conf/strategies/test_strategy.yml
exchange: gemini
gemini_domain: "gemini_sandbox"  # Use sandbox
market: BTC-USD
```

#### Environment Variables (for CI/CD)
```bash
# Production
export GEMINI_DOMAIN="gemini_main"
export GEMINI_API_KEY="production_key"
export GEMINI_API_SECRET="production_secret"

# Sandbox
export GEMINI_DOMAIN="gemini_sandbox"
export GEMINI_API_KEY="sandbox_key"
export GEMINI_API_SECRET="sandbox_secret"
```

## Benefits

1. **Easy Switching:** Users can switch between production and sandbox by changing one config value
2. **Safe Testing:** Test strategies with fake money before going live
3. **CI/CD Friendly:** Automated tests can run against sandbox without risk
4. **Standard Pattern:** Matches how 7+ other Hummingbot exchanges work (Bybit, Hyperliquid, etc.)
5. **No Code Duplication:** Same connector code works for both domains

## Testing Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                   Development Workflow                       │
└─────────────────────────────────────────────────────────────┘

1. Write Code
   ↓
2. Unit Tests (mocked, no real API)
   ↓
3. Sandbox Integration Tests (gemini_sandbox domain)
   ├─ Test with fake money
   ├─ Verify order placement
   ├─ Test WebSocket streams
   └─ Validate strategies
   ↓
4. Production Validation (gemini_main domain)
   ├─ Small order sizes
   ├─ Limited capital
   └─ Monitor closely
   ↓
5. Full Production Deployment
```

## Gemini Sandbox Details

### Sandbox API
- **REST URL:** `https://api.sandbox.gemini.com`
- **WebSocket URL:** `wss://api.sandbox.gemini.com`
- **Documentation:** https://docs.sandbox.gemini.com/

### Key Differences from Production
- Separate API keys (create in sandbox account)
- Fake balances and orders
- Same API endpoints and behavior as production
- May have slightly different rate limits (usually more lenient)

### Getting Sandbox Access
1. Go to https://exchange.sandbox.gemini.com/
2. Create sandbox account (separate from production)
3. Generate sandbox API keys
4. Use these keys with `gemini_domain: "gemini_sandbox"`

## Implementation Checklist

- [ ] Add domain parameter to `GeminiExchange.__init__()`
- [ ] Update `gemini_constants.py` with domain-based URL dictionaries
- [ ] Modify `gemini_web_utils.py` to use domain-based URLs
- [ ] Update `gemini_auth.py` to pass domain parameter
- [ ] Add domain configuration to `conf/connectors/gemini.yml`
- [ ] Update tests to support both domains
- [ ] Document sandbox setup in user guide
- [ ] Test both domains in CI/CD pipeline

## Alternative: Single Domain Implementation

If you want to simplify for the initial release, you could:

**Option A: Sandbox Only (for initial development)**
```python
# gemini_constants.py
REST_URL = "https://api.sandbox.gemini.com"
WSS_URL = "wss://api.sandbox.gemini.com"
```

**Option B: Production Only (skip sandbox initially)**
```python
# gemini_constants.py
REST_URL = "https://api.gemini.com"
WSS_URL = "wss://api.gemini.com"
```

Then add multi-domain support in a follow-up PR after initial release.

## Recommendation

**Implement multi-domain support from the start** because:
1. ✅ Only ~10-15 lines of code difference
2. ✅ Enables safe testing for users and developers
3. ✅ Matches existing Hummingbot patterns (7+ exchanges already do this)
4. ✅ PR #8027 likely already has most of this (needs verification)
5. ✅ Prevents need for breaking changes later

It's much easier to include domain support now than to add it later as a breaking change!
