from typing import List
from pydantic import BaseModel


class FaceSlot(BaseModel):
    x: int
    y: int
    width: int
    height: int
    rotation: float = 0


class SaveTemplateRequest(BaseModel):
    id: str
    name: str
    filename: str
    tags: List[str]
    face_slot: FaceSlot
