from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Literal

Angle = Annotated[float, Field(ge=0, le=180, allow_inf_nan=False)]

class GestureData(BaseModel):
    model_config = ConfigDict(strict=True, extra='ignore')

    type: Literal["angles"]
    angles: Annotated[list[Angle], Field(min_length=6, max_length=6)]
    timestamp: float = Field(default=0.0, allow_inf_nan=False)
    sequence: int = Field(default=0, ge=0)