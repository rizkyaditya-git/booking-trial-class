"""Public camelCase contracts; Python and service records use snake_case."""

import re
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel


def decimal_id(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    if type(value) is int:
        return value
    raise ValueError("Must be a positive decimal integer")


TextId = Annotated[int, BeforeValidator(decimal_id), Field(gt=0)]
JsonId = Annotated[int, Field(strict=True, gt=0)]
RequestKey = Annotated[str, Field(min_length=1, max_length=128)]
BookingStatus = Literal["pending_payment", "confirmed", "payment_failed", "cancelled"]
BlockReason = Literal["class_full", "duplicate_booking"]


class Input(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid")


class CreateBooking(Input):
    student_id: JsonId
    trial_class_id: JsonId


class CompletePayment(Input):
    requested_outcome: Literal["success", "failure"]


class BookingForm(Input):
    demo_parent_id: TextId
    student_id: TextId
    trial_class_id: TextId
    idempotency_key: RequestKey


class PaymentForm(Input):
    demo_parent_id: TextId
    requested_outcome: Literal["success", "failure"]
    idempotency_key: RequestKey


class Record(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Health(Record):
    status: Literal["ok"]


class Parent(Record):
    id: int
    name: str


class Student(Parent):
    parent_id: int


class TrialClass(Parent):
    starts_at: str
    capacity: Literal[4]
    confirmed_count: int
    seats_remaining: int


class Booking(Record):
    id: int
    student_id: int
    trial_class_id: int
    status: BookingStatus
    status_reason: BlockReason | None
    created_at: str
    updated_at: str


class PaymentAttempt(Record):
    id: int
    booking_id: int
    requested_outcome: Literal["success", "failure"]
    outcome: Literal["pending", "succeeded", "failed", "blocked"]
    reason: Literal["mock_declined", "class_full", "duplicate_booking"] | None
    created_at: str
    booking_status: BookingStatus
    booking_status_reason: BlockReason | None


class RosterMember(Record):
    booking_id: int
    student_id: int
    student_name: str


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: list[T]
    meta: dict = Field(default_factory=dict)


class Problem(Record):
    type: Literal["about:blank"] = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    instance: str
    request_id: str
    errors: list[dict[str, str]] | None = None
    booking_id: int | None = None
    payment_attempt_id: int | None = None
    booking_status: BookingStatus | None = None
    existing_booking_id: int | None = None
