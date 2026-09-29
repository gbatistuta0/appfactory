"""Chat-side setup for the MCP tools: status, services, non-secret keys, approvals.

Secrets never go through here (the model would see them): they are entered on the local page that
setup_gui starts. None of this is service-gated and it works with no config file.
"""

from __future__ import annotations

import os
from typing import Any

from . import cli
from . import config as cfg

CREDENTIALS_HINT = "call setup_credentials([...]) and ask the user to type the keys in the browser page"


def _chosen(c: dict[str, Any]) -> set[str]:
    return cfg.enabled_services(c) if "services" in c else {"research"}


# Real dependencies only: turning a service on also turns these on.
REQUIRES: dict[str, list[str]] = {"ai": ["supabase"], "maestro": ["xcode"]}

ASK_SERVICES = ("Ask about EACH service separately (one yes/no per service, with its description); never bundle "
                "services into one choice. The only links are REQUIRES (e.g. ai needs supabase). If your question UI "
                "caps the number of options, split them over several questions. Then call setup_services(enable=[...]).")


def status() -> dict[str, Any]:
    c = cfg.load_config()
    chosen = "services" in c
    enabled = _chosen(c)
    missing_bins = cli.missing_binaries(enabled)
    services, nxt = [], []
    if not chosen:
        nxt.append(ASK_SERVICES)
    for name, spec in cfg.SERVICES.items():
        row: dict[str, Any] = {"name": name, "description": spec["description"], "enabled": name in enabled,
                               "requires": REQUIRES.get(name, [])}
        if name in enabled:
            keys = []
            for k in spec["keys"] + spec.get("optional_keys", []):
                keys.append({"key": k, "what": cfg.KNOWN_KEYS.get(k, k), "secret": k in cfg.SECRET_KEYS,
                             "optional": k in spec.get("optional_keys", []), "state": "set" if c.get(k) else "missing"})
            row["keys"] = keys
            row["binaries"] = [{"name": b, "state": "missing" if b in missing_bins else "ok",
                                **({"install": h} if b in missing_bins else {})}
                               for b, h in spec["binaries"].items()]
            need = [k for k in keys if k["state"] == "missing" and not k["optional"]]
            plain = [k["key"] for k in need if not k["secret"]]
            secret = [k["key"] for k in need if k["secret"]]
            if plain:
                nxt.append(f"{name}: ask the user for {', '.join(plain)} and call setup_set(key, value) for each.")
            if secret:
                nxt.append(f"{name}: secrets {', '.join(secret)} are missing; {CREDENTIALS_HINT}.")
            for b in row["binaries"]:
                if b["state"] == "missing":
                    nxt.append(f"{name}: install {b['name']} (`{b['install']}`).")
        services.append(row)
    if chosen and not nxt:
        nxt.append("Setup is complete for the chosen services.")
    return {"ok": True, "config_path": str(cfg.CONFIG_PATH), "config_exists": cfg.CONFIG_PATH.exists(),
            "services_chosen": chosen, "services": services,
            "approvals": c.get("approvals", "required") if c.get("approvals") in ("required", "off") else "required",
            "next": nxt}


def set_services(enable: list[str] | None, disable: list[str] | None) -> dict[str, Any]:
    enable, disable = enable or [], disable or []
    for n in [*enable, *disable]:
        if n not in cfg.SERVICES:
            return {"ok": False, "error": f"unknown service {n!r}; choose from: {', '.join(cfg.SERVICES)}"}
    if any(cfg.SERVICES[n].get("always_on") for n in disable):
        return {"ok": False, "error": "research is always on"}
    c = cfg.load_config()
    new = (_chosen(c) | set(enable)) - set(disable)
    for n in list(new):
        new |= set(REQUIRES.get(n, []))
    blocked = [f"{n} needs {r}" for n in new for r in REQUIRES.get(n, []) if r in disable]
    if blocked:
        return {"ok": False, "error": "; ".join(blocked)}
    c["services"] = [n for n in cfg.SERVICES if n in new or cfg.SERVICES[n].get("always_on")]
    cfg.save_config(c)
    return status()


def set_key(key: str, value: str) -> dict[str, Any]:
    if key in cfg.SECRET_KEYS:
        return {"ok": False, "error": f"{key} is a secret and must not pass through the chat: {CREDENTIALS_HINT}"}
    if key not in cfg.KNOWN_KEYS:
        return {"ok": False, "error": f"unknown key {key!r}"}
    c = cfg.load_config()
    value = (value or "").strip()
    if value:
        c[key] = os.path.expanduser(value) if key.endswith("filepath") else value
    else:
        c.pop(key, None)
    cfg.save_config(c)
    return {"ok": True, "key": key, "state": "set" if value else "missing"}


def set_approvals(mode: str) -> dict[str, Any]:
    if mode == "required":
        c = cfg.load_config()
        c["approvals"] = "required"
        cfg.save_config(c)
        return {"ok": True, "approvals": "required"}
    if mode == "off":
        return {"ok": False, "error": "turning approvals off lets an agent make irreversible live changes on its own, "
                                      "so only the human can do it: call setup_credentials() and ask the user to "
                                      "switch the Safety toggle in the browser page"}
    return {"ok": False, "error": "mode must be 'required' (or 'off', which only the human can set)"}


def required() -> dict[str, Any] | None:
    """A `setup_required` refusal for the run tools when setup has not been done yet, else None.
    Not chosen services or a missing required key of an enabled service both count."""
    st = status()
    todo = [line for line in st["next"] if not line.startswith("Setup is complete") and "install " not in line]
    if st["services_chosen"] and not todo:
        return None
    return {"ok": False, "setup_required": True,
            "error": "AppFactory is not set up yet. Do the setup with the user right now, then continue the run.",
            "next": todo, "how": "setup_status() -> ask the user in chat which services they want (research needs "
                                 "nothing) -> setup_services(enable=[...]) -> setup_set(key, value) for non-secret "
                                 "keys -> setup_credentials([...]) for secrets (the user fills a browser form) -> "
                                 "setup_status() shows no missing keys -> continue with run_options()."}
