"""Failures the processing pipeline distinguishes, because each maps to a different HTTP answer."""


class ProcessingError(Exception):
    """Base class for every failure raised on purpose by the pipeline."""


class PoisonMessageError(ProcessingError):
    """The message can never be processed (bad envelope, bad base64, invalid event).

    Retrying it is pointless; Pub/Sub moves it to the dead-letter topic after its
    configured number of delivery attempts.
    """


class TransientStorageError(ProcessingError):
    """The storage backend failed in a way that may succeed on retry (503, 429, timeout)."""


class PermanentStorageError(ProcessingError):
    """The backend rejected the write for a reason a retry will not fix (bad schema, 403)."""
