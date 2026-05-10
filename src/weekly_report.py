#!/usr/bin/env python3
"""Weekly CRM reporting pipeline.

This is a public-safe version of a real Bitrix24 weekly reporting script.
Production input files and credentials were removed. Bring your own CRM export
or set BITRIX_WEBHOOK_URL and adapt config/report_config.example.json.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/report_config.example.json"
DEFAULT_SAMPLE_DIR = ROOT / "sample_data"
OUT_DIR = ROOT / "out"


@dataclass
class Period:
    start: datetime
    end: datetime


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_tz(value: str) -> timezone:
    sign = 1 if value.startswith("+") else -1
    hours, minutes = map(int, value[1:].split(":"))
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def get_period(tz: timezone, week: list[str] | None) -> Period:
    if week:
        start = datetime.strptime(week[0], "%Y-%m-%d").replace(tzinfo=tz)
        end = datetime.strptime(week[1], "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=tz)
        return Period(start, end)
    today = datetime.now(tz)
    last_monday = today - timedelta(days=today.weekday() + 7)
    start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return Period(start, end)


def in_period(row: dict, field: str, period: Period) -> bool:
    raw = row.get(field)
    if not raw:
        return False
    dt = datetime.fromisoformat(str(raw))
    return period.start <= dt <= period.end


def bitrix_get_all(webhook: str, method: str, filters: dict, select_fields: list[str]) -> list[dict]:
    items: list[dict] = []
    start = 0
    while True:
        params = {"start": start}
        for i, field in enumerate(select_fields):
            params[f"select[{i}]"] = field
        params.update(filters)
        url = f"{webhook.rstrip('/')}/{method}?" + urlencode(params, doseq=True)
        try:
            with urlopen(Request(url), timeout=30) as resp:
                payload = json.loads(resp.read())
        except HTTPError as exc:
            raise RuntimeError(f"Bitrix HTTP {exc.code} for {method}") from exc
        except URLError as exc:
            raise RuntimeError(f"Bitrix network error for {method}: {exc}") from exc
        batch = payload.get("result", [])
        items.extend(batch)
        total = payload.get("total", 0)
        if len(items) >= total or not batch:
            return items
        start += 50


def load_inputs(args, config: dict, period: Period) -> tuple[list[dict], list[dict]]:
    if args.sample_data:
        sample_dir = Path(args.sample_data)
        return load_json(sample_dir / "leads.json"), load_json(sample_dir / "deals.json")

    webhook = os.getenv(config["crm"].get("webhook_env", "BITRIX_WEBHOOK_URL"), "").strip()
    if not webhook:
        raise SystemExit("Set BITRIX_WEBHOOK_URL or pass --sample-data sample_data")

    fields = config["fields"]
    leads = bitrix_get_all(webhook, "crm.lead.list", {
        "filter[>=DATE_CREATE]": period.start.isoformat(),
        "filter[<=DATE_CREATE]": period.end.isoformat(),
    }, ["ID", "DATE_CREATE", "STATUS_ID", "ASSIGNED_BY_ID", fields["unqualified_flag"]])
    deals = bitrix_get_all(webhook, "crm.deal.list", {
        "filter[>=DATE_CREATE]": period.start.isoformat(),
        "filter[<=DATE_CREATE]": period.end.isoformat(),
    }, ["ID", "DATE_CREATE", "STAGE_ID", "OPPORTUNITY", fields["booking_manager"], fields["source_marker"], fields["booking_date"], fields["hall"], fields["package_type"], fields["client_type"], fields["event_type"]])
    return leads, deals


def pct(num: int | float, den: int | float) -> float:
    return round((num / den * 100), 1) if den else 0.0


def build_report(config: dict, period: Period, leads: list[dict], deals: list[dict]) -> dict:
    fields = config["fields"]
    clean_statuses = set(config["clean_lead_statuses"])
    active_stages = set(config["active_deal_stages"])
    won_stage = config["won_stage"]
    returning = str(config["returning_customer_marker"])

    period_leads = [l for l in leads if in_period(l, "DATE_CREATE", period)]
    no_unqualified = [l for l in period_leads if str(l.get(fields["unqualified_flag"], "")) != "1"]
    clean_leads = [l for l in no_unqualified if l.get("STATUS_ID") in clean_statuses]
    period_deals = [d for d in deals if in_period(d, "DATE_CREATE", period)]
    active_deals = [d for d in period_deals if d.get("STAGE_ID") in active_stages]
    won_deals = [d for d in period_deals if d.get("STAGE_ID") == won_stage]

    managers = []
    for manager_id, manager_name in config["managers"].items():
        manager_leads = [l for l in clean_leads if str(l.get("ASSIGNED_BY_ID")) == manager_id]
        manager_deals = [d for d in active_deals if str(d.get(fields["booking_manager"])) == manager_id]
        new_customer_deals = [d for d in manager_deals if str(d.get(fields["source_marker"], "")) != returning]
        manager_won = [d for d in won_deals if str(d.get(fields["booking_manager"])) == manager_id]
        revenue = sum(float(d.get("OPPORTUNITY") or 0) for d in manager_won)
        managers.append({
            "manager": manager_name,
            "clean_leads": len(manager_leads),
            "active_deals": len(manager_deals),
            "new_customer_deals": len(new_customer_deals),
            "won_deals": len(manager_won),
            "revenue": revenue,
            "lead_to_deal_rate": pct(len(new_customer_deals), len(manager_leads)),
        })

    halls = []
    for hall_id, hall_name in config["halls"].items():
        hall_won = [d for d in won_deals if str(d.get(fields["hall"])) == hall_id]
        halls.append({
            "hall": hall_name,
            "won_deals": len(hall_won),
            "revenue": sum(float(d.get("OPPORTUNITY") or 0) for d in hall_won),
        })

    package_count = sum(1 for d in active_deals if str(d.get(fields["package_type"])) == "package")
    hourly_count = sum(1 for d in active_deals if str(d.get(fields["package_type"])) == "hourly")

    return {
        "period": {"from": period.start.date().isoformat(), "to": period.end.date().isoformat()},
        "summary": {
            "total_leads": len(no_unqualified),
            "clean_leads": len(clean_leads),
            "dirty_leads": len(no_unqualified) - len(clean_leads),
            "active_deals": len(active_deals),
            "won_deals": len(won_deals),
            "revenue": sum(float(d.get("OPPORTUNITY") or 0) for d in won_deals),
            "package_deals": package_count,
            "hourly_deals": hourly_count,
        },
        "managers": managers,
        "halls": halls,
    }


def write_outputs(report: dict) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "weekly_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Weekly Business Report: {report['period']['from']} — {report['period']['to']}",
        "",
        "## Summary",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")
    lines += ["", "## Managers"]
    for row in report["managers"]:
        lines.append(f"- **{row['manager']}**: {row['clean_leads']} clean leads, {row['active_deals']} active deals, {row['won_deals']} wins, ${row['revenue']:.0f} revenue")
    lines += ["", "## Halls / Rooms"]
    for row in report["halls"]:
        lines.append(f"- **{row['hall']}**: {row['won_deals']} wins, ${row['revenue']:.0f} revenue")
    (OUT_DIR / "weekly_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly CRM reporting pipeline")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--sample-data", default=str(DEFAULT_SAMPLE_DIR), help="Folder with leads.json and deals.json. Omit only when using BITRIX_WEBHOOK_URL.")
    parser.add_argument("--week", nargs=2, metavar=("FROM", "TO"), help="Example: 2026-05-04 2026-05-10")
    args = parser.parse_args()

    config = load_json(Path(args.config))
    period = get_period(parse_tz(config.get("timezone", "+00:00")), args.week)
    leads, deals = load_inputs(args, config, period)
    report = build_report(config, period, leads, deals)
    write_outputs(report)
    print(f"Wrote {OUT_DIR / 'weekly_report.json'}")
    print(f"Wrote {OUT_DIR / 'weekly_report.md'}")


if __name__ == "__main__":
    main()
