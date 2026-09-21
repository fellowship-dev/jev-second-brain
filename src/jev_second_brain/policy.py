"""Local limits and privacy gates for outbound evaluation requests.

The gateway enforces its own retention policy.  This module prevents private
requests until a synthetic canary has produced route evidence, and bounds this
process's use of that route.  Limits apply to one provider instance/run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


class PolicyError(RuntimeError):
    """A request cannot be made within the selected privacy or spend policy."""


def _money(value: Decimal | str | int) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("cost limit must be a finite nonnegative amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("cost limit must be a finite nonnegative amount")
    return amount


@dataclass(frozen=True)
class BudgetLimits:
    """Per-run local ceilings; a gateway/team billing cap is still advisable.

    ``input_price_ceiling_per_million`` must be at least the current model price.
    A preflight charge reserves one token per UTF-8 byte, a deliberately generous
    upper bound for the supported text request, before each network attempt.
    Reported gateway cost is checked after successful responses.
    """

    max_requests: int = 100
    max_request_bytes: int = 32_000
    max_input_tokens: int = 1_000_000
    max_cost_usd: Decimal = Decimal("1")
    input_price_ceiling_per_million: Decimal = Decimal("1")
    max_retries: int = 2
    max_retry_delay_seconds: float = 15.0
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        for name in ("max_requests", "max_request_bytes", "max_input_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 4:
            raise ValueError("max_retries must be between zero and four")
        if not 0 <= self.max_retry_delay_seconds <= 60 or not 0 < self.timeout_seconds <= 60:
            raise ValueError("retry delay and timeout must be finite and bounded")
        object.__setattr__(self, "max_cost_usd", _money(self.max_cost_usd))
        price = _money(self.input_price_ceiling_per_million)
        if price == 0:
            raise ValueError("input price ceiling must be positive")
        object.__setattr__(self, "input_price_ceiling_per_million", price)


@dataclass
class BudgetMeter:
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    requests: int = 0
    request_bytes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    _reserved_input_tokens: int = 0
    _reserved_cost_usd: Decimal = Decimal("0")

    def reserve_attempt(self, byte_count: int) -> None:
        """Charge every HTTP attempt before I/O, including failed retries."""
        if type(byte_count) is not int or byte_count <= 0:
            raise PolicyError("empty or invalid request")
        limits = self.limits
        estimated_cost = Decimal(byte_count) * limits.input_price_ceiling_per_million / 1_000_000
        if byte_count > limits.max_request_bytes:
            raise PolicyError("request byte limit exceeded")
        if self.requests + 1 > limits.max_requests:
            raise PolicyError("request count limit exceeded")
        if self._reserved_input_tokens + byte_count > limits.max_input_tokens:
            raise PolicyError("input token reserve exceeded")
        if self._reserved_cost_usd + estimated_cost > limits.max_cost_usd:
            raise PolicyError("cost reserve exceeded")
        self.requests += 1
        self.request_bytes += byte_count
        self._reserved_input_tokens += byte_count
        self._reserved_cost_usd += estimated_cost

    def record_response(self, input_tokens: int, output_tokens: int, cost_usd: Decimal) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost_usd
        if self.input_tokens > self.limits.max_input_tokens or self.cost_usd > self.limits.max_cost_usd:
            raise PolicyError("provider reported usage above the configured budget")


def require_private_route(verified: bool) -> None:
    if not verified:
        raise PolicyError("private evaluation requires a verified synthetic ZDR route")


def validate_gateway_route(provider_metadata: Any, *, require_zdr_evidence: bool = False) -> dict[str, Any]:
    """Require TypeSafe routing and, for the canary, explicit ZDR evidence.

    Vercel's documented audit field is ``routing.planningReasoning``.  Missing
    route or ZDR evidence is an abstention, not a guess that the option worked.
    """
    if not isinstance(provider_metadata, dict):
        raise PolicyError("gateway routing metadata missing")
    gateway = provider_metadata.get("gateway")
    if not isinstance(gateway, dict) or not isinstance(gateway.get("routing"), dict):
        raise PolicyError("gateway routing metadata missing")
    routing = gateway["routing"]
    if routing.get("finalProvider") != "typesafe-ai" or routing.get("resolvedProvider") != "typesafe-ai":
        raise PolicyError("evaluation did not route exclusively to TypeSafe")
    if routing.get("originalModelId") != "typesafe-ai/jev":
        raise PolicyError("evaluation model changed in routing")
    if require_zdr_evidence:
        reason = routing.get("planningReasoning", "")
        explicit = gateway.get("zeroDataRetention") is True
        if not explicit and (not isinstance(reason, str) or "zdr" not in reason.casefold()):
            raise PolicyError("gateway did not confirm ZDR routing")
    return routing
