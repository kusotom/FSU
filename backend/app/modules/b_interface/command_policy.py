from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class BInterfaceCommandPolicy:
    allow_auto_upgrade: bool = False
    allow_fsu_reboot: bool = False
    allow_real_device_control: bool = False
    dry_run_only: bool = True


@dataclass(frozen=True)
class CommandPolicyDecision:
    allowed: bool
    blocked: bool
    reason: str
    dry_run: bool
    command_name: str
    executed: bool = False


def load_command_policy() -> BInterfaceCommandPolicy:
    return BInterfaceCommandPolicy(
        allow_auto_upgrade=bool(settings.b_interface_allow_auto_upgrade),
        allow_fsu_reboot=bool(settings.b_interface_allow_fsu_reboot),
        allow_real_device_control=bool(settings.b_interface_allow_real_device_control),
        dry_run_only=bool(settings.b_interface_control_dry_run_only),
    )


def evaluate_command_policy(command_name: str, policy: BInterfaceCommandPolicy | None = None) -> CommandPolicyDecision:
    resolved = policy or load_command_policy()
    normalized = (command_name or "").strip().upper()

    if normalized == "SET_FSUREBOOT":
        allowed = resolved.allow_fsu_reboot and resolved.allow_real_device_control
        if not allowed:
            return CommandPolicyDecision(
                allowed=False,
                blocked=True,
                reason="disabled_by_default",
                dry_run=True,
                command_name=normalized,
            )
        return CommandPolicyDecision(
            allowed=True,
            blocked=False,
            reason="accepted_dry_run",
            dry_run=True,
            command_name=normalized,
        )

    if normalized in {"AUTO_UPGRADE", "SET_AUTOUPGRADE", "SET_FSUUPGRADE", "SET_UPGRADE"}:
        allowed = resolved.allow_auto_upgrade and resolved.allow_real_device_control
        if not allowed:
            return CommandPolicyDecision(
                allowed=False,
                blocked=True,
                reason="disabled_by_default",
                dry_run=True,
                command_name=normalized,
            )
        return CommandPolicyDecision(
            allowed=True,
            blocked=False,
            reason="accepted_dry_run",
            dry_run=True,
            command_name=normalized,
        )

    return CommandPolicyDecision(
        allowed=False,
        blocked=True,
        reason="policy_blocked",
        dry_run=True,
        command_name=normalized or "UNKNOWN_CONTROL_COMMAND",
    )
