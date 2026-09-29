# Minimal image to run the MCP server over stdio (used by directories such as Glama for introspection).
# Research tools work in it; building iOS apps needs macOS + Xcode, so use `uvx appfactory@latest` on a Mac.
FROM python:3.12-slim
RUN pip install --no-cache-dir appfactory
ENTRYPOINT ["appfactory-mcp"]
