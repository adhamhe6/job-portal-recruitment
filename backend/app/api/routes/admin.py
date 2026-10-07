"""Admin routes (implemented by the admin module owner; this stub keeps the router wired)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import COMMON_ERRORS

router = APIRouter(prefix="/admin", tags=["Admin"], responses=COMMON_ERRORS)
