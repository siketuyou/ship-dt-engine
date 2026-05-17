from pydantic import BaseModel


class KeywordCreateBody(BaseModel):
    modelId: int
    keywordName: str
    useFlag: int = 1
