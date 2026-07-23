"""Painel de mercado da tela inicial."""
from fastapi import APIRouter, Depends

from gateway.app import mercado
from gateway.app.auth.entra import verify_token

router = APIRouter()


@router.get("/mercado")
async def get_mercado(_: dict = Depends(verify_token)):
    return await mercado.payload()
