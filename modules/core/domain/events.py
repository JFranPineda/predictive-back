"""Domain events. Side effects subscribe; use cases never call them directly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DomainEvent:
    occurred_at: datetime

    @property
    def name(self) -> str:
        return type(self).__name__


@dataclass(frozen=True, slots=True)
class ModuleInstalled(DomainEvent):
    module_code: str
    version: str


@dataclass(frozen=True, slots=True)
class ModuleUninstalled(DomainEvent):
    module_code: str


@dataclass(frozen=True, slots=True)
class ReadingRecorded(DomainEvent):
    company_id: int
    reading_id: int
    point_id: int
    magnitude_code: str
    value: Decimal
    condition_status: str | None


@dataclass(frozen=True, slots=True)
class EquipmentStatusChanged(DomainEvent):
    company_id: int
    equipment_id: int
    previous: str | None
    current: str


@dataclass(frozen=True, slots=True)
class MediaUploaded(DomainEvent):
    company_id: int
    media_id: int
    original_format: str


@dataclass(frozen=True, slots=True)
class ServiceCompleted(DomainEvent):
    company_id: int
    service_order_id: int
