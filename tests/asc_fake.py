"""A fake `asc` binary at the subprocess level: asc_cli._exec is replaced, so every ASC call made by
the code under test is recorded as an argv list and answered from a route table (no network)."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable

from appfactory import asc_cli

Reply = dict[str, Any] | list | str | Callable[[list[str], str | None], Any] | None


class FakeAsc:
    """Routes match on the leading command words (flags stripped), longest route first:
        FakeAsc(monkeypatch, {("apps", "list"): {"data": [...]}})
    A reply is the stdout JSON (dict/list), a raw string, a callable(args, stdin) returning one of
    those, or `err(...)` for a failure. Unrouted commands answer {"data": []}."""

    def __init__(self, monkeypatch, routes: dict[tuple[str, ...], Reply] | None = None):
        self.routes = dict(routes or {})
        self.calls: list[list[str]] = []
        self.stdins: list[str | None] = []
        self.envs: list[dict[str, str]] = []
        monkeypatch.setattr(asc_cli, "binary", lambda: "/fake/asc")
        monkeypatch.setattr(asc_cli, "_exec", self._exec)

    @staticmethod
    def words(args: list[str]) -> tuple[str, ...]:
        out: list[str] = []
        for a in args:
            if a.startswith("-"):
                break
            out.append(a)
        return tuple(out)

    def _exec(self, argv, *, timeout, env, stdin):
        args = [a for a in argv[1:] if a != "--api-debug"]
        if args[-2:] == ["--output", "json"]:
            args = args[:-2]
        self.calls.append(args)
        self.stdins.append(stdin)
        self.envs.append(env)
        key = self.words(args)
        reply: Reply = {"data": []}
        for route in sorted(self.routes, key=len, reverse=True):
            if key[:len(route)] == route:
                reply = self.routes[route]
                break
        if callable(reply):
            reply = reply(args, stdin)
        if isinstance(reply, Err):
            return subprocess.CompletedProcess(argv, reply.code, "", reply.stderr())
        out = reply if isinstance(reply, str) else json.dumps(reply)
        return subprocess.CompletedProcess(argv, 0, out, '← HTTP Response" status=200\n')

    def find(self, *words: str) -> list[list[str]]:
        return [c for c in self.calls if self.words(c)[:len(words)] == words]

    @staticmethod
    def flag(args: list[str], name: str) -> str | None:
        pre = f"--{name}="
        return next((a[len(pre):] for a in args if a.startswith(pre)), None)


class Err:
    def __init__(self, message: str, status: int | None = None, code: int = 1):
        self.message, self.status, self.code = message, status, code

    def stderr(self) -> str:
        head = f'level=INFO msg="← HTTP Response" status={self.status}\n' if self.status else ""
        return head + f"Error: {self.message}\n"


def err(message: str, status: int | None = None, code: int = 1) -> Err:
    return Err(message, status, code)
