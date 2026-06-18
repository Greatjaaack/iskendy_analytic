"""Роутер номенклатуры: ингредиенты, ТТК и привязка проданное блюдо ↔ ТТК."""

import re

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from models import (
    DishMapping,
    Ingredient,
    SessionLocal,
    Supplier,
    SupplierPrice,
    Ttk,
    TtkIngredient,
)

router = APIRouter(prefix="/api", tags=["nomenclature"])


def _norm(s: str) -> str:
    """Нормализация имени для сопоставления (lower, ё→е, схлоп пробелов)."""
    return re.sub(r"\s+", " ", str(s or "").strip().lower().replace("ё", "е"))


# ---------- Ингредиенты (номенклатура) ----------


@router.get("/ingredients")
def list_ingredients():
    with SessionLocal() as db:
        # минимальная цена по ингредиенту (для обзора)
        price_cnt = dict(
            db.execute(
                select(SupplierPrice.ingredient_id, func.count(SupplierPrice.id)).group_by(
                    SupplierPrice.ingredient_id
                )
            ).all()
        )
        rows = db.execute(select(Ingredient).order_by(Ingredient.name)).scalars().all()
        return [
            {
                "id": i.id,
                "name": i.name,
                "unit": i.unit,
                "iiko_product_id": i.iiko_product_id,
                "prices": price_cnt.get(i.id, 0),
            }
            for i in rows
        ]


@router.get("/ingredients/{ingredient_id}")
def get_ingredient(ingredient_id: int):
    with SessionLocal() as db:
        ing = db.get(Ingredient, ingredient_id)
        if not ing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ингредиент не найден")

        prices = db.execute(
            select(SupplierPrice, Supplier)
            .join(Supplier, SupplierPrice.supplier_id == Supplier.id)
            .where(SupplierPrice.ingredient_id == ingredient_id)
            .order_by(SupplierPrice.price_date.desc().nullslast())
        ).all()

        used_in = (
            db.execute(
                select(Ttk)
                .join(TtkIngredient, TtkIngredient.ttk_id == Ttk.id)
                .where(TtkIngredient.ingredient_id == ingredient_id)
                .distinct()
            )
            .scalars()
            .all()
        )

        return {
            "id": ing.id,
            "name": ing.name,
            "unit": ing.unit,
            "iiko_product_id": ing.iiko_product_id,
            "prices": [
                {
                    "supplier_id": s.id,
                    "supplier": s.name,
                    "pack_size": p.pack_size,
                    "pack_price": p.pack_price,
                    "unit_price": p.unit_price,
                    "price_date": p.price_date.isoformat() if p.price_date else None,
                }
                for p, s in prices
            ],
            "used_in": [{"id": t.id, "name": t.name, "category": t.category} for t in used_in],
        }


class IngredientPatch(BaseModel):
    name: str | None = None
    unit: str | None = None
    iiko_product_id: str | None = None


@router.put("/ingredients/{ingredient_id}")
def update_ingredient(ingredient_id: int, data: IngredientPatch):
    with SessionLocal() as db:
        ing = db.get(Ingredient, ingredient_id)
        if not ing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ингредиент не найден")
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(ing, k, v)
        db.commit()
        return {
            "id": ing.id,
            "name": ing.name,
            "unit": ing.unit,
            "iiko_product_id": ing.iiko_product_id,
        }


# ---------- ТТК ----------


@router.get("/ttk")
def list_ttk():
    with SessionLocal() as db:
        rows = db.execute(select(Ttk).order_by(Ttk.is_semi, Ttk.name)).scalars().all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "category": t.category,
                "is_semi": t.is_semi,
                "yield_qty": t.yield_qty,
                "yield_unit": t.yield_unit,
                "cost_total": round(t.cost_total or 0, 2),
            }
            for t in rows
        ]


@router.get("/ttk/{ttk_id}")
def get_ttk(ttk_id: int):
    with SessionLocal() as db:
        t = db.get(Ttk, ttk_id)
        if not t:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ТТК не найдена")
        lines = []
        for line in t.lines:
            child = db.get(Ttk, line.child_ttk_id) if line.child_ttk_id else None
            lines.append(
                {
                    "id": line.id,
                    "raw_name": line.raw_name,
                    "ingredient_id": line.ingredient_id,
                    "child_ttk_id": line.child_ttk_id,
                    "child_ttk_name": child.name if child else None,
                    "gross": line.gross,
                    "net": line.net,
                    "unit": line.unit,
                    "waste_pct": round(line.waste_pct, 2) if line.waste_pct is not None else None,
                    "cost_rub": round(line.cost_rub, 2) if line.cost_rub is not None else None,
                }
            )
        return {
            "id": t.id,
            "name": t.name,
            "category": t.category,
            "is_semi": t.is_semi,
            "yield_qty": t.yield_qty,
            "yield_unit": t.yield_unit,
            "cost_total": round(t.cost_total or 0, 2),
            "lines": lines,
        }


# ---------- Привязка проданное блюдо ↔ ТТК (для расчёта с/с по блюду) ----------


class DishMapIn(BaseModel):
    sale_name: str  # название блюда в продажах iiko
    ttk_id: int


@router.get("/dish-mappings")
def list_dish_mappings():
    with SessionLocal() as db:
        out = []
        for m in db.query(DishMapping).all():
            t = m.ttk
            out.append(
                {
                    "id": m.id,
                    "sale_name": m.sale_name,
                    "ttk_id": m.ttk_id,
                    "ttk_name": t.name if t else None,
                    "cost_full": t.cost_full if t else None,
                }
            )
        return sorted(out, key=lambda x: x["sale_name"].lower())


@router.post("/dish-mappings")
def upsert_dish_mapping(data: DishMapIn):
    """Создать/обновить привязку (по нормализованному имени продажи)."""
    with SessionLocal() as db:
        if not db.get(Ttk, data.ttk_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ТТК не найдена")
        nn = _norm(data.sale_name)
        m = db.execute(
            select(DishMapping).where(DishMapping.sale_name_norm == nn)
        ).scalar_one_or_none()
        if m:
            m.ttk_id = data.ttk_id
            m.sale_name = data.sale_name
        else:
            m = DishMapping(sale_name=data.sale_name, sale_name_norm=nn, ttk_id=data.ttk_id)
            db.add(m)
        db.commit()
        db.refresh(m)
        return {"id": m.id, "sale_name": m.sale_name, "ttk_id": m.ttk_id}


@router.delete("/dish-mappings/{mapping_id}")
def delete_dish_mapping(mapping_id: int):
    with SessionLocal() as db:
        m = db.get(DishMapping, mapping_id)
        if not m:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "привязка не найдена")
        db.delete(m)
        db.commit()
        return {"status": "ok"}
