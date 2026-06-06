from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class EmployeeCreate(BaseModel):
    id: str
    name: str
    grade: int
    title: str
    department: str
    manager_id: Optional[str] = None
    home_base: str


class EmployeeOut(BaseModel):
    id: str
    name: str
    grade: int
    title: str
    department: str
    manager_id: Optional[str]
    home_base: str
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class SubmissionCreate(BaseModel):
    employee_id: str
    trip_purpose: str
    trip_dates_start: str
    trip_dates_end: str


class PolicyCitation(BaseModel):
    doc_id: str
    section: str
    quote: str
    relevance: str


class OverrideOut(BaseModel):
    id: str
    reviewer: str
    original_verdict: str
    new_verdict: str
    comment: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LineItemOut(BaseModel):
    id: str
    submission_id: str
    filename: str
    file_type: Optional[str]
    vendor: Optional[str]
    date: Optional[str]
    amount: Optional[float]
    currency: str
    category: Optional[str]
    description: Optional[str]
    verdict: Optional[str]
    reasoning: Optional[str]
    confidence: Optional[float]
    policy_citations: Optional[str]
    flags: Optional[str]
    overrides: List[OverrideOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionOut(BaseModel):
    id: str
    employee_id: str
    trip_purpose: str
    trip_dates_start: str
    trip_dates_end: str
    status: str
    created_at: datetime
    updated_at: datetime
    employee: Optional[EmployeeOut]
    line_items: List[LineItemOut] = []

    model_config = {"from_attributes": True}


class OverrideCreate(BaseModel):
    reviewer: str
    new_verdict: str
    comment: str


class PolicyQARequest(BaseModel):
    question: str


class PolicyQAResponse(BaseModel):
    answer: str
    citations: List[dict]
    confidence: float
    refused: bool
    refusal_reason: Optional[str] = None


class IndexStatusResponse(BaseModel):
    indexed: bool
    chunk_count: int
    doc_ids: List[str]
