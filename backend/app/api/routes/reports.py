"""Reports routes (implemented by the reports module owner; this stub keeps the router wired)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import COMMON_ERRORS

router = APIRouter(prefix="/reports", tags=["Reports"], responses=COMMON_ERRORS)
