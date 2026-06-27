"""FastMCP server exposing Talos's Jira/GitHub integration tools.

Run as a standalone process (separate from the FastAPI app):

    PYTHONPATH=src python -m integrations.mcp_server

An external MCP host (e.g. Claude Code) connects over HTTP/SSE and drives the
read-ticket -> implement -> open-PR loop. Tool bodies live in ``integrations.tools``.
"""
from mcp.server.fastmcp import FastMCP

from config import cfg
from integrations.tools import MCP_TOOLS

mcp = FastMCP(
    "talos-integrations",
    host=cfg().mcp.host,
    port=cfg().mcp.port,
)

for _fn in MCP_TOOLS:
    mcp.tool()(_fn)


def main() -> None:
    mcp.run(transport=cfg().mcp.transport)


if __name__ == "__main__":
    main()
