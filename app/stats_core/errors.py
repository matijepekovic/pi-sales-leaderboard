class ValidationError(ValueError):
    """User-correctable input error."""


class BusyError(RuntimeError):
    """A mutually exclusive operation is already running."""
