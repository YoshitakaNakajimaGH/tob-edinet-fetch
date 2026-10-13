#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GPT_SCRIPTS = ROOT / "old" / "experiments" / "gpt-extract" / "scripts"
if str(GPT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(GPT_SCRIPTS))

from gemini_client import call_gemini_json  # noqa: E402
from llm_common import (  # noqa: E402
    GEMINI_MODEL_PREFERENCES,
    _model_score,
    resolve_gemini_model,
)


class GeminiClientTests(unittest.TestCase):
    def test_model_score_prefers_flash_and_stable(self) -> None:
        flash = _model_score("gemini-3.6-flash")
        preview = _model_score("gemini-3.1-pro-preview")
        self.assertGreater(flash, preview)

    def test_resolve_gemini_model_uses_preference_list(self) -> None:
        with patch(
            "llm_common.list_gemini_models",
            return_value=["gemini-3.5-flash-lite", "gemini-3.6-flash"],
        ):
            self.assertEqual(resolve_gemini_model("key"), "gemini-3.6-flash")

    def test_resolve_gemini_model_honors_preferred_when_available(self) -> None:
        with patch(
            "llm_common.list_gemini_models",
            return_value=["gemini-3.5-flash-lite", "gemini-3.6-flash"],
        ):
            self.assertEqual(
                resolve_gemini_model("key", preferred="gemini-3.5-flash-lite"),
                "gemini-3.5-flash-lite",
            )

    def test_call_gemini_json_skips_404_without_unbound_local(self) -> None:
        """Regression: HTTP 404/429 must not fall through with undefined payload."""

        def fake_urlopen(req, timeout=0):
            url = req.full_url
            if "models/list" in url or url.endswith("/models?key=test"):
                body = json.dumps(
                    {
                        "models": [
                            {
                                "name": "models/gemini-3.6-flash",
                                "supportedGenerationMethods": ["generateContent"],
                            }
                        ]
                    }
                ).encode()
                return io.BytesIO(body)

            if "gemini-3.6-flash" in url:
                payload = json.dumps({"error": {"code": 404, "message": "missing"}}).encode()
                raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=io.BytesIO(payload))

            payload = json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "sponsor_type": "unknown",
                                                "sponsor_name": "",
                                                "confidence": "low",
                                                "reason": "test",
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode()
            return io.BytesIO(payload)

        import urllib.error
        import urllib.request

        with patch.object(urllib.request, "urlopen", fake_urlopen):
            with patch(
                "gemini_client.list_gemini_models",
                return_value=["gemini-3.6-flash", "gemini-3.5-flash-lite"],
            ):
                with patch(
                    "gemini_client.resolve_gemini_model",
                    return_value="gemini-3.6-flash",
                ):
                    result = call_gemini_json(
                        prompt='{"sponsor_type":"unknown"}',
                        api_key="test",
                        model="gemini-3.6-flash",
                        max_retries=1,
                    )
        self.assertEqual(result["sponsor_type"], "unknown")

    def test_preferences_not_empty(self) -> None:
        self.assertTrue(GEMINI_MODEL_PREFERENCES)


if __name__ == "__main__":
    unittest.main()
