"""Compatibility Base for legacy modules.

Legacy code in this repo expects `app.db.base.Base`.
The new service defines the canonical SQLAlchemy Declarative Base in `app.core.db.Base`.

We re-export that Base here so *all* models share a single metadata.
"""

from app.core.db import Base  # noqa: F401
