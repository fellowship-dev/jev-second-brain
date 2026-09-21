import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_second_brain.cli import main


class CliSmokeTest(unittest.TestCase):
    def test_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Local-first Markdown memory tooling", out.getvalue())

    def test_local_journey_is_source_preserving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault, state = root / "vault", root / "state"
            vault.mkdir()
            note = vault / "note.md"
            note.write_text("# Fresh note\nA blue dragon lives here.\n", encoding="utf-8")

            def invoke(*args: str) -> dict:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(list(args)), 0)
                return json.loads(output.getvalue())

            initialized = invoke("init", str(vault), "--state", str(state), "--json")
            self.assertEqual(initialized["vault"], str(vault.resolve()))
            indexed = invoke("index", "--state", str(state), "--json")
            self.assertEqual(indexed["added"], 1)
            hits = invoke("search", "blue dragon", "--state", str(state), "--json")
            self.assertEqual(hits["hits"][0]["path"], "note.md")
            self.assertEqual(hits["hits"][0]["source_path"], str(note.resolve()))
            preview = invoke("suggest", "note.md", "--state", str(state), "--json")
            self.assertEqual(preview["candidates"]["eligible_count"], 0)
            self.assertEqual(preview["provider_calls"], 0)
            review = invoke("review", "link_example", "keep", "--state", str(state), "--json")
            self.assertEqual(review["disposition"], "keep")
            self.assertEqual(note.read_text(encoding="utf-8"), "# Fresh note\nA blue dragon lives here.\n")

            (vault / "related.md").write_text("# Fresh dragon\nAnother dragon.\n", encoding="utf-8")
            invoke("index", "--state", str(state), "--json")
            error = io.StringIO()
            with patch.dict("os.environ", {"AI_GATEWAY_API_KEY": ""}), contextlib.redirect_stderr(error), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["suggest", "note.md", "--state", str(state), "--evaluate", "--public"]), 2)
            self.assertIn("AI_GATEWAY_API_KEY", error.getvalue())
