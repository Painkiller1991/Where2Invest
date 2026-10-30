from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config_loader import load_config, project_root, save_config
from app.models.schemas import (
    ConfirmForecastRequest,
    ConfigUpdate,
    DataStatus,
    FetchRequest,
    ForecastRequest,
    ForecastResponse,
    InvestCompareResponse,
    InvestInput,
    InvestSuggestResponse,
)
from app.services import forecast as forecast_svc
from app.services.data_fetch import data_gate
from app.services.invest import compare_methods, suggest_monthly_budget

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Where2Invest", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return load_config()


@app.put("/api/config")
def put_config(body: ConfigUpdate) -> dict[str, Any]:
    cfg = load_config()
    _deep_merge(cfg, body.patch)
    save_config(cfg)
    return cfg


@app.get("/api/data/status", response_model=DataStatus)
def data_status() -> DataStatus:
    if not data_gate.ready:
        data_gate.bootstrap_from_db()
    return data_gate.status


@app.post("/api/data/fetch", response_model=DataStatus)
def data_fetch(body: FetchRequest) -> DataStatus:
    status = data_gate.fetch(start_date=body.start_date, force=body.force)
    if not status.ready:
        # Still return status with 200 so UI can show error + retry; gate flag is ready=false
        return status
    return status


@app.post("/api/forecast", response_model=ForecastResponse)
def create_forecast(body: ForecastRequest) -> ForecastResponse:
    if not data_gate.ready:
        raise HTTPException(status_code=409, detail="Step 1 incomplete: market data not ready")
    try:
        return forecast_svc.run_forecast(
            gold_sentiment=body.gold_sentiment,
            usd_sentiment=body.usd_sentiment,
            months=body.months,
            model=body.model,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("forecast failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/forecast/latest", response_model=ForecastResponse)
def latest_forecast() -> ForecastResponse:
    fc = forecast_svc.get_last_forecast()
    if fc is None:
        raise HTTPException(status_code=404, detail="No forecast yet")
    return fc


@app.post("/api/forecast/confirm", response_model=ForecastResponse)
def confirm_forecast(body: ConfirmForecastRequest) -> ForecastResponse:
    try:
        return forecast_svc.confirm_forecast(body.confirm)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post("/api/invest/suggest-monthly", response_model=InvestSuggestResponse)
def invest_suggest_monthly(body: InvestInput) -> InvestSuggestResponse:
    return suggest_monthly_budget(body)


@app.post("/api/invest/compare", response_model=InvestCompareResponse)
def invest_compare(body: InvestInput) -> InvestCompareResponse:
    try:
        return compare_methods(body)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.get("/api/docs/prediction-models")
def prediction_models_doc() -> FileResponse:
    path = project_root() / "docs" / "prediction-models.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Doc not found")
    return FileResponse(path)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


_docs_dir = project_root() / "docs"
if _docs_dir.exists():
    app.mount("/docs-static", StaticFiles(directory=str(_docs_dir)), name="docs_static")

# Optional: serve built frontend if present
_frontend_dist = project_root() / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
