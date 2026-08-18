"""Action Registry 中央能力约束。

NOT_IMPLEMENTED 不得伪装成 Executed / Result / Strategy Memory。
这是中央 invariant，不是 Sandbox 特判。
"""

from __future__ import annotations

from typing import Any

from app.services.action_registry import ACTION_REGISTRY

IMPLEMENTED = "IMPLEMENTED"
READ_ONLY = "READ_ONLY"
MANUAL_ONLY = "MANUAL_ONLY"
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
DISABLED = "DISABLED"

BLOCKED_NOT_IMPLEMENTED = "BLOCKED_NOT_IMPLEMENTED"

_METHOD_TO_CAPABILITY = {
    "human_execute": MANUAL_ONLY,
    "platform_or_human": IMPLEMENTED,
    "store_execute": MANUAL_ONLY,
    "not_implemented": NOT_IMPLEMENTED,
    "disabled": DISABLED,
    "read_only": READ_ONLY,
}


class ActionCapabilityError(Exception):
    def __init__(self, action_type: str, capability: str, code: str = BLOCKED_NOT_IMPLEMENTED):
        self.action_type = action_type
        self.capability = capability
        self.code = code
        super().__init__(f"{code}: {action_type} capability={capability}")


def execution_capability(action_type: str) -> str:
    kind = str(action_type or "").strip()
    if kind in ACTION_REGISTRY:
        method = str(ACTION_REGISTRY[kind].get("execution_method") or "")
        return _METHOD_TO_CAPABILITY.get(method, MANUAL_ONLY)
    return MANUAL_ONLY


def is_not_implemented(action_type: str) -> bool:
    return execution_capability(action_type) == NOT_IMPLEMENTED


def assert_action_executable(action_type: str) -> None:
    capability = execution_capability(action_type)
    if capability == NOT_IMPLEMENTED:
        raise ActionCapabilityError(action_type, capability, BLOCKED_NOT_IMPLEMENTED)
    if capability == DISABLED:
        raise ActionCapabilityError(action_type, capability, "BLOCKED_DISABLED")
    if capability == READ_ONLY:
        raise ActionCapabilityError(action_type, capability, "BLOCKED_READ_ONLY")


def blocked_payload(action_type: str, *, tool: str = "") -> dict[str, Any]:
    capability = execution_capability(action_type)
    return {
        "ok": False,
        "code": BLOCKED_NOT_IMPLEMENTED,
        "tool": tool,
        "action_type": action_type,
        "execution_capability": capability,
        "message": f"{action_type} 尚未实现，不能进入执行、Result 或 Strategy Memory。",
        "executed": False,
    }
