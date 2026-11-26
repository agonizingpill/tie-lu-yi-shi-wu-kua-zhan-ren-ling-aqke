from fastapi import APIRouter, Depends

from railway.security import actor
from railway.services import audit

router = APIRouter(prefix="/audits")


@router.get("")
def index(user=Depends(actor)):
    return audit.listing(user)


@router.post("", status_code=201)
def start(user=Depends(actor)):
    return audit.start(user)


@router.get("/{audit_id}")
def read(audit_id: int, user=Depends(actor)):
    return audit.detail(audit_id, user)


@router.post("/{audit_id}/run")
def run(audit_id: int, user=Depends(actor)):
    return audit.run(audit_id, user)
