import re

from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime

# Kept in step with the hint shown under the password field on the mobile
# registration screen. A form that asks for eight characters and an API that
# accepts one are telling the user two different things about their account.
MINIMUM_PASSWORD_LENGTH = 8

# Deliberately loose: one @, something either side, and a dot in the domain.
# The aim is to catch a typo before it becomes an account nobody can log into,
# not to prove the mailbox exists — only sending mail to it could do that.
#
# A plain pattern rather than pydantic's EmailStr, which needs the
# email-validator package. That package is not installed here, and because
# schemas are imported during startup a missing dependency would stop the whole
# application rather than just this endpoint.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")


class DoctorBase(BaseModel):
    email: str
    full_name: str


class DoctorCreate(DoctorBase):
    """
    Registration input.

    The validators live here rather than on DoctorBase on purpose. DoctorBase
    is also the parent of DoctorResponse, which is built from rows already in
    the database — validating there would mean an account created before these
    rules existed could no longer be read back, turning a historical input
    problem into a permanent read failure.

    Validate what comes in. Never validate what goes out.
    """

    password: str

    @field_validator("email")
    @classmethod
    def email_must_look_like_an_address(cls, value: str) -> str:
        # Lowercased as well as trimmed, because the address is this system's
        # account identifier rather than a delivery route. RFC 5321 permits a
        # mail server to treat the local part case-sensitively, but no provider
        # meaningfully does, and an identifier that distinguishes
        # "Doctor@clinic.com" from "doctor@clinic.com" lets one person hold two
        # accounts — with the consultations recorded under each invisible from
        # the other.
        value = value.strip().lower()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("full_name")
    @classmethod
    def full_name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter the doctor's full name.")
        return value

    @field_validator("password")
    @classmethod
    def password_must_be_long_enough(cls, value: str) -> str:
        # Not stripped. Spaces are legitimate password characters, and silently
        # altering what someone typed would store a password they cannot
        # reproduce at the login screen.
        if len(value) < MINIMUM_PASSWORD_LENGTH:
            raise ValueError(
                f"Use at least {MINIMUM_PASSWORD_LENGTH} characters for the password."
            )
        return value


class DoctorResponse(DoctorBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: str | None = None
