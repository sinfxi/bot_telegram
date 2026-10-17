from __future__ import annotations

import asyncio
import html
import logging
import os
import random
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import (
    BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine,
    func, or_, select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("foodmind")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./foodmind.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_fa: Mapped[str] = mapped_column(String(180), index=True)
    name_original: Mapped[str] = mapped_column(String(180), default="")
    country: Mapped[str] = mapped_column(String(100), default="نامشخص", index=True)
    category: Mapped[str] = mapped_column(String(80), default="غذای اصلی", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    ingredients_text: Mapped[str] = mapped_column(Text, default="")
    steps_text: Mapped[str] = mapped_column(Text, default="")
    minutes: Mapped[int] = mapped_column(Integer, default=30)
    servings: Mapped[int] = mapped_column(Integer, default=2)
    difficulty: Mapped[str] = mapped_column(String(30), default="متوسط")
    dietary: Mapped[str] = mapped_column(String(180), default="")
    calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_name: Mapped[str] = mapped_column(String(180), default="نمونه اولیه FoodMind")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_status: Mapped[str] = mapped_column(String(50), default="sample_unverified")
    external_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    favorites: Mapped[list["Favorite"]] = relationship(back_populates="recipe", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[str] = mapped_column(String(40), server_default=func.now())

class Favorite(Base):
    __tablename__ = "favorites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    recipe: Mapped[Recipe] = relationship(back_populates="favorites")
    __table_args__ = (UniqueConstraint("telegram_id", "recipe_id", name="uq_favorite_user_recipe"),)

class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    item: Mapped[str] = mapped_column(String(220))
    checked: Mapped[bool] = mapped_column(Boolean, default=False)

SAMPLE_RECIPES = [
    {"name_fa":"املت گوجه‌فرنگی","name_original":"Persian tomato omelette","country":"ایران","category":"صبحانه","description":"املت ساده با گوجه تازه و تخم‌مرغ.","ingredients_text":"تخم‌مرغ: ۲ عدد\nگوجه‌فرنگی: ۲ عدد\nروغن: ۱ قاشق غذاخوری\nنمک و فلفل: به مقدار لازم","steps_text":"۱. گوجه‌ها را خرد کنید و با روغن روی حرارت متوسط بپزید تا نرم شوند.\n۲. نمک و فلفل را اضافه کنید.\n۳. تخم‌مرغ‌ها را اضافه کنید و هم بزنید تا کاملاً ببندند.","minutes":15,"servings":1,"difficulty":"آسان","dietary":"vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
    {"name_fa":"سالاد یونانی","name_original":"Greek salad","country":"یونان","category":"سالاد","description":"سالادی تازه با خیار، گوجه، زیتون و پنیر فتا.","ingredients_text":"گوجه‌فرنگی: ۲ عدد\nخیار: ۱ عدد\nزیتون: ۸ عدد\nپنیر فتا: ۵۰ گرم\nروغن زیتون و آب‌لیمو: به مقدار لازم","steps_text":"۱. سبزیجات را بشویید و خرد کنید.\n۲. زیتون و پنیر خردشده را اضافه کنید.\n۳. با روغن زیتون و آب‌لیمو مزه‌دار کنید.","minutes":10,"servings":2,"difficulty":"آسان","dietary":"vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
    {"name_fa":"پاستا با سس گوجه","name_original":"Tomato pasta","country":"ایتالیا","category":"غذای اصلی","description":"پاستای خانگی با سس گوجه ساده.","ingredients_text":"پاستا: ۲۰۰ گرم\nگوجه یا گوجه خردشده: ۲۵۰ گرم\nسیر: ۱ حبه\nروغن زیتون: ۱ قاشق غذاخوری\nنمک و فلفل: به مقدار لازم","steps_text":"۱. پاستا را طبق دستور بسته در آب جوش و نمک بپزید.\n۲. سیر خردشده را کوتاه در روغن تفت دهید.\n۳. گوجه را اضافه کنید و ۱۰ تا ۱۵ دقیقه بپزید.\n۴. پاستا را با سس مخلوط و سرو کنید.","minutes":25,"servings":2,"difficulty":"آسان","dietary":"vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
    {"name_fa":"عدسی","name_original":"Persian lentil soup","country":"ایران","category":"سوپ","description":"غذای ساده و اقتصادی بر پایه عدس.","ingredients_text":"عدس: ۱ پیمانه\nپیاز: ۱ عدد\nسیب‌زمینی: ۱ عدد اختیاری\nزردچوبه، نمک و فلفل: به مقدار لازم","steps_text":"۱. عدس را بشویید.\n۲. پیاز خردشده را با کمی روغن و زردچوبه تفت دهید.\n۳. عدس و آب را اضافه کنید و حدود ۳۰ تا ۴۰ دقیقه بپزید.\n۴. در صورت تمایل سیب‌زمینی خردشده را اضافه کنید و تا نرم‌شدن بپزید.","minutes":45,"servings":3,"difficulty":"آسان","dietary":"vegan vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
]
def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(func.count(Recipe.id))) == 0:
            for row in SAMPLE_RECIPES:
                db.add(Recipe(**row))
            db.commit()

def search_recipes(query: str = "", limit: int = 8, country: str = "", ingredient: str = "") -> list[Recipe]:
    with SessionLocal() as db:
        stmt = select(Recipe)
        if query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(or_(Recipe.name_fa.ilike(q), Recipe.name_original.ilike(q), Recipe.description.ilike(q), Recipe.ingredients_text.ilike(q), Recipe.country.ilike(q)))
        if country.strip():
            stmt = stmt.where(Recipe.country.ilike(f"%{country.strip()}%"))
        if ingredient.strip():
            stmt = stmt.where(Recipe.ingredients_text.ilike(f"%{ingredient.strip()}%"))
        return list(db.scalars(stmt.order_by(Recipe.name_fa).limit(max(1, min(limit, 30)))).all())

def get_recipe(recipe_id: int) -> Recipe | None:
    with SessionLocal() as db:
        return db.get(Recipe, recipe_id)

def recipe_count() -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count(Recipe.id))) or 0)

def remember_user(telegram_id: int, display_name: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            db.add(User(telegram_id=telegram_id, display_name=display_name[:160]))
        else:
            user.display_name = display_name[:160]
        db.commit()

def favorite_recipe(telegram_id: int, recipe_id: int) -> bool:
    with SessionLocal() as db:
        existing = db.scalar(select(Favorite).where(Favorite.telegram_id == telegram_id, Favorite.recipe_id == recipe_id))
        if existing:
            db.delete(existing); db.commit(); return False
        if not db.get(Recipe, recipe_id):
            return False
        db.add(Favorite(telegram_id=telegram_id, recipe_id=recipe_id)); db.commit(); return True

def get_favorites(telegram_id: int) -> list[Recipe]:
    with SessionLocal() as db:
        return list(db.scalars(select(Recipe).join(Favorite).where(Favorite.telegram_id == telegram_id).order_by(Recipe.name_fa)).all())

def add_shopping(telegram_id: int, items: list[str]) -> int:
    clean = [x.strip()[:220] for x in items if x.strip()]
    with SessionLocal() as db:
        for item in clean[:30]:
            db.add(ShoppingItem(telegram_id=telegram_id, item=item))
        db.commit()
    return len(clean[:30])

def get_shopping(telegram_id: int) -> list[ShoppingItem]:
    with SessionLocal() as db:
        return list(db.scalars(select(ShoppingItem).where(ShoppingItem.telegram_id == telegram_id).order_by(ShoppingItem.id.desc()).limit(40)).all())

def main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🍽 پیشنهاد غذا", callback_data="recommend"), InlineKeyboardButton(text="🌍 کشف غذا", callback_data="discover")],
        [InlineKeyboardButton(text="🔎 جست‌وجو", callback_data="search"), InlineKeyboardButton(text="🧺 با مواد موجود", callback_data="ingredients")],
        [InlineKeyboardButton(text="🛒 فهرست خرید", callback_data="shopping"), InlineKeyboardButton(text="❤️ ذخیره‌شده‌ها", callback_data="favorites")],
        [InlineKeyboardButton(text="📊 آمار دانشنامه", callback_data="stats"), InlineKeyboardButton(text="ℹ️ راهنما", callback_data="help")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def recipe_keyboard(recipe: Recipe) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ ذخیره / حذف ذخیره", callback_data=f"fav:{recipe.id}")],
        [InlineKeyboardButton(text="🛒 افزودن مواد به فهرست خرید", callback_data=f"shop:{recipe.id}")],
        [InlineKeyboardButton(text="⬅️ منوی اصلی", callback_data="home")],
    ])

def recipe_text(r: Recipe) -> str:
    ingredients = html.escape(r.ingredients_text or "مواد اولیه ثبت نشده")
    steps = html.escape(r.steps_text or "مراحل پخت ثبت نشده")
    source = html.escape(r.source_name or "نامشخص")
    status = "نمونه اولیه؛ نیازمند بررسی منبع" if r.source_status == "sample_unverified" else "منبع واردشده"
    return (f"<b>🍽 {html.escape(r.name_fa)}</b>\n"
            f"🌍 کشور: {html.escape(r.country)} | 🗂 دسته: {html.escape(r.category)}\n"
            f"⏱ زمان: {r.minutes} دقیقه | 👥 نفرات: {r.servings} | 🎯 سختی: {html.escape(r.difficulty)}\n\n"
            f"{html.escape(r.description or '')}\n\n<b>🧺 مواد اولیه</b>\n{ingredients}\n\n"
            f"<b>👨‍🍳 مراحل پخت</b>\n{steps}\n\n"
            f"📚 منبع: {source} ({status})\n"
            "⚠️ ارزش غذایی و آلرژن‌ها تا زمانی که داده معتبر ثبت نشده باشد، تأییدشده محسوب نمی‌شوند.")

dp = Dispatcher()
bot_instance: Bot | None = None

@dp.message(CommandStart())
async def start(message: Message):
    if message.from_user:
        remember_user(message.from_user.id, message.from_user.full_name)
    await message.answer("سلام! به <b>FoodMind AI</b> خوش اومدی 🍲\nاز اینجا غذاهای جهان رو جست‌وجو کن، دستور پخت ببین یا با مواد داخل خونه غذا پیدا کن.", reply_markup=main_keyboard())

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("برای جست‌وجو نام غذا را بفرست. برای جست‌وجوی مواد، مثلاً بنویس: «با سیب‌زمینی».\nاز دکمه‌های منو برای پیشنهاد، کشف غذا، علاقه‌مندی و فهرست خرید استفاده کن.", reply_markup=main_keyboard())

@dp.message(Command("search"))
async def search_cmd(message: Message):
    query = (message.text or "").partition(" ")[2].strip()
    await show_search(message, query)

async def show_search(message: Message, query: str):
    results = search_recipes(query, limit=10)
    if not results:
        await message.answer("چیزی پیدا نکردم. اسم دیگری امتحان کن یا با دکمه «با مواد موجود» جست‌وجو کن.")
        return
    rows = [[InlineKeyboardButton(text=f"🍽 {r.name_fa} · {r.minutes} دقیقه", callback_data=f"recipe:{r.id}")] for r in results]
    rows.append([InlineKeyboardButton(text="⬅️ منو", callback_data="home")])
    await message.answer(f"نتایج جست‌وجو برای «{html.escape(query or 'همه غذاها')}»:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.message()
async def text_search(message: Message):
    if not message.text or message.text.startswith("/"):
        return
    raw = message.text.strip()
    query = re.sub(r"^(با مواد|با|جستجو|جست‌وجو)s*", "", raw, flags=re.I).strip()
    await show_search(message, query)

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.answer()
    if call.message:
        await call.message.edit_text("منوی اصلی FoodMind AI 🍲", reply_markup=main_keyboard())

@dp.callback_query(F.data == "help")
async def help_cb(call: CallbackQuery):
    await call.answer()
    if call.message:
        await call.message.edit_text("🔎 نام غذا یا مواد اولیه را در چت بنویس.\n🍽 پیشنهاد و کشف غذا از دکمه‌های منو در دسترس‌اند.\nاطلاعات نمونه با برچسب نمونه نمایش داده می‌شوند و داده تغذیه‌ای بدون منبع معتبر ادعا نمی‌شود.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "search")
async def search_cb(call: CallbackQuery):
    await call.answer("نام غذا یا ماده اولیه را به‌صورت پیام بفرست.")
    if call.message:
        await call.message.answer("نام غذا یا ماده اولیه را بفرست؛ مثلاً «پاستا» یا «عدس».")

@dp.callback_query(F.data == "ingredients")
async def ingredients_cb(call: CallbackQuery):
    await call.answer("مواد اولیه را ارسال کن.")
    if call.message:
        await call.message.answer("مواد اولیه‌ای که داری را بنویس؛ مثلاً: مرغ، برنج، پیاز")

@dp.callback_query(F.data == "recommend")
async def recommend_cb(call: CallbackQuery):
    await call.answer()
    rows = search_recipes(limit=20)
    if call.message:
        if not rows:
            await call.message.answer("هنوز غذایی در دانشنامه نیست.")
            return
        r = random.choice(rows)
        await call.message.answer("✨ پیشنهاد امروز بر اساس غذاهای ثبت‌شده:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🍽 {r.name_fa}", callback_data=f"recipe:{r.id}")]]))

@dp.callback_query(F.data == "discover")
async def discover_cb(call: CallbackQuery):
    await call.answer()
    with SessionLocal() as db:
        countries = list(db.scalars(select(Recipe.country).distinct().order_by(Recipe.country)).all())
    rows = [[InlineKeyboardButton(text=f"🌍 {c}", callback_data=f"country:{c}")] for c in countries[:20]]
    rows.append([InlineKeyboardButton(text="🎲 غذای تصادفی", callback_data="recommend")])
    if call.message:
        await call.message.edit_text("از کدام کشور غذا کشف کنیم؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("country:"))
async def country_cb(call: CallbackQuery):
    country = call.data.split(":", 1)[1]
    results = search_recipes(country=country, limit=15)
    await call.answer()
    if call.message:
        rows = [[InlineKeyboardButton(text=r.name_fa, callback_data=f"recipe:{r.id}")] for r in results]
        rows.append([InlineKeyboardButton(text="⬅️ منو", callback_data="home")])
        await call.message.edit_text(f"غذاهای ثبت‌شده از {html.escape(country)}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "stats")
async def stats_cb(call: CallbackQuery):
    await call.answer()
    if call.message:
        await call.message.answer(f"📚 تعداد دستورهای ثبت‌شده فعلی: {recipe_count()}\nاین عدد فقط رکوردهای واقعاً موجود در دیتابیس است؛ به معنی پوشش کامل غذاهای جهان نیست.")

@dp.callback_query(F.data == "favorites")
async def favorites_cb(call: CallbackQuery):
    await call.answer()
    favs = get_favorites(call.from_user.id)
    if call.message:
        if not favs:
            await call.message.answer("هنوز غذایی ذخیره نکردی ❤️")
            return
        rows = [[InlineKeyboardButton(text=f"❤️ {r.name_fa}", callback_data=f"recipe:{r.id}")] for r in favs]
        await call.message.answer("غذاهای ذخیره‌شده:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "shopping")
async def shopping_cb(call: CallbackQuery):
    await call.answer()
    items = get_shopping(call.from_user.id)
    if call.message:
        if not items:
            await call.message.answer("فهرست خرید خالی است. اول یک دستور را باز کن و «افزودن مواد» را بزن.")
        else:
            text = "\n".join(("☑️ " if x.checked else "▫️ ") + html.escape(x.item) for x in items)
            await call.message.answer("<b>🛒 فهرست خرید</b>\n" + text)

@dp.callback_query(F.data.startswith("recipe:"))
async def recipe_cb(call: CallbackQuery):
    recipe_id = int(call.data.split(":", 1)[1])
    r = get_recipe(recipe_id)
    await call.answer()
    if call.message:
        if r:
            await call.message.answer(recipe_text(r), reply_markup=recipe_keyboard(r))
        else:
            await call.message.answer("این دستور دیگر در دسترس نیست.")

@dp.callback_query(F.data.startswith("fav:"))
async def fav_cb(call: CallbackQuery):
    recipe_id = int(call.data.split(":", 1)[1])
    added = favorite_recipe(call.from_user.id, recipe_id)
    await call.answer("به علاقه‌مندی‌ها اضافه شد ❤️" if added else "از علاقه‌مندی‌ها حذف شد.")

@dp.callback_query(F.data.startswith("shop:"))
async def shop_cb(call: CallbackQuery):
    r = get_recipe(int(call.data.split(":", 1)[1]))
    await call.answer()
    if r:
        items = [line.split(":", 1)[0].strip() for line in r.ingredients_text.splitlines() if line.strip()]
        count = add_shopping(call.from_user.id, items)
        if call.message:
            await call.message.answer(f"🛒 {count} مورد به فهرست خرید اضافه شد.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_instance
    init_db()
    if BOT_TOKEN:
        bot_instance = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        asyncio.create_task(dp.start_polling(bot_instance, handle_signals=False))
        log.info("Telegram polling started")
    else:
        log.warning("BOT_TOKEN is not set; web/admin API will run without Telegram polling")
    yield
    if bot_instance:
        await dp.stop_polling()
        await bot_instance.session.close()

app = FastAPI(title="FoodMind AI", version="0.1.0", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status":"ok", "service":"FoodMind AI", "recipes":recipe_count()}

@app.get("/api/recipes")
def api_recipes(q: str = "", country: str = "", ingredient: str = "", limit: int = 20):
    rows = search_recipes(q, limit, country, ingredient)
    return [{"id":r.id,"name_fa":r.name_fa,"name_original":r.name_original,"country":r.country,"category":r.category,"minutes":r.minutes,"servings":r.servings,"source_status":r.source_status} for r in rows]

def require_admin(request: Request) -> None:
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="ADMIN_PASSWORD is not configured")
    auth = request.headers.get("x-admin-password", "")
    if auth != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    password = request.query_params.get("key", "")
    if not ADMIN_PASSWORD or password != ADMIN_PASSWORD:
        return HTMLResponse("<meta charset='utf-8'><h2>FoodMind AI · ورود مدیر</h2><form><input name='key' type='password' placeholder='Admin password'><button>ورود</button></form>", status_code=401)
    with SessionLocal() as db:
        users = int(db.scalar(select(func.count(User.id))) or 0)
        total = int(db.scalar(select(func.count(Recipe.id))) or 0)
        samples = int(db.scalar(select(func.count(Recipe.id)).where(Recipe.source_status == "sample_unverified")) or 0)
        recent = list(db.scalars(select(Recipe).order_by(Recipe.id.desc()).limit(30)).all())
    items = "".join(f"<tr><td>{r.id}</td><td>{html.escape(r.name_fa)}</td><td>{html.escape(r.country)}</td><td>{html.escape(r.source_status)}</td></tr>" for r in recent)
    return HTMLResponse(f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>FoodMind Admin</title><style>body{{font-family:Tahoma,Arial;margin:30px;background:#f6f7f8;color:#20252b}}main{{max-width:1000px;margin:auto;background:white;padding:24px;border-radius:14px}}.stats{{display:flex;gap:12px;flex-wrap:wrap}}.stats div{{background:#f0f4f2;padding:18px;border-radius:10px}}table{{width:100%;border-collapse:collapse;margin-top:24px}}td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:right}}</style><main><h1>🍲 FoodMind AI</h1><p>پنل مدیریت دانشنامه</p><section class="stats"><div>دستورها: <b>{total}</b></div><div>کاربران ثبت‌شده: <b>{users}</b></div><div>نمونه‌های نیازمند بررسی: <b>{samples}</b></div></section><h2>آخرین غذاها</h2><table><tr><th>شناسه</th><th>نام</th><th>کشور</th><th>وضعیت منبع</th></tr>{items}</table><p>برای واردکردن داده از اسکریپت scripts/import_themealdb.py استفاده کنید.</p></main></html>""")

@app.get("/")
def index():
    return {"name":"FoodMind AI","message":"دانشنامه هوشمند غذا و آشپزی","docs":"/docs","health":"/health","admin":"/admin"}
