"""Deprecated compatibility entry point for the publication pipeline.

TRZIP publication is owned by the laptop runtime.  Keep this module only so
older commands do not break while callers migrate to ``trzip.local_pipeline``.
"""

from .publication_pipeline import main, run

__all__ = ["main", "run"]


if __name__ == "__main__":
    main()
