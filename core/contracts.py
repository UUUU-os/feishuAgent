from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class AIWorkflowInput:
    """Stable input contract from runtime services to the AI layer."""

    workflow_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    allow_write: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AIWorkflowInput":
        """Build the contract from a loose runtime dictionary."""

        return cls(
            workflow_type=str(data.get("workflow_type", "")),
            payload=dict(data.get("payload") or {}),
            trace_id=str(data.get("trace_id", "")),
            allow_write=bool(data.get("allow_write", False)),
        )


@dataclass(slots=True)
class AIWorkflowResult:
    """Stable output contract returned by the AI layer."""

    trace_id: str
    workflow_type: str
    status: str
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AIWorkflowResult":
        """Build the contract from a loose runtime dictionary."""

        return cls(
            trace_id=str(data.get("trace_id", "")),
            workflow_type=str(data.get("workflow_type", "")),
            status=str(data.get("status", "")),
            summary=str(data.get("summary", "")),
            data=dict(data.get("data") or {}),
            evidence_refs=list(data.get("evidence_refs") or []),
            metrics=dict(data.get("metrics") or {}),
            errors=[str(error) for error in data.get("errors") or []],
        )
