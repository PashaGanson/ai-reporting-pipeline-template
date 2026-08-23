from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import report_snapshot  # noqa: E402
import weekly_report  # noqa: E402


class PublicTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = weekly_report.load_json(ROOT / "config" / "report_config.example.json")
        self.period = weekly_report.get_period(
            weekly_report.parse_tz(self.config["timezone"]),
            ["2026-05-04", "2026-05-10"],
        )

    def test_sample_data_never_enters_network_path(self) -> None:
        with patch.object(weekly_report, "urlopen", side_effect=AssertionError("network entered")):
            leads, deals = weekly_report.load_inputs(
                argparse.Namespace(sample_data=str(ROOT / "sample_data")),
                self.config,
                self.period,
            )
        self.assertEqual(len(leads), 8)
        self.assertEqual(len(deals), 4)

    def test_missing_webhook_fails_closed_before_network(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            weekly_report, "bitrix_get_all", side_effect=AssertionError("network entered")
        ):
            with self.assertRaisesRegex(SystemExit, "Set BITRIX_WEBHOOK_URL"):
                weekly_report.load_inputs(
                    argparse.Namespace(sample_data=""), self.config, self.period
                )

    def test_committed_fixtures_have_only_expected_synthetic_fields(self) -> None:
        leads = weekly_report.load_json(ROOT / "sample_data" / "leads.json")
        deals = weekly_report.load_json(ROOT / "sample_data" / "deals.json")
        self.assertEqual(
            set().union(*(row.keys() for row in leads)),
            {"ID", "DATE_CREATE", "STATUS_ID", "ASSIGNED_BY_ID", "UF_CRM_UNQUALIFIED"},
        )
        self.assertEqual(
            set().union(*(row.keys() for row in deals)),
            {
                "ID", "DATE_CREATE", "STAGE_ID", "OPPORTUNITY",
                "UF_CRM_BOOKING_MANAGER", "UF_CRM_SOURCE_MARKER",
                "UF_CRM_BOOKING_DATE", "UF_CRM_HALL", "UF_CRM_PACKAGE_TYPE",
                "UF_CRM_CLIENT_TYPE", "UF_CRM_EVENT_TYPE",
            },
        )
        fixture_text = json.dumps({"leads": leads, "deals": deals}, sort_keys=True)
        self.assertNotIn("@", fixture_text)
        self.assertNotRegex(fixture_text, r"(?i)(phone|email|name|chat|call)")

    def test_snapshot_is_byte_deterministic(self) -> None:
        leads, deals = weekly_report.load_inputs(
            argparse.Namespace(sample_data=str(ROOT / "sample_data")), self.config, self.period
        )
        report = weekly_report.build_report(self.config, self.period, leads, deals)
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.png"
            second = Path(temp_dir) / "second.png"
            report_snapshot.render_snapshot(report, first)
            report_snapshot.render_snapshot(report, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).hexdigest(),
                "e13186158a0b5acae2403c2a06c3473413c34bdcf03d524898f2c83cdb1f710e",
            )

    def test_report_outputs_use_lf_on_every_supported_host(self) -> None:
        leads, deals = weekly_report.load_inputs(
            argparse.Namespace(sample_data=str(ROOT / "sample_data")), self.config, self.period
        )
        report = weekly_report.build_report(self.config, self.period, leads, deals)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_report, "OUT_DIR", Path(temp_dir)
        ):
            weekly_report.write_outputs(report)
            for name in ("weekly_report.json", "weekly_report.md"):
                self.assertNotIn(b"\r\n", (Path(temp_dir) / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
