from fastapi import APIRouter

from app.api.accounts_router import router as accounts_router
from app.api.auth_router import router as auth_router
from app.api.conditions_router import router as conditions_router
from app.api.content_sources_router import router as content_sources_router
from app.api.incidents_router import router as incidents_router
from app.api.news_router import router as news_router
from app.api.villages_router import router as villages_router
from app.api.logs_router import router as logs_router
from app.api.pipeline_router import router as pipeline_router
from app.api.sources_router import router as sources_router
from app.api.webhooks_router import router as webhooks_router
from app.api.map_router import router as map_router
from app.api.rejected_news_router import router as rejected_news_router

router = APIRouter()
router.include_router(accounts_router)
router.include_router(auth_router)
router.include_router(webhooks_router)
router.include_router(sources_router)
router.include_router(conditions_router)
router.include_router(villages_router)
router.include_router(content_sources_router)
router.include_router(incidents_router)
router.include_router(news_router)
router.include_router(logs_router)
router.include_router(pipeline_router)
router.include_router(map_router)
router.include_router(rejected_news_router)
