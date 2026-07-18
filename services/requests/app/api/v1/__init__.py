"""API v1 router assembly."""

from fastapi import APIRouter

from app.api.v1 import actions, forms, instances, projects, reference, stats, stream

router = APIRouter(prefix="/api/requests/v1")
router.include_router(projects.router)
router.include_router(forms.router)
router.include_router(instances.router)
router.include_router(actions.router)
router.include_router(stream.router)
router.include_router(stats.router)
router.include_router(reference.router)

__all__ = ["router"]
