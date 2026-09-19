"""Schema behavior shared by all public API endpoints."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base model that rejects undocumented request and response fields."""

    model_config = ConfigDict(extra="forbid")
