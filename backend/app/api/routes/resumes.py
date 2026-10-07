"""Resumes routes (implemented by the resumes module owner; this stub keeps the router wired)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import COMMON_ERRORS

router = APIRouter(prefix="/resumes", tags=["Resumes"], responses=COMMON_ERRORS)
