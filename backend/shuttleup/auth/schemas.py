from pydantic import BaseModel, Field, field_validator


class GuestCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


class LoginRequest(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1,max_length=40)
    timezone: str = Field(min_length=1,max_length=64)
    expected_version: int


class PasswordUpdate(BaseModel):
    current_password: str|None=None
    new_password: str=Field(min_length=10,max_length=200)
