from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    if getattr(request.app.state, "ready", False):
        return JSONResponse({"status": "ok"}, status_code=200)
    return JSONResponse({"status": "starting"}, status_code=503)
