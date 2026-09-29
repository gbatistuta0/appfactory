"""Every registered tool carries MCP annotations, parameter descriptions and a Returns section."""
import asyncio

from fastmcp import Client

from appfactory.server import mcp


def _tools():
    async def go():
        async with Client(mcp) as c:
            return await c.list_tools()
    return asyncio.run(go())


def test_all_tools_have_annotations_param_descriptions_and_returns():
    tools = _tools()
    assert len(tools) >= 120
    for t in tools:
        a = t.annotations
        assert a is not None and a.title, t.name
        assert None not in (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint), t.name
        assert "Returns" in (t.description or ""), t.name
        for k, v in (t.inputSchema.get("properties") or {}).items():
            assert v.get("description"), f"{t.name}.{k}"


def test_approval_gated_tools_are_destructive_and_not_read_only():
    by = {t.name: t.annotations for t in _tools()}
    assert by["asc_submit_for_review"].destructiveHint and not by["asc_submit_for_review"].readOnlyHint
    assert by["aso_search_hints"].readOnlyHint and by["aso_search_hints"].openWorldHint
