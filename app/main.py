from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from celery.result import AsyncResult
from fastapi.responses import StreamingResponse

from app.database import get_db, engine
from app.models import Base, SourceDocument, MCQAssessment
from app.schemas import AssessmentRequest, TaskStatusResponse
from app.celery_app import celery_app
from app.tasks import async_generate_mcqs

Base.metadata.create_all(bind=engine)
app = FastAPI(title="AI MCQ Platform")

@app.post("/api/v1/assessment/generate_stream")
def generate_assessment(payload: AssessmentRequest, db: Session = Depends(get_db)):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Inbound source string cannot be empty.")
    try:
        source_doc = SourceDocument(raw_text=payload.text)
        db.add(source_doc)
        db.flush()
        db.commit()

        task = async_generate_mcqs.delay(source_doc.id, payload.text, payload.num_questions)
        return {"document_id": source_doc.id, "task_id": task.id, "status": "processing"}
    except Exception as err:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(err))



async def generate_assessment_stream(payload: AssessmentRequest):
    # 1. We create a generator function that reads the AI stream line-by-line
    def ai_stream_generator():
        # Change this call to match your specific LLM provider setup
        response = openai.chat.completions.create(
            model="gpt-4o-mini",  # Highly speed-optimized model
            messages=[{"role": "user", "content": f"Generate {payload.num_questions} MCQs from: {payload.text}"}],
            stream=True  # Tells the AI to send text pieces instantly
        )
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # 2. Return the live pipeline directly to your Streamlit frontend
    return StreamingResponse(ai_stream_generator(), media_type="text/plain")

@app.get("/api/v1/assessment/status/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, db: Session = Depends(get_db)):
    task_result = AsyncResult(task_id, app=celery_app)
    response = {"task_id": task_id, "task_status": task_result.status, "result": None}

    if task_result.status == "SUCCESS":
        meta_data = task_result.result
        if meta_data and meta_data.get("status") == "success":
            doc_id = meta_data.get("document_id")
            questions = db.query(MCQAssessment).filter(MCQAssessment.source_id == doc_id).all()
            return {
         	"status": "success",
        	"document_id": source_doc.id,
        	"mcqs": [{"question_text": q.question_text, "options": q.options, "answer_key": q.answer_key} for q in questions]
    }
    return response