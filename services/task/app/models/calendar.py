"""Calendar event models."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel


class CalendarEvent(BaseModel):
    """Event in the production calendar.

    Stores precise ``start_at`` / ``end_at`` timestamps. ``is_all_day`` is a
    presentation hint — for true all-day events the form sends midnight–
    end-of-day, and the UI hides the time component.
    """

    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('personal','department','common','conference')",
            name="ck_calendar_event_type",
        ),
        CheckConstraint("end_at >= start_at", name="ck_calendar_event_range"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="personal", index=True
    )
    conference_room_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    department_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # Author of the event — populated from the JWT on create. Kept nullable
    # so the column survives a backfill from rows created before migration 006.
    creator_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    exceptions: Mapped[list["EventException"]] = relationship(
        "EventException", back_populates="event", cascade="all, delete-orphan"
    )
    participants: Mapped[list["CalendarEventParticipant"]] = relationship(
        "CalendarEventParticipant",
        back_populates="event",
        cascade="all, delete-orphan",
    )


class EventException(BaseModel):
    """Exceptions to recurring calendar events."""
    __tablename__ = "event_exceptions"

    event_id: Mapped[int] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    event: Mapped["CalendarEvent"] = relationship("CalendarEvent", back_populates="exceptions")


class CalendarEventParticipant(Base):
    """Invited user for a calendar event (e.g. a general meeting).

    Composite PK (event_id, user_id). No FK to a user table — see
    migration 006 for the rationale. The visibility filter in the
    calendar API joins on ``user_id == current_user.user_id``.
    """

    __tablename__ = "calendar_event_participants"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "user_id", name="pk_calendar_event_participants"),
        CheckConstraint(
            "rsvp_status IN ('pending','accepted','declined')",
            name="ck_calendar_event_participant_status",
        ),
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 'pending' until the invitee accepts or declines. The author is added with
    # 'accepted' from the start since they implicitly attend their own event.
    rsvp_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    event: Mapped["CalendarEvent"] = relationship(
        "CalendarEvent", back_populates="participants"
    )
