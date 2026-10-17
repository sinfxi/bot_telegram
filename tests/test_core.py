import os
import tempfile

# Tests use the local database configured for the test process.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_foodmind.db")

from foodmind import SAMPLE_RECIPES, SessionLocal, Recipe, init_db, search_recipes, recipe_count

def test_seeded_recipes_are_searchable():
    init_db()
    assert recipe_count() >= len(SAMPLE_RECIPES)
    results = search_recipes("املت")
    assert any(r.name_fa == "املت گوجه‌فرنگی" for r in results)

def test_ingredient_search():
    init_db()
    results = search_recipes(ingredient="عدس")
    assert any("عدس" in r.ingredients_text for r in results)
