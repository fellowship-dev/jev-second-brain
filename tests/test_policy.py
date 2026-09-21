import unittest
from decimal import Decimal

from jev_second_brain.policy import BudgetLimits, BudgetMeter, PolicyError, validate_gateway_route


class BudgetPolicyTest(unittest.TestCase):
    def test_each_attempt_reserves_a_conservative_token_and_cost_envelope(self):
        meter = BudgetMeter(BudgetLimits(max_requests=2, max_request_bytes=20, max_input_tokens=21,
                                         max_cost_usd=Decimal("0.000021")))
        meter.reserve_attempt(10)
        meter.reserve_attempt(10)
        self.assertEqual(meter.requests, 2)
        with self.assertRaises(PolicyError):
            meter.reserve_attempt(1)

    def test_over_budget_is_blocked_before_transport(self):
        meter = BudgetMeter(BudgetLimits(max_request_bytes=8, max_input_tokens=8))
        with self.assertRaisesRegex(PolicyError, "byte limit"):
            meter.reserve_attempt(9)
        self.assertEqual(meter.requests, 0)

    def test_reported_cost_above_budget_blocks_future_use(self):
        meter = BudgetMeter(BudgetLimits(max_requests=2, max_cost_usd=Decimal("0.0001")))
        meter.reserve_attempt(10)
        with self.assertRaises(PolicyError):
            meter.record_response(8, 2, Decimal("0.01"))

    def test_private_canary_needs_zdr_and_exclusive_typesafe_route(self):
        metadata = {"gateway": {"routing": {"originalModelId": "typesafe-ai/jev",
                                               "resolvedProvider": "typesafe-ai",
                                               "finalProvider": "typesafe-ai"}}}
        with self.assertRaisesRegex(PolicyError, "ZDR"):
            validate_gateway_route(metadata, require_zdr_evidence=True)
        metadata["gateway"]["routing"]["planningReasoning"] = "ZDR requested; ZDR execution order: typesafe-ai"
        validate_gateway_route(metadata, require_zdr_evidence=True)
        metadata["gateway"]["routing"]["finalProvider"] = "other-provider"
        with self.assertRaisesRegex(PolicyError, "TypeSafe"):
            validate_gateway_route(metadata, require_zdr_evidence=True)


if __name__ == "__main__":
    unittest.main()
