from pydantic import BaseModel, ConfigDict
from typing import Literal

class SourceMessage(BaseModel):
    model_config = ConfigDict(extra='ignore')

    type: Literal['source']
    source: Literal['remote_camera', 'local_camera']