import json
import os
import tempfile
import unittest
from pathlib import Path

from jev_second_brain.config import init_project, load_config


class ConfigTest(unittest.TestCase):
    def test_init_is_external_to_vault_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            note = vault / "note.md"
            note.write_text("# Source\n", encoding="utf-8")
            state = root / "state"
            config = init_project(vault, state_dir=state)
            self.assertEqual(config.vault, vault.resolve())
            self.assertEqual(config.db_path, state.resolve() / "index.sqlite")
            self.assertFalse(config.allow_private_provider)
            self.assertEqual(load_config(state), config)
            self.assertEqual(init_project(vault, state_dir=state), config)
            self.assertEqual(note.read_text(encoding="utf-8"), "# Source\n")
            self.assertEqual(sorted(p.name for p in vault.iterdir()), ["note.md"])
            self.assertEqual(json.loads((state / "config.json").read_text())["schema"], 1)
            if os.name == "posix":
                self.assertEqual(state.stat().st_mode & 0o077, 0)

    def test_refuses_to_rebind_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            state = root / "state"
            init_project(first, state_dir=state)
            with self.assertRaises(ValueError):
                init_project(second, state_dir=state)
