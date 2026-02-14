"""
Tool Execution Engine for Kart Orchestrator

Provides governance-checked tool access for Kart agent.
All operations validated through gate.py Dual Commit system.

Tools: read_file, write_file, edit_file, bash_exec, grep_search, glob_find,
       task_create, task_update, task_list

GOVERNANCE: Every tool call logged and gated per AIONIC_CONTINUITY v5.1
AUTHOR: Kart Orchestration System
VERSION: 1.0
CHECKSUM: ΔΣ=42
"""

import re
import glob as glob_module
import subprocess
import requests
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any
from datetime import datetime

# Core imports
from core import agent_registry, gate, knowledge

# Trust hierarchy
TRUST_HIERARCHY = ["WORKER", "OPERATOR", "ENGINEER"]


@dataclass
class ToolDefinition:
    """Tool definition with permissions and executor."""
    name: str
    description: str
    parameters: Dict[str, str]  # JSON schema-style
    required_trust: str  # WORKER, OPERATOR, or ENGINEER
    governance_type: str  # state, external, config
    executor: Callable


# Global tool registry
TOOL_REGISTRY: Dict[str, ToolDefinition] = {}


def register_tool(definition: ToolDefinition):
    """Register a tool in the registry."""
    TOOL_REGISTRY[definition.name] = definition


def _check_permission(agent_trust: str, required_trust: str) -> bool:
    """Check if agent trust level meets requirement."""
    try:
        agent_level = TRUST_HIERARCHY.index(agent_trust)
        required_level = TRUST_HIERARCHY.index(required_trust)
        return agent_level >= required_level
    except ValueError:
        return False


def list_tools(agent: str, username: str) -> List[Dict[str, Any]]:
    """List tools available to agent based on trust level."""
    agent_info = agent_registry.get_agent(username, agent)
    if not agent_info:
        return []

    agent_trust = agent_info.get("trust_level", "WORKER")
    available = []

    for tool_name, tool_def in TOOL_REGISTRY.items():
        if _check_permission(agent_trust, tool_def.required_trust):
            available.append({
                "name": tool_def.name,
                "description": tool_def.description,
                "parameters": tool_def.parameters,
                "required_trust": tool_def.required_trust
            })

    return available


def execute(tool_name: str, params: Dict[str, Any], agent: str, username: str) -> Dict[str, Any]:
    """
    Execute a tool with governance checks.

    Args:
        tool_name: Name of tool to execute
        params: Tool parameters
        agent: Agent name (e.g., "kart")
        username: User name

    Returns:
        {
            "success": bool,
            "result": any,
            "error": str (if failed),
            "governance_status": str
        }
    """
    # 1. Validate tool exists
    if tool_name not in TOOL_REGISTRY:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(TOOL_REGISTRY.keys())
        }

    tool_def = TOOL_REGISTRY[tool_name]

    # 2. Validate agent trust level
    agent_info = agent_registry.get_agent(username, agent)
    if not agent_info:
        return {
            "success": False,
            "error": f"Unknown agent: {agent}"
        }

    agent_trust = agent_info.get("trust_level", "WORKER")

    if not _check_permission(agent_trust, tool_def.required_trust):
        return {
            "success": False,
            "error": f"Insufficient trust level. Required: {tool_def.required_trust}, Agent has: {agent_trust}"
        }

    # 3. Execute tool
    try:
        result = tool_def.executor(**params, agent=agent, username=username)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": f"Tool execution failed: {str(e)}"
        }


# ============================================================================
# TOOL IMPLEMENTATIONS
# ============================================================================

def _tool_read_file(file_path: str, agent: str, username: str) -> Dict[str, Any]:
    """Read file contents with governance check."""
    # Governance check
    decision = gate.validate_modification(
        mod_type="state",
        target=f"file_read:{file_path}",
        new_value="",  # Read is non-destructive
        reason=f"Agent {agent} reading {file_path}",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": f"Governance denied: {decision.get('reason', 'Unknown')}",
            "governance_status": "DENIED"
        }

    # Execute
    try:
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": "File not found"}

        content = path.read_text(encoding="utf-8")

        # Log access
        try:
            knowledge.log_file_access(username, agent, file_path, "read")
        except:
            pass  # Non-fatal if logging fails

        return {
            "success": True,
            "result": {
                "content": content,
                "size": len(content),
                "path": str(path.absolute())
            },
            "governance_status": "APPROVED"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Read failed: {str(e)}"
        }


def _tool_write_file(file_path: str, content: str, agent: str, username: str) -> Dict[str, Any]:
    """Write file with governance check (requires human approval)."""
    # Governance check - REQUIRE_HUMAN
    decision = gate.validate_modification(
        mod_type="external",
        target=f"file_write:{file_path}",
        new_value=content[:200] + "..." if len(content) > 200 else content,
        reason=f"Agent {agent} writing {file_path} ({len(content)} bytes)",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance check required - queued for human approval",
            "governance_status": "PENDING_APPROVAL",
            "request_id": decision.get("request_id")
        }

    # Execute
    try:
        path = Path(file_path)

        # Backup existing file
        if path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            path.rename(backup_path)

        path.write_text(content, encoding="utf-8")

        # Log access
        try:
            knowledge.log_file_access(username, agent, file_path, "write")
        except:
            pass

        return {
            "success": True,
            "result": {
                "path": str(path.absolute()),
                "size": len(content)
            },
            "governance_status": "APPROVED"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Write failed: {str(e)}"
        }


def _tool_edit_file(file_path: str, old_text: str, new_text: str, agent: str, username: str) -> Dict[str, Any]:
    """Edit file with exact string replacement (requires human approval)."""
    # Governance check
    decision = gate.validate_modification(
        mod_type="external",
        target=f"file_edit:{file_path}",
        new_value=f"Replace '{old_text[:50]}...' with '{new_text[:50]}...'",
        reason=f"Agent {agent} editing {file_path}",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance check required - queued for human approval",
            "governance_status": "PENDING_APPROVAL",
            "request_id": decision.get("request_id")
        }

    # Execute
    try:
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": "File not found"}

        content = path.read_text(encoding="utf-8")

        if old_text not in content:
            return {
                "success": False,
                "error": f"Text not found in file: '{old_text[:50]}...'"
            }

        # Backup
        backup_path = path.with_suffix(path.suffix + ".bak")
        path.rename(backup_path)

        # Replace
        new_content = content.replace(old_text, new_text)
        path.write_text(new_content, encoding="utf-8")

        # Log
        try:
            knowledge.log_file_access(username, agent, file_path, "edit")
        except:
            pass

        return {
            "success": True,
            "result": {
                "path": str(path.absolute()),
                "replacements": content.count(old_text),
                "backup": str(backup_path)
            },
            "governance_status": "APPROVED"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Edit failed: {str(e)}"
        }


def _tool_bash_exec(command: str, agent: str, username: str) -> Dict[str, Any]:
    """Execute bash command with governance check."""
    # Detect destructive commands
    destructive_patterns = [r'\brm\b', r'\bmv\b', r'>>', r'>', r'\|']
    is_destructive = any(re.search(pattern, command) for pattern in destructive_patterns)

    gov_type = "external" if is_destructive else "state"

    # Governance check
    decision = gate.validate_modification(
        mod_type=gov_type,
        target=f"bash_exec:{command[:50]}",
        new_value="",
        reason=f"Agent {agent} executing: {command}",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance check required" if is_destructive else "Governance denied",
            "governance_status": "PENDING_APPROVAL" if is_destructive else "DENIED",
            "request_id": decision.get("request_id")
        }

    # Execute
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )

        return {
            "success": result.returncode == 0,
            "result": {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            },
            "governance_status": "APPROVED"
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out (60s limit)"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Execution failed: {str(e)}"
        }


def _tool_grep_search(pattern: str, path: str, agent: str, username: str) -> Dict[str, Any]:
    """Search files with regex pattern."""
    # Governance check
    decision = gate.validate_modification(
        mod_type="state",
        target=f"grep_search:{path}",
        new_value=pattern,
        reason=f"Agent {agent} searching {path} for '{pattern}'",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance denied",
            "governance_status": "DENIED"
        }

    # Execute
    try:
        matches = []
        path_obj = Path(path)

        if path_obj.is_file():
            # Search single file
            with open(path_obj, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    if re.search(pattern, line):
                        matches.append({
                            "file": str(path_obj),
                            "line": line_num,
                            "content": line.strip()
                        })
        elif path_obj.is_dir():
            # Search directory recursively
            for file_path in path_obj.rglob("*"):
                if file_path.is_file():
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for line_num, line in enumerate(f, 1):
                                if re.search(pattern, line):
                                    matches.append({
                                        "file": str(file_path),
                                        "line": line_num,
                                        "content": line.strip()
                                    })
                    except:
                        continue  # Skip files that can't be read

        return {
            "success": True,
            "result": {
                "matches": matches,
                "count": len(matches),
                "pattern": pattern
            },
            "governance_status": "APPROVED"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Search failed: {str(e)}"
        }


def _tool_glob_find(pattern: str, agent: str, username: str) -> Dict[str, Any]:
    """Find files matching glob pattern."""
    # Governance check
    decision = gate.validate_modification(
        mod_type="state",
        target=f"glob_find:{pattern}",
        new_value="",
        reason=f"Agent {agent} finding files: {pattern}",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance denied",
            "governance_status": "DENIED"
        }

    # Execute
    try:
        files = glob_module.glob(pattern, recursive=True)
        files = [str(Path(f).absolute()) for f in files]

        return {
            "success": True,
            "result": {
                "files": files,
                "count": len(files),
                "pattern": pattern
            },
            "governance_status": "APPROVED"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Glob failed: {str(e)}"
        }


def _tool_task_create(subject: str, description: str, agent: str, username: str) -> Dict[str, Any]:
    """Create a new task."""
    # Import task module
    try:
        from core import kart_tasks
    except ImportError:
        return {
            "success": False,
            "error": "Task system not available"
        }

    # Governance check
    decision = gate.validate_modification(
        mod_type="state",
        target=f"task_create:{subject}",
        new_value=description[:100],
        reason=f"Agent {agent} creating task: {subject}",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance denied",
            "governance_status": "DENIED"
        }

    # Execute
    try:
        task_id = kart_tasks.create_task(username, subject, description, agent)
        return {
            "success": True,
            "result": {
                "task_id": task_id,
                "subject": subject
            },
            "governance_status": "APPROVED"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Task creation failed: {str(e)}"
        }


def _tool_task_update(task_id: str, status: str, agent: str, username: str) -> Dict[str, Any]:
    """Update task status."""
    try:
        from core import kart_tasks
    except ImportError:
        return {
            "success": False,
            "error": "Task system not available"
        }

    # Governance check
    decision = gate.validate_modification(
        mod_type="state",
        target=f"task_update:{task_id}",
        new_value=status,
        reason=f"Agent {agent} updating task {task_id} to {status}",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance denied",
            "governance_status": "DENIED"
        }

    # Execute
    try:
        success = kart_tasks.update_task(username, task_id, status, agent)
        return {
            "success": success,
            "result": {
                "task_id": task_id,
                "status": status
            },
            "governance_status": "APPROVED"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Task update failed: {str(e)}"
        }


def _tool_task_list(agent: str, username: str) -> Dict[str, Any]:
    """List all tasks."""
    try:
        from core import kart_tasks
    except ImportError:
        return {
            "success": False,
            "error": "Task system not available"
        }

    # Governance check
    decision = gate.validate_modification(
        mod_type="state",
        target="task_list",
        new_value="",
        reason=f"Agent {agent} listing tasks",
        authority="ai"
    )

    if not decision["approved"]:
        return {
            "success": False,
            "error": "Governance denied",
            "governance_status": "DENIED"
        }

    # Execute
    try:
        tasks = kart_tasks.list_tasks(username, agent)
        return {
            "success": True,
            "result": {
                "tasks": tasks,
                "count": len(tasks)
            },
            "governance_status": "APPROVED"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Task list failed: {str(e)}"
        }


def _tool_delegate_to_agent(target_agent: str, task: str, agent: str, username: str) -> Dict[str, Any]:
    """
    Delegate a task to another agent via conversational chat API.

    This enables any LLM to offload work to specialized agents:
    - Claude Code → Kart (code analysis, file operations)
    - Willow → Kart (complex routing decisions)
    - Any agent → Jane (SAFE-compliant responses)
    - Cross-agent collaboration patterns

    Args:
        target_agent: Agent to delegate to (kart, willow, jane, etc.)
        task: Task description to send to target agent
        agent: Requesting agent name
        username: User name

    Returns:
        Response from target agent with tool call results
    """
    # Normalize agent name to lowercase
    target_agent = target_agent.lower()

    # Validate target agent exists
    target_info = agent_registry.get_agent(username, target_agent)
    if not target_info:
        return {
            "success": False,
            "error": f"Target agent '{target_agent}' not found. Available agents: willow, kart, jane, riggs, ada, gerald, steve"
        }

    # Call target agent via chat API
    try:
        response = requests.post(
            "http://localhost:8420/api/agents/chat/" + target_agent,
            json={"message": task},
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()

            # Log the delegation
            try:
                knowledge.log_observation(
                    username=username,
                    agent=agent,
                    observation_type="delegation",
                    content=f"Delegated to {target_agent}: {task[:100]}..."
                )
            except:
                pass

            return {
                "success": True,
                "result": {
                    "response": result.get("response", ""),
                    "target_agent": target_agent,
                    "provider": result.get("provider", "unknown"),
                    "tier": result.get("tier", "unknown"),
                    "tool_calls": result.get("tool_calls", [])
                },
                "governance_status": "APPROVED"
            }
        else:
            return {
                "success": False,
                "error": f"Agent chat API returned status {response.status_code}: {response.text[:200]}"
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": f"Delegation to {target_agent} timed out after 120 seconds"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Delegation failed: {str(e)}"
        }


# ============================================================================
# TOOL REGISTRATION
# ============================================================================

def init_tools():
    """Initialize and register all tools."""

    # Read operations (WORKER level)
    register_tool(ToolDefinition(
        name="read_file",
        description="Read file contents",
        parameters={"file_path": "string"},
        required_trust="WORKER",
        governance_type="state",
        executor=_tool_read_file
    ))

    register_tool(ToolDefinition(
        name="grep_search",
        description="Search files with regex pattern",
        parameters={"pattern": "string", "path": "string"},
        required_trust="WORKER",
        governance_type="state",
        executor=_tool_grep_search
    ))

    register_tool(ToolDefinition(
        name="glob_find",
        description="Find files matching glob pattern",
        parameters={"pattern": "string"},
        required_trust="WORKER",
        governance_type="state",
        executor=_tool_glob_find
    ))

    register_tool(ToolDefinition(
        name="task_list",
        description="List all tasks",
        parameters={},
        required_trust="WORKER",
        governance_type="state",
        executor=_tool_task_list
    ))

    register_tool(ToolDefinition(
        name="delegate_to_agent",
        description="Delegate a task to another agent. Use this to offload work to specialized agents (kart for file ops, jane for SAFE responses, etc.)",
        parameters={"target_agent": "string", "task": "string"},
        required_trust="WORKER",
        governance_type="state",
        executor=_tool_delegate_to_agent
    ))

    # Task management (OPERATOR level)
    register_tool(ToolDefinition(
        name="task_create",
        description="Create a new task",
        parameters={"subject": "string", "description": "string"},
        required_trust="OPERATOR",
        governance_type="state",
        executor=_tool_task_create
    ))

    register_tool(ToolDefinition(
        name="task_update",
        description="Update task status",
        parameters={"task_id": "string", "status": "string"},
        required_trust="OPERATOR",
        governance_type="state",
        executor=_tool_task_update
    ))

    # Write operations (OPERATOR level, requires human approval)
    register_tool(ToolDefinition(
        name="write_file",
        description="Write content to file (requires human approval)",
        parameters={"file_path": "string", "content": "string"},
        required_trust="OPERATOR",
        governance_type="external",
        executor=_tool_write_file
    ))

    register_tool(ToolDefinition(
        name="edit_file",
        description="Edit file with exact replacement (requires human approval)",
        parameters={"file_path": "string", "old_text": "string", "new_text": "string"},
        required_trust="OPERATOR",
        governance_type="external",
        executor=_tool_edit_file
    ))

    # Command execution (ENGINEER level)
    register_tool(ToolDefinition(
        name="bash_exec",
        description="Execute bash command (destructive commands require human approval)",
        parameters={"command": "string"},
        required_trust="ENGINEER",
        governance_type="external",
        executor=_tool_bash_exec
    ))


# Initialize tools on module load
init_tools()
