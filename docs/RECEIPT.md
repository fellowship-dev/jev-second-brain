# MVP verification receipt

Verified locally on macOS, 2026-09-20 (America/Santiago), at commit `475a0c4`.

| Check | Result |
| --- | --- |
| Synthetic tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q`: 44 passed. |
| Skill provenance | `python3 scripts/check_skill_sync.py --source-repo ../jev-pattern-library-draft`: matched recorded source and copy hashes. |
| Package build | Python 3.12, `pip wheel --no-deps --no-build-isolation .`: built `jev_second_brain-0.1.0-py3-none-any.whl`. |
| Clean install | Installed that wheel into a temporary virtual environment with `--no-index --no-deps`; installed CLI completed `init`, `index`, `search`, and `suggest` on the fictional vault. |
| Synthetic journey | 5 notes indexed; search returned 3 local hits; one-note preview returned 3 pending candidate judgments and made zero provider calls. |
| Source preservation | The synthetic fixture files were unchanged after the installed CLI journey. State was outside the vault. |
| Working tree | Clean after the MVP commit on local `main`. |

No Gateway key was available in this process. The `/v1/evaluate` adapter and
privacy policy are covered by mocked tests, but a live synthetic canary and
private route eligibility remain unverified. CI is configured and has not run
on a remote host. No private corpus was indexed or transmitted in this receipt.

The next measured gate is candidate recall and false-link review on a frozen
small corpus, followed by a scoped private pilot. Public GitHub publication
is a separate owner decision.
