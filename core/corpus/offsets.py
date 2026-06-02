from __future__ import annotations

from core.corpus.types import InvalidInputError


VALID_OFFSET_FRAMES = frozenset({"auto", "document", "scoped"})


def slice_scoped_text_with_offsets(
    text: str,
    char_start: int | None,
    char_end: int | None,
    *,
    scope_start: int,
    scope_end: int,
    offset_frame: str = "auto",
    scope_name: str = "selected scope",
) -> tuple[str, int, int]:
    """Slice text while preserving document-global citation coordinates."""
    frame = _normalize_offset_frame(offset_frame)
    if scope_end < scope_start:
        raise InvalidInputError(f"{scope_name} has invalid offset bounds")

    if char_start is None and char_end is None:
        return text, scope_start, scope_end

    _validate_requested_bounds(char_start, char_end)

    document_candidate = _document_frame_candidate(
        text,
        char_start,
        char_end,
        scope_start=scope_start,
        scope_end=scope_end,
    )
    scoped_candidate = _scoped_frame_candidate(
        text,
        char_start,
        char_end,
        scope_start=scope_start,
    )

    if frame == "document":
        if document_candidate is None:
            raise InvalidInputError(
                f"char_start/char_end must be document offsets contained within {scope_name}"
            )
        return document_candidate
    if frame == "scoped":
        if scoped_candidate is None:
            raise InvalidInputError(
                f"char_start/char_end must be offsets within {scope_name}"
            )
        return scoped_candidate

    if document_candidate is not None and _prefer_document_frame(
        char_start,
        char_end,
        scope_start=scope_start,
        scoped_length=len(text),
    ):
        return document_candidate
    if scoped_candidate is not None:
        return scoped_candidate
    if document_candidate is not None:
        return document_candidate

    raise InvalidInputError(
        f"char_start/char_end do not select content inside {scope_name}; "
        "use document offsets from search hits, use offset_frame='scoped' for "
        "scope-relative offsets, or omit the scope when slicing a broader span"
    )


def _normalize_offset_frame(offset_frame: str) -> str:
    frame = str(offset_frame or "auto").strip().lower()
    if frame not in VALID_OFFSET_FRAMES:
        valid = ", ".join(sorted(VALID_OFFSET_FRAMES))
        raise InvalidInputError(f"offset_frame must be one of: {valid}")
    return frame


def _validate_requested_bounds(char_start: int | None, char_end: int | None) -> None:
    if char_start is not None and char_start < 0:
        raise InvalidInputError("char_start and char_end must be >= 0")
    if char_end is not None and char_end < 0:
        raise InvalidInputError("char_start and char_end must be >= 0")
    if char_start is not None and char_end is not None:
        if char_end < char_start:
            raise InvalidInputError("char_end must be >= char_start")
        if char_end == char_start:
            raise InvalidInputError("char_end must be > char_start")


def _document_frame_candidate(
    text: str,
    char_start: int | None,
    char_end: int | None,
    *,
    scope_start: int,
    scope_end: int,
) -> tuple[str, int, int] | None:
    if scope_end - scope_start != len(text):
        return None

    start = scope_start if char_start is None else char_start
    end = scope_end if char_end is None else char_end
    if start < scope_start or end > scope_end or end <= start:
        return None

    local_start = start - scope_start
    local_end = end - scope_start
    return text[local_start:local_end], start, end


def _scoped_frame_candidate(
    text: str,
    char_start: int | None,
    char_end: int | None,
    *,
    scope_start: int,
) -> tuple[str, int, int] | None:
    start = 0 if char_start is None else char_start
    end = len(text) if char_end is None else char_end
    if start < 0 or end > len(text) or end <= start:
        return None
    return text[start:end], scope_start + start, scope_start + end


def _prefer_document_frame(
    char_start: int | None,
    char_end: int | None,
    *,
    scope_start: int,
    scoped_length: int,
) -> bool:
    if scope_start == 0:
        return True
    if char_start is not None and char_start >= scope_start:
        return True
    if char_end is not None and char_end > scoped_length:
        return True
    return False
