from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assignments, artifacts, courses, curves, exports, gradebook, imports, oauth, runs, submissions
from app.core.config import get_settings
from app.services.paths import ensure_structure

settings = get_settings()

app = FastAPI(title="course-grader API", version="1.0.0")

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
app.include_router(curves.router)
app.include_router(oauth.router)
app.include_router(artifacts.router)
app.include_router(exports.router)


@app.on_event("startup")
def _startup() -> None:
    ensure_structure()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
