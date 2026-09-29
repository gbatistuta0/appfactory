"""asc_sbp_check — Small Business Program proof from the App Store Connect sales report.

Apple pays 85% of the net price (15% commission) to Small Business Program members and 70% (30%)
otherwise, except "Rate After One Year" subscription renewals, which are 85% for everyone. The
SUBSCRIPTION/SUMMARY sales report carries both the customer price and the developer proceeds per
row, so proceeds ÷ price on rows WITHOUT sales tax/VAT in the price (US storefront) and without a
proceeds reason proves the rate: ≈ 0.85 ⇒ SBP, ≈ 0.70 ⇒ standard rate.

Sales reports need an API key with the Finance (or Sales/Admin) role. The factory's main ASC key
usually has App Manager only, so this uses a separate key: config `asc_finance_key_id` +
`asc_finance_key_filepath` (issuer `asc_issuer_id` is shared) and `asc_vendor_number`.
The report is fetched with the asc CLI, authenticated as the finance key:
  asc analytics sales --vendor … --type SUBSCRIPTION --subtype SUMMARY --frequency DAILY
      --date YYYY-MM-DD --version 1_3 --allow-missing --output <file>   → gzip'd TSV
"""

from __future__ import annotations

import csv
import datetime as _dt
import gzip
import io
import os
import tempfile
from typing import Any, Callable

from . import asc_cli
from . import config as cfg

# Label only: the report is fetched by `asc analytics sales`, never by URL.
SALES_REPORT = "salesReports"
SBP_RATE, STANDARD_RATE, TOLERANCE = 0.85, 0.70, 0.03

Fetch = Callable[[str, dict[str, str], dict[str, str]], tuple[int, bytes]]


def _num(v: str | None) -> float | None:
    try:
        return float((v or "").replace(",", ""))
    except ValueError:
        return None


def parse_report(raw: bytes) -> list[dict[str, str]]:
    """gzip'd (or plain) TSV → rows keyed by the header line."""
    try:
        data = gzip.decompress(raw)
    except OSError:
        data = raw
    text = data.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def proceeds_ratio(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Weighted proceeds/price on US (USD, tax-exclusive) rows without a proceeds reason."""
    price_sum = proceeds_sum = 0.0
    used = 0
    for r in rows:
        country = (r.get("Country") or "").strip().upper()
        cur = (r.get("Customer Currency") or "").strip().upper()
        pcur = (r.get("Proceeds Currency") or "").strip().upper()
        reason = (r.get("Proceeds Reason") or "").strip()
        price, proceeds = _num(r.get("Customer Price")), _num(r.get("Developer Proceeds"))
        units = _num(r.get("Active Standard Price Subscriptions")) or 1.0
        if country != "US" or cur != "USD" or pcur not in ("", "USD") or reason:
            continue
        if not price or proceeds is None or price <= 0:
            continue
        price_sum += price * units
        proceeds_sum += proceeds * units
        used += 1
    if not used:
        return {"ratio": None, "rows_used": 0}
    return {"ratio": round(proceeds_sum / price_sum, 4), "rows_used": used}


def classify(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if abs(ratio - SBP_RATE) <= TOLERANCE:
        return "small_business_program"
    if abs(ratio - STANDARD_RATE) <= TOLERANCE:
        return "standard_rate"
    return "unknown"


def _asc_fetch(creds: dict[str, str]) -> Fetch:
    """A Fetch that downloads the report with `asc analytics sales` as the finance key.
    Returns (HTTP-like status, gzip bytes): 404 when asc reports the day as unavailable."""
    def fetch(url: str, params: dict[str, str], headers: dict[str, str]) -> tuple[int, bytes]:
        fd, path = tempfile.mkstemp(suffix=".tsv.gz", prefix="sales_")
        os.close(fd)
        try:
            r = asc_cli.run(["analytics", "sales", asc_cli.flag("vendor", params["filter[vendorNumber]"]),
                             asc_cli.flag("type", params["filter[reportType]"]),
                             asc_cli.flag("subtype", params["filter[reportSubType]"]),
                             asc_cli.flag("frequency", params["filter[frequency]"]),
                             asc_cli.flag("date", params["filter[reportDate]"]),
                             asc_cli.flag("version", params["filter[version]"]),
                             "--allow-missing", asc_cli.flag("output", path), "--output-format=json"],
                            json_output=False, creds=creds, timeout=120)
            if r.get("missing_binary"):
                return 599, r["error"].encode()
            if not r.get("ok"):
                return r.get("status") or 500, str(r.get("error")).encode()
            meta = r.get("data") or ""
            if '"available":false' in meta.replace(" ", "") or not os.path.getsize(path):
                return 404, b""
            with open(path, "rb") as f:
                return 200, f.read()
        finally:
            os.unlink(path)
    return fetch


def check(report_date: str | None = None, days_back: int = 7, *, fetch: Fetch | None = None,
          config: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    """Find the latest daily SUBSCRIPTION/SUMMARY report (up to `days_back` days) and classify the rate."""
    c = config if config is not None else cfg.load_config()
    key_id, issuer, vendor = c.get("asc_finance_key_id"), c.get("asc_issuer_id"), c.get("asc_vendor_number")
    missing = [k for k, v in (("asc_finance_key_id", key_id), ("asc_issuer_id", issuer),
                              ("asc_vendor_number", vendor)) if not v]
    p8 = cfg.resolve_finance_key_filepath(c)
    if not p8 and fetch is None:
        missing.append("asc_finance_key_filepath")
    if missing:
        return {"ok": False, "error": "missing config: " + ", ".join(missing) +
                " (a Finance-role ASC key; set it with config_set)"}
    headers: dict[str, str] = {}  # auth is asc's job (finance key passed as ASC_* env)
    fetch = fetch or _asc_fetch({"ASC_KEY_ID": str(key_id), "ASC_ISSUER_ID": str(issuer),
                                 "ASC_PRIVATE_KEY_PATH": str(p8)})
    start = _dt.date.fromisoformat(report_date) if report_date else _dt.date.today() - _dt.timedelta(days=1)
    tried = []
    for i in range(max(1, days_back)):
        day = (start - _dt.timedelta(days=i)).isoformat()
        params = {"filter[frequency]": "DAILY", "filter[reportType]": "SUBSCRIPTION",
                  "filter[reportSubType]": "SUMMARY", "filter[reportDate]": day,
                  "filter[vendorNumber]": str(vendor), "filter[version]": "1_3"}
        status, body = fetch(SALES_REPORT, params, headers)
        tried.append(day)
        if status == 403:
            return {"ok": False, "error": "403 Forbidden: the ASC key has no Finance (or Sales) access. Create a key "
                                          "with the Finance role and set asc_finance_key_id/asc_finance_key_filepath."}
        if status == 401:
            return {"ok": False, "error": "401 Unauthorized: finance key id / issuer / .p8 do not match"}
        if status == 404:
            continue  # no report for that day (no sales yet, or not generated)
        if not 200 <= status < 300:
            detail = body.decode("utf-8", "replace")[:300] if body else ""
            return {"ok": False, "error": f"sales report {day}: HTTP {status}" + (f" — {detail}" if detail else "")}
        rows = parse_report(body)
        r = proceeds_ratio(rows)
        verdict = classify(r["ratio"])
        return {"ok": True, "report_date": day, "rows": len(rows), **r, "verdict": verdict,
                "sbp": verdict == "small_business_program",
                "note": None if r["ratio"] is not None else "no US standard-price rows in this report"}
    return {"ok": True, "verdict": "unknown", "sbp": None, "tried": tried,
            "note": "no SUBSCRIPTION report in the window (no sales yet?)"}
