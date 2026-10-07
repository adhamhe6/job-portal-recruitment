"""Interviews routes (implemented by the interviews module owner; this stub keeps the router wired)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import COMMON_ERRORS

router = APIRouter(prefix="/interviews", tags=["Interviews"], responses=COMMON_ERRORS)
