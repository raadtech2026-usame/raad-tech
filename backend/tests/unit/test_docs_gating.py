"""`_docs_kwargs` (PROJECT_STATUS.md §5 Priority 2, "`/docs` gating for production") — proves the
`/docs`/`/redoc`/`/openapi.json` gating decision is a pure function of `Environment`, never
`get_settings()`'s cached singleton or an ambient process/env-var read. Hermetic by construction:
no settings object is constructed, no `.env`/`RAAD_*` environment variable is read or needs
patching — the exact fragility class `test_video_provider_di_wiring.py` was just caught by (a
CI-job-level env var leaking into a test that assumed a clean default) is structurally impossible
here, since `_docs_kwargs` never reads the environment itself.
"""

from __future__ import annotations

import unittest

from raad.core.config.settings import Environment
from raad.main import _docs_kwargs


class DocsGatingTests(unittest.TestCase):
    def test_prod_disables_docs_redoc_and_openapi(self) -> None:
        self.assertEqual(
            _docs_kwargs(Environment.PROD),
            {"docs_url": None, "redoc_url": None, "openapi_url": None},
        )

    def test_dev_leaves_fastapi_defaults_untouched(self) -> None:
        self.assertEqual(_docs_kwargs(Environment.DEV), {})

    def test_staging_leaves_fastapi_defaults_untouched(self) -> None:
        self.assertEqual(_docs_kwargs(Environment.STAGING), {})


if __name__ == "__main__":
    unittest.main()
