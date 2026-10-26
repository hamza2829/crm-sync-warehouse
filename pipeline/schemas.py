"""Validate required fields while keeping the untouched source payload."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

Stage = Literal["lead", "qualified", "proposal", "won", "lost"]


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int = Field(gt=0)
    updated_at: AwareDatetime


class Company(SourceRecord):
    name: str = Field(min_length=1)
    industry: str


class Contact(SourceRecord):
    company_id: int = Field(gt=0)
    email: str = Field(min_length=1)


class Deal(SourceRecord):
    name: str = Field(min_length=1)
    company_id: int = Field(gt=0)
    contact_id: int = Field(gt=0)
    stage: Stage
    amount: Decimal | None = Field(ge=0, allow_inf_nan=False)
    currency: Literal["USD"]
    created_at: AwareDatetime
    close_date: date


class DealEvent(BaseModel):
    event_id: UUID
    deal_id: int = Field(gt=0)
    event_time: AwareDatetime
    old_stage: Stage
    new_stage: Stage


SCHEMAS = {"deals": Deal, "companies": Company, "contacts": Contact}


def validate_records(resource: str, records: list[dict]) -> tuple[list, list, dict]:
    schema = SCHEMAS[resource]
    valid, rejected, unknown = [], [], set()
    for raw in records:
        extras = set(raw) - set(schema.model_fields)
        unknown.update(extras)
        try:
            parsed = schema.model_validate(raw).model_dump(mode="json")
            valid.append({"parsed": parsed, "raw": raw})
        except ValidationError as exc:
            reason = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            rejected.append({"resource": resource, "raw": raw, "reason": reason})
    return (
        valid,
        rejected,
        {"unknown_fields": sorted(unknown), "rejected": len(rejected), "seen": len(records)},
    )
