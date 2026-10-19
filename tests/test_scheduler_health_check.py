# -*- coding: utf-8 -*-
"""scheduler_health_check.py 补档（--catchup）分支单测。

覆盖点：
    1. _build_slot_results：宽限窗口判定边界（进入窗口 / 未到 / 已过）
    2. _slot_already_dispatched：同档已在 GitHub 上跑过 → 幂等跳过
    3. _dispatch_workflow / _api_post：成功路径与 4xx 错误路径
    4. attempt_catchup：caught_up / dispatch_failed / dry_run / skipped_already_exists
    5. check_today：now 参数注入 + API 结果聚合
    6. main()：--catchup + --dry-run 全流程（mock 网络 + 飞书）

所有测试都通过 monkeypatch 切断外部依赖，不发真实网络请求。
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 让测试能直接 import scripts/scheduler_health_check.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

shc = importlib.import_module("scheduler_health_check")


# ------------------------------------------------------------
# fixtures
# ------------------------------------------------------------
@pytest.fixture
def bjt():
    """BJT 时区对象（复用 shc.BJT 逻辑）。"""
    return timezone(timedelta(hours=8))


@pytest.fixture
def mock_api_get(monkeypatch):
    """把 shc._api_get 替换成可控 fake，返回按 workflow 分组的运行列表。"""
    def _install(push_runs=None, review_runs=None):
        captured = {"urls": []}

        def fake_api_get(token, path, retries=3):
            captured["urls"].append(path)
            if "strategy_cloud_deploy.yml" in path:
                return {"workflow_runs": push_runs or []}
            if "evening_review.yml" in path:
                return {"workflow_runs": review_runs or []}
            return {"workflow_runs": []}

        monkeypatch.setattr(shc, "_api_get", fake_api_get)
        return captured

    return _install


def _make_dispatch_run(bjt_dt: datetime, workflow: str = "strategy_cloud_deploy.yml") -> dict:
    """构造一条 GitHub workflow_dispatch 运行记录（UTC 时间）。"""
    utc_dt = bjt_dt.astimezone(timezone.utc)
    return {
        "event": "workflow_dispatch",
        "created_at": utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "conclusion": "success",
        "name": workflow,
    }


def _slot_for(results, hour, minute):
    for r in results:
        if r["hour"] == hour and r["minute"] == minute:
            return r
    raise AssertionError(f"slot {hour}:{minute} not found in results")


# ------------------------------------------------------------
# 1. _build_slot_results —— 宽限窗口边界
# ------------------------------------------------------------
class TestBuildSlotResults:
    def test_now_inside_window_marks_should_run(self, bjt):
        """10:10 时，10:00 档已进入 30 分钟宽限窗口，10:30 档还没到。"""
        now = datetime(2026, 9, 22, 10, 10, tzinfo=bjt)
        results = shc._build_slot_results(now, [], [])
        s1000 = _slot_for(results, 10, 0)
        s1030 = _slot_for(results, 10, 30)
        assert s1000["should_run"] is True
        assert s1030["should_run"] is False

    def test_now_at_slot_time_marks_should_run(self, bjt):
        """档期整点（delay=0）算进窗口。"""
        now = datetime(2026, 9, 22, 10, 0, tzinfo=bjt)
        results = shc._build_slot_results(now, [], [])
        assert _slot_for(results, 10, 0)["should_run"] is True

    def test_now_at_window_boundary_marks_should_run(self, bjt):
        """delay 恰好等于 CATCHUP_WINDOW_MINUTES（30 分钟）仍在窗口内。"""
        now = datetime(2026, 9, 22, 10, 30, tzinfo=bjt)
        results = shc._build_slot_results(now, [], [])
        assert _slot_for(results, 10, 0)["should_run"] is True

    def test_now_just_past_window_marks_false(self, bjt):
        """delay = 31 分钟已过窗口，不补。"""
        now = datetime(2026, 9, 22, 10, 31, tzinfo=bjt)
        results = shc._build_slot_results(now, [], [])
        assert _slot_for(results, 10, 0)["should_run"] is False

    def test_review_slot_uses_review_workflow(self, bjt):
        """15:30 复盘档应使用 evening_review.yml。"""
        now = datetime(2026, 9, 22, 15, 40, tzinfo=bjt)
        results = shc._build_slot_results(now, [], [])
        s1530 = _slot_for(results, 15, 30)
        assert s1530["workflow"] == shc.REVIEW_WORKFLOW
        assert s1530["report_mode"] is None
        assert s1530["should_run"] is True

    def test_premarket_slot_uses_premarket_report_mode(self, bjt):
        """9:15 盘前档 report_mode=premarket，其余 push 档是 scan。"""
        now = datetime(2026, 9, 22, 9, 20, tzinfo=bjt)
        results = shc._build_slot_results(now, [], [])
        assert _slot_for(results, 9, 15)["report_mode"] == "premarket"
        assert _slot_for(results, 10, 0)["report_mode"] == "scan"


# ------------------------------------------------------------
# 2. _slot_already_dispatched —— 幂等判定
# ------------------------------------------------------------
class TestSlotAlreadyDispatched:
    def test_exact_slot_time_is_dispatched(self, bjt):
        """运行时间恰好等于档位时间（delay=0）→ 已分发。"""
        slot = {"kind": "push", "hour": 10, "minute": 0}
        runs = [_make_dispatch_run(datetime(2026, 9, 22, 10, 0, tzinfo=bjt))]
        assert shc._slot_already_dispatched(slot, runs, []) is True

    def test_within_tolerance_is_dispatched(self, bjt):
        """运行时间在档位 ±15 分钟内（Worker Cron 抖动容忍）。"""
        slot = {"kind": "push", "hour": 10, "minute": 30}
        runs = [_make_dispatch_run(datetime(2026, 9, 22, 10, 38, tzinfo=bjt))]
        assert shc._slot_already_dispatched(slot, runs, []) is True

    def test_outside_tolerance_is_not_dispatched(self, bjt):
        """运行时间在档位 20 分钟外 → 该档位未分发。"""
        slot = {"kind": "push", "hour": 10, "minute": 30}
        runs = [_make_dispatch_run(datetime(2026, 9, 22, 10, 50, tzinfo=bjt))]
        assert shc._slot_already_dispatched(slot, runs, []) is False

    def test_wrong_kind_runs_ignored(self, bjt):
        """push 档只看 push_today，review_today 的 runs 不算数。"""
        slot = {"kind": "push", "hour": 10, "minute": 0}
        review_run = _make_dispatch_run(datetime(2026, 9, 22, 10, 0, tzinfo=bjt),
                                        workflow="evening_review.yml")
        assert shc._slot_already_dispatched(slot, [], [review_run]) is False

    def test_empty_runs_is_not_dispatched(self, bjt):
        slot = {"kind": "push", "hour": 10, "minute": 0}
        assert shc._slot_already_dispatched(slot, [], []) is False


# ------------------------------------------------------------
# 3. _api_post / _dispatch_workflow
# ------------------------------------------------------------
class TestApiPost:
    def _mk_resp(self, status_code: int, text: str):
        """构造 requests.Response 风格对象：status_code 与 text 精确可控。"""
        return types.SimpleNamespace(status_code=status_code, text=text)

    def test_api_post_success(self, monkeypatch):
        """HTTP 202 → {"_status": 202}（无 _error 键）。"""
        monkeypatch.setattr("requests.post",
                            lambda *a, **kw: self._mk_resp(202, ""))
        result = shc._api_post("token", "/dispatches", {"ref": "refs/heads/main"})
        assert result == {"_status": 202}
        assert "_error" not in result

    def test_api_post_error_returns_error_dict(self, monkeypatch):
        """HTTP 403 → {"_status": 403, "_error": "..."}。"""
        fake_resp = MagicMock(status_code=403, text="Forbidden")
        monkeypatch.setattr("requests.post", lambda *a, **kw: fake_resp)
        result = shc._api_post("bad_token", "/dispatches", {})
        assert result["_status"] == 403
        assert "Forbidden" in result["_error"]

    def test_api_post_network_error_returns_error_dict(self, monkeypatch):
        """网络异常 → {"_error": "..."}，不抛异常。"""
        def raise_conn_error(*a, **kw):
            raise ConnectionError("boom")
        monkeypatch.setattr("requests.post", raise_conn_error)
        result = shc._api_post("token", "/dispatches", {})
        assert "_error" in result
        assert "ConnectionError" in result["_error"]

    def test_dispatch_workflow_omits_inputs_when_report_mode_none(self, monkeypatch):
        """report_mode=None → POST body 的 inputs 为空字典（evening_review 无 inputs）。"""
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return MagicMock(status_code=204, text="")

        monkeypatch.setattr("requests.post", fake_post)
        shc._dispatch_workflow("token", "evening_review.yml", None)
        assert captured["json"]["inputs"] == {}
        assert captured["json"]["ref"] == "refs/heads/main"
        assert "evening_review.yml" in captured["url"]

    def test_dispatch_workflow_includes_report_mode(self, monkeypatch):
        """report_mode="scan" → POST body inputs.report_mode 有值。"""
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return MagicMock(status_code=202, text="")

        monkeypatch.setattr("requests.post", fake_post)
        shc._dispatch_workflow("token", "strategy_cloud_deploy.yml", "scan")
        assert captured["json"]["inputs"] == {"report_mode": "scan"}


# ------------------------------------------------------------
# 4. attempt_catchup —— 各事件分支
# ------------------------------------------------------------
class TestAttemptCatchup:
    def _mk_results(self, *, in_window=True, existing=None):
        existing = existing or []
        return [{
            "kind": "push", "hour": 10, "minute": 0, "label": "上午盘中",
            "workflow": shc.PUSH_WORKFLOW, "report_mode": "scan",
            "should_run": in_window,
            "existing_count": len(existing), "existing_runs": existing,
        }]

    def _patch_log_dir(self, monkeypatch, tmp_path):
        """让所有 _record_catchup 调用写到 tmp_path/data/，不污染仓库。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        original = shc._record_catchup

        def patched(*args, **kwargs):
            kwargs["log_dir"] = str(tmp_path)
            return original(*args, **kwargs)

        monkeypatch.setattr(shc, "_record_catchup", patched)

    def test_catchup_success(self, monkeypatch, tmp_path):
        """漏发档 → 触发 POST → 返回 caught_up。"""
        self._patch_log_dir(monkeypatch, tmp_path)
        monkeypatch.setattr(shc, "_dispatch_workflow",
                            lambda token, wf, rm: {"_status": 202})
        day = date(2026, 9, 22)
        results = self._mk_results()
        events = shc.attempt_catchup("token", day, results, dry_run=False)
        assert len(events) == 1
        assert events[0]["event"] == "caught_up"
        assert events[0]["slot"] == "10:00"

    def test_catchup_dispatch_failed(self, monkeypatch, tmp_path):
        """POST 401 → 事件是 dispatch_failed，带 status 与错误文本。"""
        self._patch_log_dir(monkeypatch, tmp_path)
        monkeypatch.setattr(shc, "_dispatch_workflow",
                            lambda *a, **kw: {"_status": 401, "_error": "Bad credentials"})
        day = date(2026, 9, 22)
        results = self._mk_results()
        events = shc.attempt_catchup("token", day, results, dry_run=False)
        assert events[0]["event"] == "dispatch_failed"
        assert events[0]["status"] == 401

    def test_catchup_dry_run_no_dispatch(self, monkeypatch, tmp_path):
        """dry_run=True → 不调用 _dispatch_workflow，事件是 dry_run。"""
        self._patch_log_dir(monkeypatch, tmp_path)
        called = {"count": 0}

        def fake_dispatch(*a, **kw):
            called["count"] += 1
            return {"_status": 202}

        monkeypatch.setattr(shc, "_dispatch_workflow", fake_dispatch)
        day = date(2026, 9, 22)
        results = self._mk_results()
        events = shc.attempt_catchup("token", day, results, dry_run=True)
        assert called["count"] == 0
        assert events[0]["event"] == "dry_run"

    def test_catchup_skipped_already_dispatched(self, monkeypatch, tmp_path, bjt):
        """同一档已存在 workflow_dispatch → 跳过，不重复触发。"""
        self._patch_log_dir(monkeypatch, tmp_path)
        called = {"count": 0}

        def fake_dispatch(*a, **kw):
            called["count"] += 1
            return {"_status": 202}

        monkeypatch.setattr(shc, "_dispatch_workflow", fake_dispatch)
        day = date(2026, 9, 22)
        existing_run = _make_dispatch_run(datetime(2026, 9, 22, 10, 3, tzinfo=bjt))
        results = self._mk_results(existing=[existing_run])
        events = shc.attempt_catchup("token", day, results, dry_run=False)
        assert called["count"] == 0
        assert events[0]["event"] == "skipped_already_exists"

    def test_catchup_no_in_window_slots_no_events(self, monkeypatch, tmp_path):
        """所有档 should_run=False → 无事件返回，不调用 POST。"""
        self._patch_log_dir(monkeypatch, tmp_path)
        called = {"count": 0}

        def fake_dispatch(*a, **kw):
            called["count"] += 1
            return {"_status": 202}

        monkeypatch.setattr(shc, "_dispatch_workflow", fake_dispatch)
        day = date(2026, 9, 22)
        results = self._mk_results(in_window=False)
        events = shc.attempt_catchup("token", day, results, dry_run=False)
        assert called["count"] == 0
        assert events == []

    def test_catchup_mixed_slots_only_in_window_dispatched(self, monkeypatch, tmp_path, bjt):
        """两个档：10:00 应补，11:00 已过窗口 → 只对 10:00 触发一次 POST。"""
        self._patch_log_dir(monkeypatch, tmp_path)
        dispatched = []

        def fake_dispatch(token, wf, rm):
            dispatched.append((wf, rm))
            return {"_status": 202}

        monkeypatch.setattr(shc, "_dispatch_workflow", fake_dispatch)
        day = date(2026, 9, 22)
        results = [
            {"kind": "push", "hour": 10, "minute": 0, "label": "上午盘中",
             "workflow": shc.PUSH_WORKFLOW, "report_mode": "scan",
             "should_run": True, "existing_count": 0, "existing_runs": []},
            {"kind": "push", "hour": 11, "minute": 0, "label": "上午盘中",
             "workflow": shc.PUSH_WORKFLOW, "report_mode": "scan",
             "should_run": False, "existing_count": 0, "existing_runs": []},
            {"kind": "review", "hour": 15, "minute": 30, "label": "收盘复盘",
             "workflow": shc.REVIEW_WORKFLOW, "report_mode": None,
             "should_run": False, "existing_count": 0, "existing_runs": []},
        ]
        events = shc.attempt_catchup("token", day, results, dry_run=False)
        assert dispatched == [("strategy_cloud_deploy.yml", "scan")]
        assert len(events) == 1


# ------------------------------------------------------------
# 5. check_today —— API 结果聚合 + now 注入
# ------------------------------------------------------------
class TestCheckToday:
    def test_check_today_in_window_slot(self, bjt, mock_api_get):
        """10:10 → 10:00 档 should_run=True；API 返回的 runs 挂在 existing_runs 上。"""
        now = datetime(2026, 9, 22, 10, 10, tzinfo=bjt)
        day = now.date()
        run_at_9_15 = _make_dispatch_run(datetime(2026, 9, 22, 9, 15, tzinfo=bjt))
        mock_api_get(push_runs=[run_at_9_15])

        result_day, results = shc.check_today("token", ref_day=day, now=now)
        assert result_day == day
        s1000 = _slot_for(results, 10, 0)
        assert s1000["should_run"] is True
        assert s1000["existing_count"] == 1
        assert s1000["existing_runs"] == [run_at_9_15]

    def test_check_today_after_all_slots_no_should_run(self, bjt, mock_api_get):
        """18:00 → 所有交易档都 out of window → 无 should_run=True。"""
        now = datetime(2026, 9, 22, 18, 0, tzinfo=bjt)
        day = now.date()
        mock_api_get(push_runs=[], review_runs=[])

        _, results = shc.check_today("token", ref_day=day, now=now)
        assert all(not r["should_run"] for r in results)

    def test_check_today_pre_open_all_false(self, bjt, mock_api_get):
        """8:00（开盘前）→ 所有档 delay<0 → 无 should_run=True。"""
        now = datetime(2026, 9, 22, 8, 0, tzinfo=bjt)
        day = now.date()
        mock_api_get(push_runs=[], review_runs=[])

        _, results = shc.check_today("token", ref_day=day, now=now)
        assert all(not r["should_run"] for r in results)


# ------------------------------------------------------------
# 6. main() —— --catchup + --dry-run 全流程
# ------------------------------------------------------------
class TestMainCatchup:
    def test_main_catchup_dry_run_no_network_no_feishu(self, monkeypatch, bjt, tmp_path):
        """--catchup --dry-run → 不发真实 POST、不推飞书、exit 0。"""
        monkeypatch.setattr(shc, "now_bjt",
                            lambda: datetime(2026, 9, 22, 10, 10, tzinfo=timezone(timedelta(hours=8))))
        run_915 = _make_dispatch_run(datetime(2026, 9, 22, 9, 15, tzinfo=timezone(timedelta(hours=8))))
        monkeypatch.setattr(shc, "_dispatches_by_day",
                            lambda token, wf, ref, days=1: {ref: ([run_915] if wf == shc.PUSH_WORKFLOW else [])})
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        original_record = shc._record_catchup
        monkeypatch.setattr(shc, "_record_catchup",
                            lambda *a, **kw: original_record(*a, log_dir=str(tmp_path), **kw))
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        feishu_called = {"count": 0}
        monkeypatch.setattr(shc, "push_feishu",
                            lambda text: feishu_called.__setitem__("count", feishu_called["count"] + 1))

        argv_orig = sys.argv
        try:
            sys.argv = ["scheduler_health_check.py", "--catchup", "--dry-run"]
            rc = shc.main()
        finally:
            sys.argv = argv_orig

        assert rc == 0
        assert feishu_called["count"] == 0  # dry-run 不推飞书

    def test_main_catchup_writes_audit_log(self, monkeypatch, bjt, tmp_path):
        """dry-run 模式下不真正 POST，但 dry_run 事件写入审计日志。"""
        monkeypatch.setattr(shc, "now_bjt",
                            lambda: datetime(2026, 9, 22, 10, 10, tzinfo=timezone(timedelta(hours=8))))
        monkeypatch.setattr(shc, "_dispatches_by_day",
                            lambda token, wf, ref, days=1: {})
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        original_record = shc._record_catchup
        monkeypatch.setattr(shc, "_record_catchup",
                            lambda *a, **kw: original_record(*a, log_dir=str(tmp_path), **kw))
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setattr(shc, "push_feishu", lambda text: True)

        argv_orig = sys.argv
        try:
            sys.argv = ["scheduler_health_check.py", "--catchup", "--dry-run"]
            rc = shc.main()
        finally:
            sys.argv = argv_orig

        log_file = tmp_path / shc.REMEDIATION_LOG
        assert rc == 0
        assert log_file.exists(), f"审计日志应写到 tmp_path，实际不存在: {log_file}"
        text = log_file.read_text(encoding="utf-8")
        assert '"event": "dry_run"' in text or '"event":"dry_run"' in text

    def test_main_catchup_no_token_returns_1(self, monkeypatch):
        """缺 GITHUB_TOKEN → exit 1，不进入补档逻辑。"""
        argv_orig = sys.argv
        try:
            sys.argv = ["scheduler_health_check.py", "--catchup"]
            monkeypatch.delenv("GITHUB_TOKEN", raising=False)
            rc = shc.main()
        finally:
            sys.argv = argv_orig
        assert rc == 1

    def test_main_selftest_still_works(self, monkeypatch):
        """--selftest 分支保持原行为。"""
        argv_orig = sys.argv
        try:
            sys.argv = ["scheduler_health_check.py", "--selftest"]
            rc = shc.main()
        finally:
            sys.argv = argv_orig
        assert rc == 0
