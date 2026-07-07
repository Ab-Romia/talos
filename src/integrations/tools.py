"""Single source of truth for tool functions, shared by both "brains".

``MCP_TOOLS``   — exposed by the FastMCP server to an external coding agent,
                  covering all four domains: external apps (Jira + GitHub),
                  filesystem, chat, and RAG — still pinned to the configured
                  bot scope.
``AGENT_TOOLS`` — bound to the embedded LangChain agent that powers the Slack bot.

Each entry is a plain async (or sync) function whose type hints + docstring become the
tool schema/description in both FastMCP and LangChain. No definition is duplicated.
"""
from integrations.github.client import (
    github_create_branch,
    github_get_file,
    github_open_pr,
    github_put_file,
)
from integrations.jira.client import (
    jira_comment,
    jira_get_issue,
    jira_list_issues,
    jira_transition,
)
from integrations.talos_tools import (
    rag_ask,
    talos_get_file,
    talos_list_files,
    talos_post_message,
    talos_read_messages,
)

# Tools the external coding agent uses to read tickets, write code, and open PRs.
# All four Talos domains are exposed — external apps (Jira/GitHub), filesystem,
# chat, and RAG — with every Talos tool pinned to the configured bot scope.
MCP_TOOLS = [
    jira_list_issues,
    jira_get_issue,
    jira_comment,
    jira_transition,
    github_get_file,
    github_create_branch,
    github_put_file,
    github_open_pr,
    talos_list_files,
    talos_get_file,
    rag_ask,
    talos_read_messages,
    talos_post_message,
]

# Tools the embedded Slack agent binds — mirrors what Talos does in the app.
AGENT_TOOLS = [
    rag_ask,
    talos_post_message,
    talos_read_messages,
    talos_list_files,
    talos_get_file,
]
