"""Vercel AI Gateway Jev evaluation over its documented HTTP endpoint.

No vault content is logged.  Private calls require a successful synthetic ZDR
canary in the same provider instance; every request still carries the policy.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

from .policy import BudgetLimits, BudgetMeter, PolicyError, require_private_route, validate_gateway_route

GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/evaluate"
MODEL = "typesafe-ai/jev"
MAX_RESPONSE_BYTES = 256_000


class ProviderError(RuntimeError):
    """Transport, malformed response, or upstream status error without note text."""


@dataclass(frozen=True)
class EvaluationResult:
    model: str
    answers: dict[str, dict[str, Any]]
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    routing: dict[str, Any]
    generation_id: str | None


def _number(value: Any, *, minimum: float = 0, maximum: float = 1) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ProviderError("invalid numeric evaluation answer")
    return float(value)


def _distribution(value: Any, keys: set[str]) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProviderError("evaluation probabilities do not match criteria")
    probs = {key: _number(value[key]) for key in keys}
    if not .98 <= sum(probs.values()) <= 1.02:
        raise ProviderError("evaluation probabilities do not sum to one")
    return probs


def _validate_questions(questions: Mapping[str, Any]) -> None:
    if not isinstance(questions, dict) or not questions or len(questions) > 16:
        raise ValueError("questions must be a nonempty map of at most 16")
    for key, question in questions.items():
        if not isinstance(key, str) or not key or not isinstance(question, dict):
            raise ValueError("invalid question")
        kind = question.get("type")
        if kind not in ("boolean", "choice", "score"):
            raise ValueError("question type must be boolean, choice, or score")
        instructions = question.get("instructions")
        if not isinstance(instructions, (str, dict, list)) or not instructions:
            raise ValueError("question needs instructions")
        criteria = question.get("criteria")
        if kind == "choice":
            if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255:
                raise ValueError("choice needs 2 to 255 named criteria")
            if any(not isinstance(option, str) or not option for option in criteria):
                raise ValueError("choice criteria keys must be nonempty strings")
        elif kind == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 32:
                raise ValueError("score needs 2 to 32 ordered criteria")
        elif criteria is not None and (not isinstance(criteria, dict) or set(criteria) != {"true", "false"}):
            raise ValueError("boolean criteria must describe true and false")


def validate_answers(answers: Any, questions: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate all answer IDs and typed values against the sent rubric."""
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ProviderError("evaluation answer IDs do not match questions")
    clean: dict[str, dict[str, Any]] = {}
    for key, question in questions.items():
        answer = answers[key]
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise ProviderError("evaluation answer type mismatch")
        if kind == "boolean":
            _number(answer.get("probability"))
        elif kind == "choice":
            probs = _distribution(answer.get("probabilities"), set(question["criteria"]))
            choice = answer.get("choice")
            if choice not in probs or probs[choice] < max(probs.values()) - 1e-9:
                raise ProviderError("choice is not a highest-probability option")
        else:
            keys = {str(i) for i in range(len(question["criteria"]))}
            probs = _distribution(answer.get("probabilities"), keys)
            score = _number(answer.get("score"), maximum=len(keys) - 1)
            weighted = sum(int(level) * probability for level, probability in probs.items())
            if abs(score - weighted) > .05:
                raise ProviderError("score is inconsistent with its distribution")
            legend = answer.get("legend")
            if legend is not None and (not isinstance(legend, dict) or set(legend) != keys):
                raise ProviderError("score legend does not match criteria")
        if "confidence" in answer:
            _number(answer["confidence"])
        clean[key] = dict(answer)
    return clean


def _retry_after(headers: Any, max_delay: float) -> float | None:
    raw = headers.get("Retry-After") if headers else None
    if raw is None:
        return None
    try:
        delay = float(raw)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(raw)
            delay = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            return None
    if not math.isfinite(delay):
        return None
    if delay > max_delay:
        raise PolicyError("Retry-After exceeds the local retry delay limit")
    return max(0.0, delay)


class VercelJevProvider:
    """One bounded evaluation session. Key comes only from the environment."""

    def __init__(
        self,
        *,
        limits: BudgetLimits | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.budget = BudgetMeter(limits or BudgetLimits())
        self._opener = opener
        self._sleep = sleep
        self._env = env if env is not None else os.environ
        self._private_route_verified = False

    @property
    def private_route_verified(self) -> bool:
        return self._private_route_verified

    def verify_private_route(self) -> EvaluationResult:
        """Run a harmless canary and accept only explicit ZDR route evidence."""
        result = self._evaluate(
            state="Synthetic canary: the sun rose over the test garden.",
            questions={"canary": {"type": "boolean", "instructions": "Does the sentence mention a garden?"}},
            require_zdr_evidence=True,
        )
        self._private_route_verified = True
        return result

    def evaluate(self, state: Any, questions: dict[str, Any], *, private: bool = True) -> EvaluationResult:
        if private:
            require_private_route(self._private_route_verified)
        return self._evaluate(state=state, questions=questions)

    def _evaluate(self, *, state: Any, questions: dict[str, Any], require_zdr_evidence: bool = False) -> EvaluationResult:
        if not isinstance(state, (str, dict, list)) or not state:
            raise ValueError("state must be a nonempty string, object, or array")
        _validate_questions(questions)
        key = self._env.get("AI_GATEWAY_API_KEY", "")
        if not key:
            raise PolicyError("AI_GATEWAY_API_KEY is not configured")
        body = {
            "model": MODEL,
            "state": state,
            "questions": questions,
            "providerOptions": {"gateway": {"zeroDataRetention": True, "only": ["typesafe-ai"]}},
        }
        try:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("state and questions must be JSON values") from exc
        request = urllib.request.Request(
            GATEWAY_URL,
            data=encoded,
            method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        limits = self.budget.limits
        for attempt in range(limits.max_retries + 1):
            self.budget.reserve_attempt(len(encoded))
            try:
                with self._opener(request, timeout=limits.timeout_seconds) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ProviderError("evaluation response exceeded byte limit")
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ProviderError("invalid evaluation response JSON") from exc
                return self._parse_result(payload, questions, require_zdr_evidence=require_zdr_evidence)
            except urllib.error.HTTPError as exc:
                status = exc.code
                retryable = status == 429 or 500 <= status < 600
                if not retryable or attempt == limits.max_retries:
                    exc.close()
                    raise ProviderError(f"evaluation HTTP {status}") from None
                try:
                    delay = _retry_after(exc.headers, limits.max_retry_delay_seconds)
                finally:
                    exc.close()
                if delay is None:
                    delay = min(2 ** attempt, limits.max_retry_delay_seconds)
                self._sleep(delay)
            except urllib.error.URLError as exc:
                raise ProviderError("evaluation transport failed") from None
        raise AssertionError("unreachable")

    def _parse_result(self, payload: Any, questions: Mapping[str, Any], *, require_zdr_evidence: bool) -> EvaluationResult:
        if not isinstance(payload, dict) or payload.get("model") != MODEL:
            raise ProviderError("evaluation response model mismatch")
        answers = validate_answers(payload.get("answers"), questions)
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            raise ProviderError("evaluation usage missing")
        input_tokens = usage.get("inputTokens")
        output_tokens = usage.get("outputTokens")
        if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens)):
            raise ProviderError("evaluation usage invalid")
        metadata = payload.get("providerMetadata")
        routing = validate_gateway_route(metadata, require_zdr_evidence=require_zdr_evidence)
        gateway = metadata["gateway"]
        try:
            cost = Decimal(str(gateway["cost"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ProviderError("evaluation cost missing or invalid") from exc
        if not cost.is_finite() or cost < 0:
            raise ProviderError("evaluation cost missing or invalid")
        self.budget.record_response(input_tokens, output_tokens, cost)
        return EvaluationResult(
            model=payload["model"], answers=answers, input_tokens=input_tokens,
            output_tokens=output_tokens, cost_usd=cost, routing=dict(routing),
            generation_id=gateway.get("generationId") if isinstance(gateway.get("generationId"), str) else None,
        )
