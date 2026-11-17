"""Alert vocabulary shared by both services: the processor writes it, the API filters on it."""

from enum import StrEnum


class AlertType(StrEnum):
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    RAPID_STOCK_DROP = "RAPID_STOCK_DROP"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(StrEnum):
    OPEN = "OPEN"
