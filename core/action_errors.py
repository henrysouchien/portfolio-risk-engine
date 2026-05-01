"""Domain errors raised by business actions."""

from __future__ import annotations

from typing import Any


class ActionError(Exception):
    """Base class for action-layer errors."""


class ActionAuthError(ActionError):
    """Raised when action execution fails due to authentication."""


class ActionValidationError(ActionError):
    """Raised when action input is invalid."""


class ActionStructuredValidationError(ActionValidationError):
    """Raised when upstream returns machine-readable validation detail."""

    def __init__(self, message: str, detail: dict[str, Any]) -> None:
        self.detail = dict(detail)
        super().__init__(message)


class IdeaConflictError(ActionValidationError):
    """Raised when a research file already belongs to a different idea."""

    def __init__(self, message: str, detail: dict[str, Any]) -> None:
        self.detail = {
            "existing_idea_id": detail.get("existing_idea_id"),
            "requested_idea_id": detail.get("requested_idea_id"),
            "research_file_id": detail.get("research_file_id"),
        }
        super().__init__(message)


class TemplateSwitchError(ActionValidationError):
    """Raised when a template cannot be applied to the current handoff state."""

    def __init__(
        self,
        message: str,
        detail: dict[str, Any] | None = None,
        *,
        error_type: str,
    ) -> None:
        detail = dict(detail or {})
        self.error_type = error_type
        self.detail = {
            "research_file_id": detail.get("research_file_id"),
        }
        super().__init__(message)


class TemplateIdConflictError(ActionValidationError):
    """Raised when a template id collides with an existing template."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        detail = dict(detail or {})
        self.error_type = "template_id_conflict"
        self.detail = {
            "template_id": detail.get("template_id"),
            "conflict_source": detail.get("conflict_source"),
        }
        super().__init__(message)


class TemplateRequirementsError(ActionValidationError):
    """Raised when a template's finalize gates are not satisfied."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        detail = dict(detail or {})
        self.error_type = "template_requirements_unmet"
        failed_gates = detail.get("failed_gates")
        self.detail = {
            "template_id": detail.get("template_id"),
            "failed_gates": failed_gates if isinstance(failed_gates, dict) else {},
        }
        super().__init__(message)


class ActionNotFoundError(ActionError):
    """Raised when an action target cannot be found."""


class ActionInfrastructureError(ActionError):
    """Raised when action execution fails due to infrastructure."""


class IndustryToolUpstreamError(ActionInfrastructureError):
    """Raised by industry_peer_comparison when FMP upstream fails."""

    def __init__(
        self,
        message: str,
        *,
        ticker: str | None = None,
        upstream: str = "fmp",
    ) -> None:
        super().__init__(message)
        self.ticker = ticker
        self.upstream = upstream


class ActionTypedValidationError(ActionValidationError):
    """Raised when upstream returns a typed, machine-readable validation error."""

    error_type = ""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        self.detail = self._normalize_detail(detail)
        super().__init__(message)

    @staticmethod
    def _normalize_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
        return dict(detail or {})


class ActionTypedNotFoundError(ActionNotFoundError):
    """Raised when upstream returns a typed, machine-readable not-found error."""

    error_type = ""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        self.detail = self._normalize_detail(detail)
        super().__init__(message)

    @staticmethod
    def _normalize_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
        return dict(detail or {})


class MissingStableIdError(ActionTypedNotFoundError):
    """Raised when a patch target stable id cannot be found."""

    error_type = "missing_stable_id"


class DuplicateStableIdError(ActionTypedValidationError):
    """Raised when a patch target stable id matches multiple rows."""

    error_type = "duplicate_stable_id"


class PatchBatchConflictError(ActionTypedValidationError):
    """Raised when patch ops in the same batch conflict with each other."""

    error_type = "patch_batch_conflict"

    @staticmethod
    def _normalize_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(detail or {})
        conflicts = payload.get("conflicts")
        payload["conflicts"] = [
                conflict
                for conflict in conflicts
                if isinstance(conflict, dict)
            ] if isinstance(conflicts, list) else []
        return payload


class InvalidTargetError(ActionTypedValidationError):
    """Raised when a patch op targets an unsupported thesis location."""

    error_type = "invalid_patch_target"


class PatchStaleRetryExhaustedError(ActionTypedValidationError):
    """Raised when optimistic-concurrency retries are exhausted."""

    error_type = "patch_stale_retry_exhausted"

    @staticmethod
    def _normalize_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(detail or {})
        retry_count = payload.get("retry_count")
        try:
            normalized_retry_count = int(retry_count) if retry_count is not None else None
        except (TypeError, ValueError):
            normalized_retry_count = None
        payload["retry_count"] = normalized_retry_count
        return payload


class ModelInsightsNotFoundError(ActionTypedNotFoundError):
    """Raised when model insights for a research file cannot be found."""

    error_type = "model_insights_not_found"


class PriceTargetNotFoundError(ActionTypedNotFoundError):
    """Raised when a price target for a research file cannot be found."""

    error_type = "price_target_not_found"


class PriceTargetIdMismatchError(ActionTypedValidationError):
    """Raised when a requested price target id conflicts with the stored row."""

    error_type = "price_target_id_mismatch"


class ThesisNotFoundError(ActionNotFoundError):
    """Raised when a thesis artifact cannot be found."""


class InvalidSectionError(ActionValidationError):
    """Raised when a thesis section key is not supported."""


class DecisionsLogLockTimeoutError(ActionInfrastructureError):
    """Raised when the thesis decisions-log lock cannot be acquired."""


class LinkResolutionFailedError(ActionValidationError):
    """Raised when thesis scorecard execution cannot resolve model inputs."""


class LinkNotFoundError(ActionNotFoundError):
    """Raised when a thesis link cannot be found."""


class MethodologyNotFoundError(ActionNotFoundError):
    """Raised when a methodology unit name is not in the index (plan #9)."""


class WikiArticleNotFoundError(ActionNotFoundError):
    """Raised when a wiki article (type, slug) is not in the index (plan #9)."""


class MethodologyTagUnknownError(ActionValidationError):
    """Raised when a methodology_tags filter value is not in the approved
    registry (plan #9, `schema/methodology_tag_registry.yaml`)."""


class StrategyCategoryUnknownError(ActionValidationError):
    """Raised when a strategy_bias / strategy field references a category id
    that is not in the live registry (built-in defaults + user config). Plan #5b."""


class BriefPipelineError(ActionError):
    """Raised when the overview brief pipeline cannot produce a brief."""


class BriefNoCandidatesError(ActionError):
    """Raised when the overview brief pipeline has no candidates to compose."""
