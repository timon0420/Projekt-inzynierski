from pydantic import BaseModel, ConfigDict

class PairRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')

    code: str = ''
    role: str = ''