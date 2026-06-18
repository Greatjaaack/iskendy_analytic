"""Роутер запуска импорта файла «ТТК и матрица продуктов» в БД."""

from fastapi import APIRouter, HTTPException, status

from importers.ttk_matrix import import_ttk_matrix

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/ttk-matrix")
def run_import():
    try:
        counters = import_ttk_matrix()
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return {"status": "ok", "imported": counters}
