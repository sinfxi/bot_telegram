"""Import public recipe metadata from TheMealDB search API.

Run: python scripts/import_themealdb.py --query chicken
Only import records exposed by the public API. Check current provider terms before production use.
Imported recipes retain the source URL and an explicit source status.
"""
import argparse
import os
import sys

import httpx
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from foodmind import Recipe, SessionLocal, init_db

API = "https://www.themealdb.com/api/json/v1/1/search.php"

def import_query(query: str) -> tuple[int, int]:
    response = httpx.get(API, params={"s": query}, timeout=20)
    response.raise_for_status()
    meals = response.json().get("meals") or []
    inserted = skipped = 0
    with SessionLocal() as db:
        for meal in meals:
            external_id = str(meal.get("idMeal") or "")
            if not external_id or db.scalar(select(Recipe.id).where(Recipe.external_id == external_id)):
                skipped += 1
                continue
            ingredients = []
            for i in range(1, 21):
                ingredient = (meal.get(f"strIngredient{i}") or "").strip()
                measure = (meal.get(f"strMeasure{i}") or "").strip()
                if ingredient:
                    ingredients.append(f"{ingredient}: {measure}".strip())
            steps = (meal.get("strInstructions") or "").strip()
            steps = "\n".join(f"{i}. {line.strip()}" for i, line in enumerate(steps.splitlines(), 1) if line.strip())
            db.add(Recipe(
                name_fa=meal.get("strMeal") or "نامشخص",
                name_original=meal.get("strMeal") or "",
                country=meal.get("strArea") or "نامشخص",
                category=meal.get("strCategory") or "نامشخص",
                description="واردشده از TheMealDB؛ ترجمه فارسی هنوز بازبینی نشده است.",
                ingredients_text="\n".join(ingredients),
                steps_text=steps,
                minutes=30,
                servings=2,
                difficulty="نامشخص",
                source_name="TheMealDB",
                source_url=meal.get("strSource") or "",
                source_status="imported_unreviewed",
                external_id=external_id,
            ))
            inserted += 1
        db.commit()
    return inserted, skipped

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="English recipe name or keyword, e.g. chicken")
    args = parser.parse_args()
    init_db()
    inserted, skipped = import_query(args.query)
    print(f"query={args.query!r} inserted={inserted} skipped_duplicates_or_empty={skipped}")
    print("Note: imported records are unreviewed; translations, nutrition and timings are not inferred as verified.")

if __name__ == "__main__":
    main()
