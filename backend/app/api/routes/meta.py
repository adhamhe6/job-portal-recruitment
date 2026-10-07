"""Public deployment metadata (no secrets)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.core.config import get_settings

router = APIRouter(prefix="/meta", tags=["Health"])


class DemoAccount(BaseModel):
    role: str
    label: str
    email: str


class MetaOut(BaseModel):
    app: str
    version: str
    environment: str
    demo_mode: bool
    demo_password: str | None = None
    demo_accounts: list[DemoAccount] = []


@router.get(
    "", response_model=MetaOut, summary="Deployment metadata (demo accounts are listed only in demo mode)"
)
async def meta() -> MetaOut:
    s = get_settings()
    demo = s.seed_demo_data and s.environment != "production"
    out = MetaOut(app=s.app_name, version=__version__, environment=s.environment, demo_mode=demo)
    if demo:
        from app.scripts.seed_data import PASSWORD

        out.demo_password = PASSWORD
        out.demo_accounts = [
            DemoAccount(role="ADMIN", label="Platform admin", email="admin@demo.example"),
            DemoAccount(role="RECRUITER", label="Recruiter — Northwind Labs", email="recruiter@demo.example"),
            DemoAccount(
                role="HIRING_MANAGER",
                label="Hiring manager — Northwind Labs",
                email="hiring.manager@demo.example",
            ),
            DemoAccount(
                role="CANDIDATE", label="Candidate — Alex Rivera (backend)", email="candidate@demo.example"
            ),
            DemoAccount(
                role="CANDIDATE",
                label="Candidate — Bianca Costa (frontend)",
                email="bianca.costa@demo.example",
            ),
            DemoAccount(role="CANDIDATE", label="Candidate — Chen Wei (ML)", email="chen.wei@demo.example"),
        ]
    return out
