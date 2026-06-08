"""
Admin dashboard API — calls, bills, signed URLs for file access.
"""

from fastapi import APIRouter, HTTPException, Query

from app.services.admin_service import AdminServiceError, get_admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _service():
    try:
        return get_admin_service()
    except AdminServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/calls")
async def list_calls(
    q: str = Query("", description="Search name, phone, address"),
    filter: str = Query("all", alias="filter"),
    limit: int = Query(500, ge=1, le=1000),
) -> dict:
    allowed = {"all", "bill_uploaded", "no_bill", "sms_sent", "call_failed"}
    if filter not in allowed:
        raise HTTPException(status_code=400, detail=f"filter must be one of {sorted(allowed)}")

    rows = _service().list_calls(q=q, filter_by=filter, limit=limit)
    return {"calls": rows, "count": len(rows)}


@router.get("/calls/{row_key}")
async def get_call(row_key: str) -> dict:
    row = _service().get_call(row_key)
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return row


@router.get("/bills/{bill_id}/signed-url")
async def bill_signed_url(
    bill_id: int,
    download: bool = Query(False),
) -> dict:
    try:
        return _service().get_bill_signed_url(bill_id, download=download)
    except AdminServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
