from typing import Optional

from pydantic import BaseModel


class PrefsPatch(BaseModel):
    bell: Optional[bool] = None
    email: Optional[bool] = None
    telegram: Optional[bool] = None
