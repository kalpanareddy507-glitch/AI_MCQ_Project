import datetime
from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class SourceDocument(Base):
    __tablename__ = "source_documents"

    id = Column(Integer, primary_key=True, index=True)
    raw_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    questions = relationship(
        "MCQAssessment", 
        back_populates="source_document", 
        cascade="all, delete-orphan"
    )

class MCQAssessment(Base):
    __tablename__ = "mcq_assessments"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False)
    question_text = Column(Text, nullable=False)
    options = Column(JSON, nullable=False)
    answer_key = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    source_document = relationship("SourceDocument", back_populates="questions")