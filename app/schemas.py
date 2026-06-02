from pydantic import BaseModel, Field
from typing import List, Any, Optional

class AssessmentRequest(BaseModel):
    text: str = Field(..., description="Raw text content to generate MCQs from.")
    num_questions: int = Field(default=5, ge=1, le=20, description="Target question count.")

class TaskStatusResponse(BaseModel):
    task_id: str
    task_status: str
    result: Optional[Any] = None