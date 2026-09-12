"""
Pydantic request models — these define exactly what shape of JSON each
endpoint accepts, and FastAPI validates every incoming request against them
automatically, before your route function's body even runs. If validation
fails, FastAPI returns a 422 with details about which field was wrong —
you never have to hand-write that checking yourself.

If you've used Python's `dataclasses` or `attrs`, a Pydantic `BaseModel` is
similar but adds parsing + validation: `EmailStr` actually checks the string
looks like an email, `Optional[str] = None` makes a field genuinely
optional, and so on.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

# A permissive-but-real phone check: strip everything but digits, require
# a plausible length (7-15 digits is the practical range for real phone
# numbers worldwide, per the E.164 numbering plan). This intentionally does
# NOT require a leading "+" or a specific country format — it only rejects
# obvious garbage ("abc", "123"), matching "phone is optional but validated
# when supplied" rather than full carrier-grade validation.
_PHONE_DIGITS_RE = re.compile(r"\D+")


def _looks_like_a_phone_number(value: str) -> bool:
    digits = _PHONE_DIGITS_RE.sub("", value)
    return 7 <= len(digits) <= 15


# Backend password policy for self-serve signup (POST /api/auth/signup):
# at least 8 characters (matching the floor backend/create_user.py's CLI
# already enforces), plus at least one letter and one digit, so a purely
# numeric or purely alphabetic string doesn't pass. Deliberately not
# requiring symbols/mixed-case on top of that -- length plus a mix of
# letters and numbers is a reasonable minimum bar without being punishing
# for a "Phase 1" signup form.
_PASSWORD_MIN_LENGTH = 8


def _password_meets_requirements(password: str) -> bool:
    if len(password) < _PASSWORD_MIN_LENGTH:
        return False
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_letter and has_digit


class LeadIn(BaseModel):
    """POST /api/leads request body.

    The exact contract asked for is: {"name", "email", "phone", "interest"}.
    The existing, already-working frontend (index.html's "Get started"
    form) sends a couple of extra fields on top of that — `phone_e164`
    (instead of `phone`), plus `country`, `country_code`, `source`, and
    `submitted_at`. Rather than changing that working JavaScript to match
    a narrower shape, this model accepts both: `phone_e164` is treated as
    an alias for `phone` if `phone` itself isn't present, and the other
    extra fields are accepted (and stored) but never required.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    email: EmailStr
    phone: str | None = None
    interest: str | None = None
    # Accepted for compatibility with the existing frontend payload; none
    # of these are required, and none affect validation.
    country: str | None = None
    country_code: str | None = None
    source: str | None = None
    submitted_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_phone_e164_alias(cls, data: dict) -> dict:
        if isinstance(data, dict) and not data.get("phone") and data.get("phone_e164"):
            data = {**data, "phone": data["phone_e164"]}
        return data

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Please enter your name.")
        if len(v) > 200:
            raise ValueError("Name is too long.")
        return v.strip()

    @field_validator("phone")
    @classmethod
    def _phone_valid_if_present(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not _looks_like_a_phone_number(v):
            raise ValueError("Please enter a valid phone number.")
        return v

    @field_validator("interest")
    @classmethod
    def _interest_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 200:
            raise ValueError("That's too long.")
        return v


class SignupIn(BaseModel):
    """POST /api/auth/signup request body -- the "Create your Zoey account"
    modal's real account-creation request, as distinct from LeadIn (the
    same modal's fields used to power the waitlist form before this).

    Field names deliberately match LeadIn's shape (`phone`/`phone_e164`
    alias, `interest`) so the existing frontend payload structure barely
    has to change -- only `password`/`confirm_password` are new.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    email: EmailStr
    phone: str | None = None
    interest: str | None = None
    password: str
    confirm_password: str

    @model_validator(mode="before")
    @classmethod
    def _accept_phone_e164_alias(cls, data: dict) -> dict:
        if isinstance(data, dict) and not data.get("phone") and data.get("phone_e164"):
            data = {**data, "phone": data["phone_e164"]}
        return data

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Please enter your name.")
        if len(v) > 200:
            raise ValueError("Name is too long.")
        return v.strip()

    @field_validator("phone")
    @classmethod
    def _phone_valid_if_present(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not _looks_like_a_phone_number(v):
            raise ValueError("Please enter a valid phone number.")
        return v

    @field_validator("interest")
    @classmethod
    def _interest_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 200:
            raise ValueError("That's too long.")
        return v

    @field_validator("password")
    @classmethod
    def _password_valid(cls, v: str) -> str:
        if not _password_meets_requirements(v):
            raise ValueError(
                f"Password must be at least {_PASSWORD_MIN_LENGTH} characters "
                "and include at least one letter and one number."
            )
        return v

    @field_validator("confirm_password")
    @classmethod
    def _passwords_match(cls, v: str, info) -> str:
        password = info.data.get("password")
        if password is not None and v != password:
            raise ValueError("Passwords do not match.")
        return v


class LoginIn(BaseModel):
    """POST /api/login request body."""

    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    password: str
    remember: bool = False

    @field_validator("password")
    @classmethod
    def _password_present(cls, v: str) -> str:
        if not v:
            raise ValueError("Please enter your password.")
        return v
