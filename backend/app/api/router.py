"""Assembles the versioned API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import applications, auth, candidates, companies, jobs, matches, notifications, search, skills, tasks, users

api_router = APIRouter()
for router in (
    auth.router, users.router, companies.router, skills.router, candidates.router, jobs.router, search.router,
    applications.router, matches.matches_router, matches.recs_router, notifications.router, tasks.router,
):
    api_router.include_router(router)
