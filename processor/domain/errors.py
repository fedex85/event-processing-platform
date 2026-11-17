"""Failures the processing pipeline distinguishes, because each maps to a different HTTP answer."""


class ProcessingError(Exception):
    """Base class for every failure raised on purpose by the pipeline."""


class TransientStorageError(ProcessingError):
    """The storage backend failed in a way that may succeed on retry (503, 429, timeout)."""


class PermanentStorageError(ProcessingError):
    """The backend rejected the write for a reason a retry will not fix (bad schema, 403)."""
