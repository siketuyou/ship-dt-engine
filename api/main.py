# api/main.py
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import consul
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .deps import _scheduler, settings
from .routers import models, keywords, logs
from utils.logger import get_logger

logger = get_logger("SpiderAPI")

_service_id: Optional[str] = None


def _register_to_consul():
    global _service_id
    if not settings.USE_CONSUL_CONFIG:
        return
    try:
        c = consul.Consul(host=settings.CONSUL_HOST, port=settings.CONSUL_PORT)
        service_name = "spider-service"
        service_id = f"{service_name}-{settings.SERVICE_HOST}:{settings.SERVICE_PORT}"
        c.agent.service.register(
            name=service_name,
            service_id=service_id,
            address=settings.SERVICE_HOST,
            port=settings.SERVICE_PORT,
            check=consul.Check.http(
                url=f"http://{settings.SERVICE_HOST}:{settings.SERVICE_PORT}/health",
                interval="10s",
                timeout="5s",
                deregister="30s",
            ),
        )
        _service_id = service_id
        logger.info(f"服务已注册到 Consul: {service_name} (ID: {service_id})")
    except Exception as e:
        logger.error(f"注册服务到 Consul 失败: {e}")


def _deregister_from_consul():
    if not _service_id:
        return
    try:
        c = consul.Consul(host=settings.CONSUL_HOST, port=settings.CONSUL_PORT)
        c.agent.service.deregister(_service_id)
        logger.info("已从 Consul 注销服务")
    except Exception as e:
        logger.error(f"注销服务失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.start()
    _register_to_consul()
    yield
    _deregister_from_consul()
    _scheduler.shutdown(wait=False)


app = FastAPI(title="Spider Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(models.router)
app.include_router(keywords.router)
app.include_router(logs.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
