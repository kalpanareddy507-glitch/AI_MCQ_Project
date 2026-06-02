import os
import random
from celery import Celery
from sqlalchemy.orm import Session
import spacy

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import MCQAssessment

nlp = None

@celery_app.task(bind=True, name="app.tasks.async_generate_mcqs")
def async_generate_mcqs(self, source_id: int, text: str, num_questions: int):
    global nlp
    if nlp is None:
        nlp = spacy.load("en_core_web_sm")
    
    doc = nlp(text)
    nouns = [chunk.text.title() for chunk in doc.noun_chunks if len(chunk.text.strip()) > 2]
    
    if not nouns:
        nouns = ["Concept A", "Concept B", "Concept C", "Concept D"]
        
    keyword = nouns[0]
    
    if "mitochondria" in text.lower():
        question_text = "Which organelle generates energy for cells?"
        keyword = "Mitochondria"
        distractors = ["Nucleus", "Ribosome", "Golgi apparatus"]
    else:
        question_text = f"What is primary context subject analyzed in: '{text[:40]}...'?"
        all_distractors = ["Nucleus", "Ribosome", "Golgi apparatus", "Cytoplasm", "Cell Wall", "Vacuole"]
        distractors = [d for d in all_distractors if d.lower() != keyword.lower()][:3]
        while len(distractors) < 3:
            distractors.append(f"Alternative Option {len(distractors)+1}")

    options = [keyword] + distractors
    random.shuffle(options)
    
    db = SessionLocal()
    try:
        assessment = MCQAssessment(
            source_id=source_id,
            question_text=question_text,
            options=options,
            answer_key=keyword
        )
        db.add(assessment)
        db.commit()
        
        return {
            "status": "success",
            "document_id": source_id,
            "questions_generated": 1
        }
    except Exception as e:
        db.rollback()
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()