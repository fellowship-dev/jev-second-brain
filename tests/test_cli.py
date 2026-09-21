import contextlib
import io
import unittest

from jev_second_brain.cli import main


class CliSmokeTest(unittest.TestCase):
    def test_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Local-first Markdown memory tooling", out.getvalue())
