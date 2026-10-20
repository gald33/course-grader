from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    accounts,
    assignments,
    artifacts,
    auth,
    courses,
    curves,
    exports,
    grade_releases,
    gradebook,
    imports,
    oauth,
    peer_review,
    roster,
    runs,
    student_auth,
    student_review,
    submissions,
)
from app.core.config import get_settings
from app.services.paths import ensure_structure

settings = get_settings()

app = FastAPI(title="course-grader API", version="1.0.0")


# Registered before CORS so CORS stays the outer layer and 401s still carry
# CORS headers the browser can read.
@app.middleware("http")
async def instructor_auth(request: Request, call_next):
    if auth.requires_instructor(request.url.path, request.method) and not auth.is_instructor_request(request):
        return JSONResponse({"detail": "Instructor authentication required"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses.router)
app.include_router(imports.router)
app.include_router(assignments.router)
app.include_router(submissions.router)
app.include_router(runs.router)
app.include_router(gradebook.router)
app.include_router(grade_releases.router)
app.include_router(curves.router)
app.include_router(oauth.router)
app.include_router(artifacts.router)
app.include_router(exports.router)
app.include_router(auth.router)
app.include_router(peer_review.router)
app.include_router(student_review.router)
app.include_router(student_review.preview_router)
app.include_router(student_auth.router)
app.include_router(accounts.router)
app.include_router(roster.router)


@app.on_event("startup")
def _startup() -> None:
    ensure_structure()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
