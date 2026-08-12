"""Canonical CLI entry point for the laptop-owned TRZIP publisher."""

from .publication_pipeline import main, run

__all__ = ["main", "run"]


if __name__ == "__main__":
    main()
