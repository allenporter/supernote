"""Model Context Protocol (MCP) server and OAuth 2.1 / IndieAuth subpackage.

Provides an OAuth 2.1 Authorization Server (`supernote.server.mcp.auth`) mounted on the
main HTTP port (`8080`) and a Streamable HTTP MCP Resource Server
(`supernote.server.mcp.server`) listening on `mcp_port` (`8081`). Together they allow
external AI agents (Claude Desktop, Cursor, custom MCP clients) to securely query
notebooks, run semantic searches, and read OCR transcripts (`supernote.server.mcp.models`).
See `supernote.guides.mcp`.
"""
