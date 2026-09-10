from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain import PCRConfig
from .storage import (
    Configuration,
    Control,
    Health,
    Observation,
    active_config,
    initialize,
    make_engine,
    replay,
    utc_now,
)


def create_app(engine=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine if engine is not None else make_engine()
        initialize(app.state.engine)
        yield

    app = FastAPI(title="Market Strategy Lab", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        if request.method == "POST" and request.headers.get("origin") not in (
            None,
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:8123",
            "http://127.0.0.1:8123",
        ):
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "execution": "not_enabled"}

    @app.get("/api/config-schema")
    def config_schema():
        return PCRConfig.model_json_schema()

    @app.get("/api/state")
    def state():
        with Session(app.state.engine) as session:
            config_id, config, enabled = active_config(session)
            worker = session.get(Health, 1)
            worker_data = dict(worker.payload) if worker else {"state": "not_started"}
            heartbeat = worker_data.get("heartbeat_at")
            age = (
                (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)).total_seconds()
                if heartbeat
                else None
            )
            worker_data["heartbeat_age_seconds"] = round(age, 1) if age is not None else None
            worker_data["alive"] = age is not None and age < 45
            rows = session.scalars(
                select(Observation)
                .where(Observation.config_id == config_id)
                .order_by(Observation.id.desc())
                .limit(240)
            ).all()
            count = session.scalar(
                select(func.count()).select_from(Observation).where(Observation.config_id == config_id)
            )
            history = []
            previous_signature = None
            for row in reversed(rows):
                moving = next(r for r in row.evaluation["results"] if r["mode"] == "moving")
                signature = (row.session_date, row.snapshot["expiry"], tuple(moving["contract_keys"]))
                history.append(
                    {
                        "id": row.id,
                        "recorded_at": row.recorded_at,
                        "spot": row.snapshot["spot"],
                        "evaluation": row.evaluation,
                        "range_changed": previous_signature is not None and signature != previous_signature,
                    }
                )
                previous_signature = signature
            latest = rows[0] if rows else None
            receipt_age = (
                (datetime.now(timezone.utc) - datetime.fromisoformat(latest.recorded_at)).total_seconds()
                if latest
                else None
            )
            return {
                "config_id": config_id,
                "config": config.model_dump(mode="json"),
                "enabled": enabled,
                "worker": worker_data,
                "history": history,
                "observation_count": count,
                "receipt_age_seconds": round(receipt_age, 1) if receipt_age is not None else None,
                "collection_overdue": bool(
                    enabled and (receipt_age is None or receipt_age > config.interval_seconds * 2)
                ),
                "execution_enabled": False,
            }

    @app.get("/api/configurations")
    def configurations():
        with Session(app.state.engine) as session:
            return [
                {"id": row.id, "created_at": row.created_at, "config": row.payload}
                for row in session.scalars(select(Configuration).order_by(Configuration.id.desc()))
            ]

    @app.post("/api/configurations", status_code=201)
    def configure(config: PCRConfig):
        with Session(app.state.engine) as session, session.begin():
            control = session.get(Control, 1)
            if control.enabled:
                raise HTTPException(409, "Pause collection before activating a new configuration.")
            row = Configuration(created_at=utc_now(), payload=config.model_dump(mode="json"))
            session.add(row)
            session.flush()
            control.active_config_id = row.id
            return {
                "config_id": row.id,
                "message": "New version active. Prior observations and anchors retained.",
            }

    class CollectionControl(BaseModel):
        enabled: bool

    @app.post("/api/collection")
    def collection(body: CollectionControl):
        with Session(app.state.engine) as session, session.begin():
            session.get(Control, 1).enabled = body.enabled
        return {"enabled": body.enabled}

    @app.get("/api/observations/{observation_id}")
    def observation(observation_id: int):
        with Session(app.state.engine) as session:
            row = session.get(Observation, observation_id)
            if row is None:
                raise HTTPException(404, "Observation not found")
            return {
                "id": row.id,
                "config_id": row.config_id,
                "recorded_at": row.recorded_at,
                "snapshot": row.snapshot,
                "evaluation": row.evaluation,
            }

    @app.post("/api/replay/{config_id}")
    def replay_config(config_id: int):
        try:
            return replay(app.state.engine, config_id)
        except ValueError:
            raise HTTPException(404, "Configuration not found") from None

    # Development uses Vite proxy; built UI can be served by the same local backend.
    dist = Path("frontend/dist")
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    return app


app = create_app()
