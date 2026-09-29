"""cpp.py — Custom Product Pages orchestration through ASCClient and a fake `asc` (no network)."""
from asc_fake import FakeAsc, err

from appfactory import asc, cpp


def _client(monkeypatch, fail_on: tuple[str, ...] | None = None):
    n = {"i": 0}

    def made(args, stdin):
        n["i"] += 1
        return {"data": {"id": f"id{n['i']}"}}
    routes = {("product-pages", "custom-pages", "create"): made,
              ("product-pages", "custom-pages", "update"): made,
              ("product-pages", "custom-pages", "versions", "create"): made,
              ("product-pages", "custom-pages", "localizations", "create"): made}
    if fail_on:
        routes[fail_on] = err(f"boom:{' '.join(fail_on)}", status=409)
    fake = FakeAsc(monkeypatch, routes)
    return asc.ASCClient(), fake


def test_cpp_url_format():
    assert cpp.cpp_url("6749999999", "abc-uuid") == "https://apps.apple.com/app/id6749999999?ppid=abc-uuid"


def test_build_cpps_chains_endpoints_per_theme(monkeypatch):
    c, fake = _client(monkeypatch)
    out = cpp.build_cpps(c, app_id="APP1", app_apple_id="6749999999",
                         themes=[{"name": "sleep", "locale": "en-US"}, {"name": "focus"}])
    assert out["ok"] is True
    assert len(out["pages"]) == 2
    # per theme: create (+ visible) → version → localization
    assert len(fake.find("product-pages", "custom-pages", "create")) == 2
    assert all("--visible=true" in u for u in fake.find("product-pages", "custom-pages", "update"))
    assert len(fake.find("product-pages", "custom-pages", "versions", "create")) == 2
    locs = fake.find("product-pages", "custom-pages", "localizations", "create")
    assert [FakeAsc.flag(x, "locale") for x in locs] == ["en-US", "en-US"]
    # url is built with the theme's CPP id
    sleep = next(p for p in out["pages"] if p["theme"] == "sleep")
    assert sleep["url"].endswith(f"?ppid={sleep['id']}")
    assert FakeAsc.flag(fake.find("product-pages", "custom-pages", "create")[0], "app") == "APP1"


def test_build_cpps_records_failure_step_and_continues(monkeypatch):
    c, _ = _client(monkeypatch, fail_on=("product-pages", "custom-pages", "versions", "create"))
    out = cpp.build_cpps(c, "APP1", "674", themes=[{"name": "sleep"}])
    assert out["ok"] is False
    assert out["pages"][0]["step"] == "version" and out["pages"][0]["ok"] is False
