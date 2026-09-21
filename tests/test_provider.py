import io
import json
import unittest
import urllib.error
from decimal import Decimal

from jev_second_brain.policy import BudgetLimits, PolicyError
from jev_second_brain.provider import ProviderError, VercelJevProvider, validate_answers


QUESTIONS = {
    "present": {"type": "boolean", "instructions": "Is a garden mentioned?"},
    "relation": {"type": "choice", "instructions": "Relationship?", "criteria": {"same": "same", "other": "other"}},
    "rank": {"type": "score", "instructions": "Relevance?", "criteria": ["low", "medium", "high"]},
}


def payload(*, zdr=True, cost="0.000002"):
    routing = {"originalModelId": "typesafe-ai/jev", "resolvedProvider": "typesafe-ai",
               "finalProvider": "typesafe-ai"}
    if zdr:
        routing["planningReasoning"] = "ZDR requested: ZDR execution order: typesafe-ai"
    return {
        "model": "typesafe-ai/jev",
        "answers": {
            "present": {"type": "boolean", "probability": .98},
            "relation": {"type": "choice", "choice": "same", "probabilities": {"same": .8, "other": .2}},
            "rank": {"type": "score", "score": 1.75, "probabilities": {"0": 0, "1": .25, "2": .75}},
        },
        "usage": {"inputTokens": 190, "outputTokens": 12},
        "providerMetadata": {"gateway": {"routing": routing, "cost": cost, "generationId": "gen_test"}},
    }


class FakeResponse:
    def __init__(self, value):
        self._body = io.BytesIO(json.dumps(value).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, amount):
        return self._body.read(amount)


class ProviderTest(unittest.TestCase):
    def test_valid_typed_answers_and_metadata(self):
        seen = []

        def opener(request, *, timeout):
            seen.append((request, timeout))
            return FakeResponse(payload())

        provider = VercelJevProvider(opener=opener, env={"AI_GATEWAY_API_KEY": "synthetic-key"})
        result = provider.evaluate("Synthetic garden note", QUESTIONS, private=False)
        self.assertEqual(result.answers["relation"]["choice"], "same")
        self.assertEqual(result.cost_usd, Decimal("0.000002"))
        self.assertEqual(result.input_tokens, 190)
        self.assertEqual(result.routing["finalProvider"], "typesafe-ai")
        self.assertEqual(provider.budget.requests, 1)
        request, timeout = seen[0]
        self.assertEqual(request.full_url, "https://ai-gateway.vercel.sh/v1/evaluate")
        self.assertEqual(timeout, 15.0)
        body = json.loads(request.data)
        self.assertEqual(body["providerOptions"], {"gateway": {"zeroDataRetention": True,
                                                                  "only": ["typesafe-ai"]}})
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-key")

    def test_private_call_waits_for_synthetic_canary(self):
        states = []

        def opener(request, *, timeout):
            states.append(json.loads(request.data)["state"])
            result = payload()
            result["answers"] = {"canary": {"type": "boolean", "probability": .9}} if len(states) == 1 else result["answers"]
            return FakeResponse(result)

        provider = VercelJevProvider(opener=opener, env={"AI_GATEWAY_API_KEY": "key"})
        with self.assertRaises(PolicyError):
            provider.evaluate("private note", QUESTIONS, private=True)
        self.assertEqual(states, [])
        provider.verify_private_route()
        self.assertTrue(provider.private_route_verified)
        provider.evaluate("private note", QUESTIONS, private=True)
        self.assertIn("Synthetic canary", states[0])
        self.assertEqual(states[1], "private note")

    def test_missing_zdr_receipt_never_unblocks_private_data(self):
        def opener(request, *, timeout):
            value = payload(zdr=False)
            value["answers"] = {"canary": {"type": "boolean", "probability": .9}}
            return FakeResponse(value)

        provider = VercelJevProvider(opener=opener, env={"AI_GATEWAY_API_KEY": "key"})
        with self.assertRaisesRegex(PolicyError, "ZDR"):
            provider.verify_private_route()
        self.assertFalse(provider.private_route_verified)

    def test_retry_after_and_each_attempt_counted(self):
        calls, sleeps = [], []

        def opener(request, *, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "limited", {"Retry-After": "2"}, None)
            return FakeResponse(payload())

        provider = VercelJevProvider(opener=opener, sleep=sleeps.append,
                                    env={"AI_GATEWAY_API_KEY": "key"})
        provider.evaluate("synthetic", QUESTIONS, private=False)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(provider.budget.requests, 2)

    def test_payment_error_is_not_retried_or_disclosed(self):
        calls = []

        def opener(request, *, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(request.full_url, 402, "private data in server error", {}, None)

        provider = VercelJevProvider(opener=opener, env={"AI_GATEWAY_API_KEY": "key"})
        with self.assertRaisesRegex(ProviderError, "HTTP 402") as raised:
            provider.evaluate("secret text", QUESTIONS, private=False)
        self.assertEqual(calls, [1])
        self.assertNotIn("secret", str(raised.exception))

    def test_answer_type_distribution_and_score_are_validated(self):
        answer = payload()["answers"]
        answer["relation"]["choice"] = "other"
        with self.assertRaisesRegex(ProviderError, "highest-probability"):
            validate_answers(answer, QUESTIONS)
        answer["relation"]["choice"] = "same"
        answer["rank"]["score"] = .1
        with self.assertRaisesRegex(ProviderError, "inconsistent"):
            validate_answers(answer, QUESTIONS)

    def test_request_limit_prevents_second_network_call(self):
        calls = []

        def opener(request, *, timeout):
            calls.append(1)
            return FakeResponse(payload())

        provider = VercelJevProvider(limits=BudgetLimits(max_requests=1), opener=opener,
                                    env={"AI_GATEWAY_API_KEY": "key"})
        provider.evaluate("synthetic", QUESTIONS, private=False)
        with self.assertRaisesRegex(PolicyError, "request count"):
            provider.evaluate("synthetic", QUESTIONS, private=False)
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
