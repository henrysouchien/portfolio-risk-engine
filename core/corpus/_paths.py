from __future__ import annotations

import os
from pathlib import Path


def normalize_corpus_path(path: str | Path) -> Path:
    """Return an absolute Path with `~` expanded but symlinks not followed.

    Used for paths stored in documents.file_path or
    corpus_reingest_log.{old_file_path, new_file_path}. This intentionally
    uses os.path.abspath rather than Path.resolve so the unversioned corpus
    symlink prefix is preserved for cross-machine path rewriting.
    """
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


__all__ = ['normalize_corpus_path']
