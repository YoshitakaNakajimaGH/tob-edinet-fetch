#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPT_SCRIPTS = ROOT / "experiments" / "gpt-extract" / "scripts"
if str(GPT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(GPT_SCRIPTS))

from gemini_client import _models_to_try  # noqa: E402
from llm_common import DEFAULT_GEMINI_MODEL, GEMINI_MODEL_FALLBACKS  # noqa: E402


class GeminiClientTests(unittest.TestCase):
    def test_default_model_is_not_retired(self) -> None:
        self.assertNotEqual(DEFAULT_GEMINI_MODEL, "gemini-2.0-flash")

    def test_models_to_try_preserves_requested_model_first(self) -> None:
        models = _models_to_try("gemini-2.5-flash-lite")
        self.assertEqual(models[0], "gemini-2.5-flash-lite")
        for fallback in GEMINI_MODEL_FALLBACKS:
            self.assertIn(fallback, models)


if __name__ == "__main__":
    unittest.main()
