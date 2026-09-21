import json
import tempfile
import unittest
from pathlib import Path

from jev_second_brain.reviews import append_review, latest_reviews, proposal_id


class ReviewStoreTest(unittest.TestCase):
    def test_revision_and_direction_change_proposal_identity(self):
        base = proposal_id("new", "rev-1", "old", "rev-a", "supports")
        self.assertEqual(base, proposal_id("new", "rev-1", "old", "rev-a", "supports"))
        self.assertNotEqual(base, proposal_id("new", "rev-2", "old", "rev-a", "supports"))
        self.assertNotEqual(base, proposal_id("new", "rev-1", "old", "rev-b", "supports"))
        self.assertNotEqual(base, proposal_id("old", "rev-a", "new", "rev-1", "supports"))
        self.assertNotEqual(base, proposal_id("new", "rev-1", "old", "rev-a", "updates"))

    def test_reviews_append_corrections_but_not_identical_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / ".secondbrain" / "reviews.jsonl"
            identity = proposal_id("new", "1", "old", "1", "supports")
            first = append_review(state, proposal_id=identity, disposition="keep", note="Source confirms it")
            replay = append_review(state, proposal_id=identity, disposition="keep", note="Source confirms it")
            self.assertEqual(first, replay)
            self.assertEqual(len(state.read_text().splitlines()), 1)

            correction = append_review(state, proposal_id=identity, disposition="reject", note="Different event")
            self.assertEqual(correction["disposition"], "reject")
            self.assertEqual(len(state.read_text().splitlines()), 2)
            self.assertEqual(latest_reviews(state)[identity], correction)
            self.assertEqual(json.loads(state.read_text().splitlines()[0]), first)

    def test_missing_store_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "reviews.jsonl"
            self.assertEqual(latest_reviews(state), {})
            with self.assertRaises(ValueError):
                proposal_id("", "1", "old", "1", "supports")
            with self.assertRaises(ValueError):
                append_review(state, proposal_id="some-id", disposition="delete")
            self.assertFalse(state.exists())

    def test_corrupt_review_log_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "reviews.jsonl"
            state.write_text("{bad json}\n")
            with self.assertRaises(ValueError):
                append_review(state, proposal_id="some-id", disposition="unsure")
            self.assertEqual(state.read_text(), "{bad json}\n")
            state.write_text('{"proposal_id":"some-id","disposition":"keep","reviewed_at":"now"}\n')
            with self.assertRaises(ValueError):
                latest_reviews(state)


if __name__ == "__main__":
    unittest.main()
