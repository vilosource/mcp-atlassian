# Developer Guide

This guide explains how to extend **MCP Atlassian** with new Model Context Protocol (MCP) tools.

## Repository Overview

- **`src/mcp_atlassian/servers`** contains the FastMCP server implementations.
- `main.py` defines the top-level server (`main_mcp`) and mounts service-specific servers:
  - **`jira_mcp`** (Jira tools) in `servers/jira.py`.
  - **`confluence_mcp`** (Confluence tools) in `servers/confluence.py`.
- Tools are registered with these servers using the `@<server>.tool` decorator.

## Adding a New Tool

1. **Choose the target service** – Jira or Confluence – and open the corresponding file in `src/mcp_atlassian/servers/`.
2. **Define an async function** decorated with `@jira_mcp.tool` or `@confluence_mcp.tool`.
   - Include tags such as `{"jira", "read"}` or `{"confluence", "write"}` for filtering and read-only mode support.
3. **Retrieve a service client** using the helpers in `servers/dependencies.py`:
   ```python
   from mcp_atlassian.servers.dependencies import get_jira_fetcher

   @jira_mcp.tool(tags={"jira", "read"})
   async def example_tool(ctx: Context, issue_key: Annotated[str, Field(...)]) -> str:
       jira = await get_jira_fetcher(ctx)
       issue = jira.get_issue(issue_key)
       return json.dumps(issue.to_simplified_dict(), indent=2, ensure_ascii=False)
   ```
4. **Document the tool** with a Google‑style docstring describing arguments, return values, and errors.
5. **Write unit tests** under `tests/unit/servers` to ensure the tool works and is registered.
6. **Run the mandatory workflow** before committing:
   ```bash
   uv sync --frozen --all-extras --dev
   pre-commit install
   pre-commit run --all-files
   uv run pytest -k 'not real_api_validation'
   ```

## Tool Filtering

Tools are filtered based on:
- The `ENABLED_TOOLS` environment variable (comma‑separated names).
- The server's read‑only mode (`READ_ONLY_MODE=true` disables tools tagged with `"write"`).

`main_mcp` automatically excludes tools if the corresponding service is not configured.

## Example Pull Request Workflow

1. Create your feature branch and implement the tool.
2. Add or update tests.
3. Run the workflow above until all checks pass.
4. Commit with appropriate trailers (e.g., `Reported-by:` or `Github-Issue:`) and open a pull request.

For more details on contributing, see [CONTRIBUTING.md](CONTRIBUTING.md).
