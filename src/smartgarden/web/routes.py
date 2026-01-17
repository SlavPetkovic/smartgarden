from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="src/smartgarden/web/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index_old.html", {"request": request})


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request})
