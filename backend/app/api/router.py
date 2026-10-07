"""Assembles the versioned API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    admin,
    applications,
    auth,
    candidates,
    companies,
    interviews,
    jobs,
    matches,
    notifications,
    reports,
    resumes,
    search,
    skills,
    tasks,
    users,
)

api_router = APIRouter()
for router in (
    auth.router, users.router, companies.router, skills.router, candidates.router, jobs.router, search.router,
    resumes.router, applications.router, interviews.router, matches.matches_router, matches.recs_router,
    notifications.router, reports.router, tasks.router, admin.router,
):
    api_router.include_router(router)
