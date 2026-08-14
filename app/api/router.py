from fastapi import APIRouter

from app.api.accounts_router import router as accounts_router
from app.api.auth_router import router as auth_router
from app.api.content_sources_router import router as content_sources_router
from app.api.news_router import router as news_router
from app.api.sources_router import router as sources_router
from app.api.webhooks_router import router as webhooks_router

router = APIRouter()
router.include_router(accounts_router)
router.include_router(auth_router)
router.include_router(webhooks_router)
router.include_router(sources_router)
router.include_router(content_sources_router)
router.include_router(news_router)
