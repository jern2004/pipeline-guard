from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Allowed values. Anything else is rejected with HTTP 422 before any route code runs.
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "resolved"]


class IncidentCreate(BaseModel):
    """Request body for POST /incidents: only the fields a client is allowed to set."""

    title: str = Field(min_length=1, max_length=200)
    description: str
    severity: Severity = "medium"


class IncidentResponse(BaseModel):
    """Response body: the shape of an incident the API sends back."""

    # Lets Pydantic read values from a SQLAlchemy object's attributes, not only from a dict.
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    severity: Severity
    status: Status
    created_at: datetime
    resolved_at: datetime | None
