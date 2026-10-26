# -*- coding: utf-8 -*-
"""配置加载器单测。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_loader import load_feishu_config, resolve_env  # noqa: E402


class TestResolveEnv(unittest.TestCase):
    def test_resolve_placeholder(self):
        os.environ["TEST_VAR_1"] = "abc"
        self.assertEqual(resolve_env("${TEST_VAR_1}"), "abc")

    def test_resolve_missing_raises(self):
        os.environ.pop("TEST_MISSING_VAR", None)
        with self.assertRaises(KeyError):
            resolve_env("${TEST_MISSING_VAR}")

    def test_resolve_nested(self):
        os.environ["TEST_VAR_2"] = "xyz"
        data = {"a": "${TEST_VAR_2}", "b": [1, "${TEST_VAR_2}"], "c": "plain"}
        out = resolve_env(data)
        self.assertEqual(out["a"], "xyz")
        self.assertEqual(out["b"][1], "xyz")
        self.assertEqual(out["c"], "plain")

    def test_plain_string_unchanged(self):
        self.assertEqual(resolve_env("no placeholder"), "no placeholder")


class TestLoadFeishuConfig(unittest.TestCase):
    def test_load_with_env(self):
        os.environ["FEISHU_WEBHOOK_URL"] = "https://example.com/hook/123"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"webhook_url": "${FEISHU_WEBHOOK_URL}", "enabled": True}, f, ensure_ascii=False)
            path = f.name
        try:
            cfg = load_feishu_config(path)
            self.assertEqual(cfg["webhook_url"], "https://example.com/hook/123")
            self.assertTrue(cfg["enabled"])
        finally:
            os.unlink(path)

    def test_missing_webhook_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"enabled": True}, f, ensure_ascii=False)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_feishu_config(path)
        finally:
            os.unlink(path)

    def test_missing_env_raises(self):
        os.environ.pop("FEISHU_WEBHOOK_URL", None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"webhook_url": "${FEISHU_WEBHOOK_URL}"}, f, ensure_ascii=False)
            path = f.name
        try:
            with self.assertRaises(KeyError):
                load_feishu_config(path)
        finally:
            os.unlink(path)

    def test_legacy_format_compat(self):
        os.environ["FEISHU_WEBHOOK_URL"] = "https://example.com/hook/legacy"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"飞书配置": {"webhook": "${FEISHU_WEBHOOK_URL}", "enabled": True}}, f, ensure_ascii=False)
            path = f.name
        try:
            cfg = load_feishu_config(path)
            self.assertEqual(cfg["webhook_url"], "https://example.com/hook/legacy")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
