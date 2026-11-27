from typing import Optional


class TuilanAuthError(RuntimeError):
    """Structured authentication error raised for Tuilan upstream auth failures."""

    def __init__(
        self,
        message: str = "tuilan authentication failed",
        *,
        code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code: Optional[str] = code


def is_tuilan_auth_error(exc: BaseException) -> bool:
    """Return True when ``exc`` is a structured Tuilan authentication error."""
    return isinstance(exc, TuilanAuthError)
