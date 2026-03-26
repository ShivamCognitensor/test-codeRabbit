from __future__ import annotations

class AppError(Exception):
    pass

class BadRequest(AppError):
    pass

class UpstreamError(AppError):
    pass
