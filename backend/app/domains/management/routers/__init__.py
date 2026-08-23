from app.domains.management.routers.products import router as products_router
from app.domains.management.routers.projects import router as projects_router
from app.domains.management.routers.repositories import router as repositories_router
from app.domains.management.routers.repo_groups import router as repo_groups_router

__all__ = ["products_router", "projects_router", "repositories_router", "repo_groups_router"]
