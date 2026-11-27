from __future__ import annotations

import ast
import unittest
from pathlib import Path


class StatusMonitorJobsConfigTests(unittest.TestCase):
    @staticmethod
    def _find_async_job(name: str) -> ast.AsyncFunctionDef:
        source_path = Path(__file__).resolve().parents[1] / "src" / "plugins" / "status_monitor" / "jobs.py"
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in module.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
                return node
        raise AssertionError(f"async job not found: {name}")

    def _assert_scheduled_job_call(self, decorator: ast.expr) -> ast.Call:
        self.assertIsInstance(decorator, ast.Call)
        assert isinstance(decorator, ast.Call)
        self.assertIsInstance(decorator.func, ast.Attribute)
        assert isinstance(decorator.func, ast.Attribute)
        self.assertIsInstance(decorator.func.value, ast.Name)
        assert isinstance(decorator.func.value, ast.Name)
        self.assertEqual(decorator.func.value.id, "scheduler")
        self.assertEqual(decorator.func.attr, "scheduled_job")
        return decorator

    def test_daily_jjc_ranking_allows_two_concurrent_instances(self) -> None:
        target = self._find_async_job("push_daily_jjc_ranking")
        decorator = self._assert_scheduled_job_call(target.decorator_list[0])

        keywords = {
            keyword.arg: keyword.value
            for keyword in decorator.keywords
            if keyword.arg is not None
        }
        self.assertEqual(ast.literal_eval(keywords["hour"]), "3,21")
        self.assertEqual(ast.literal_eval(keywords["minute"]), 0)
        self.assertEqual(ast.literal_eval(keywords["max_instances"]), 2)

    def test_check_status_uses_max_instances_without_duplicate_run_throttle(self) -> None:
        target = self._find_async_job("check_status")
        self.assertEqual(len(target.decorator_list), 1)
        decorator = self._assert_scheduled_job_call(target.decorator_list[0])
        self.assertEqual(ast.literal_eval(decorator.args[0]), "interval")

        keywords = {
            keyword.arg: keyword.value
            for keyword in decorator.keywords
            if keyword.arg is not None
        }
        self.assertIsInstance(keywords["minutes"], ast.Name)
        self.assertEqual(keywords["minutes"].id, "STATUS_check_time")
        self.assertEqual(ast.literal_eval(keywords["max_instances"]), 1)


if __name__ == "__main__":
    unittest.main()
