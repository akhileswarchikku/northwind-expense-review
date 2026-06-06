import uuid
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime,
    Text, ForeignKey, func
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from backend.config import DB_PATH

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = "employees"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    grade = Column(Integer)
    title = Column(String)
    department = Column(String)
    manager_id = Column(String)
    home_base = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    submissions = relationship("Submission", back_populates="employee")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id = Column(String, ForeignKey("employees.id"))
    trip_purpose = Column(String)
    trip_dates_start = Column(String)
    trip_dates_end = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = relationship("Employee", back_populates="submissions")
    line_items = relationship("LineItem", back_populates="submission", cascade="all, delete-orphan")


class LineItem(Base):
    __tablename__ = "line_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id = Column(String, ForeignKey("submissions.id"))
    filename = Column(String)
    file_type = Column(String)
    raw_text = Column(Text)
    vendor = Column(String)
    date = Column(String)
    amount = Column(Float)
    currency = Column(String, default="USD")
    category = Column(String)
    description = Column(Text)
    verdict = Column(String)
    reasoning = Column(Text)
    confidence = Column(Float)
    policy_citations = Column(Text)   # JSON array string
    flags = Column(Text)              # JSON array string
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("Submission", back_populates="line_items")
    overrides = relationship("Override", back_populates="line_item", cascade="all, delete-orphan")


class Override(Base):
    __tablename__ = "overrides"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    line_item_id = Column(String, ForeignKey("line_items.id"))
    reviewer = Column(String)
    original_verdict = Column(String)
    new_verdict = Column(String)
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    line_item = relationship("LineItem", back_populates="overrides")


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_file = Column(String)
    doc_id = Column(String)
    chunk_index = Column(Integer)
    text = Column(Text)
    chroma_id = Column(String)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
