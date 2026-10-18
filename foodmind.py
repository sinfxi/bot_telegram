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
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    item: Mapped[str] = mapped_column(String(220))
    checked: Mapped[bool] = mapped_column(Boolean, default=False)

class MembershipChannel(Base):
    __tablename__ = "membership_channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    chat_id: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    invite_link: Mapped[str] = mapped_column(Text)

SAMPLE_RECIPES = [
    {"name_fa":"املت گوجه‌فرنگی","name_original":"Persian tomato omelette","country":"ایران","category":"صبحانه","description":"املت ساده با گوجه تازه و تخم‌مرغ.","ingredients_text":"تخم‌مرغ: ۲ عدد\nگوجه‌فرنگی: ۲ عدد\nروغن: ۱ قاشق غذاخوری\nنمک و فلفل: به مقدار لازم","steps_text":"۱. گوجه‌ها را خرد کنید و با روغن روی حرارت متوسط بپزید تا نرم شوند.\n۲. نمک و فلفل را اضافه کنید.\n۳. تخم‌مرغ‌ها را اضافه کنید و هم بزنید تا کاملاً ببندند.","minutes":15,"servings":1,"difficulty":"آسان","dietary":"vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
    {"name_fa":"سالاد یونانی","name_original":"Greek salad","country":"یونان","category":"سالاد","description":"سالادی تازه با خیار، گوجه، زیتون و پنیر فتا.","ingredients_text":"گوجه‌فرنگی: ۲ عدد\nخیار: ۱ عدد\nزیتون: ۸ عدد\nپنیر فتا: ۵۰ گرم\nروغن زیتون و آب‌لیمو: به مقدار لازم","steps_text":"۱. سبزیجات را بشویید و خرد کنید.\n۲. زیتون و پنیر خردشده را اضافه کنید.\n۳. با روغن زیتون و آب‌لیمو مزه‌دار کنید.","minutes":10,"servings":2,"difficulty":"آسان","dietary":"vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
    {"name_fa":"پاستا با سس گوجه","name_original":"Tomato pasta","country":"ایتالیا","category":"غذای اصلی","description":"پاستای خانگی با سس گوجه ساده.","ingredients_text":"پاستا: ۲۰۰ گرم\nگوجه یا گوجه خردشده: ۲۵۰ گرم\nسیر: ۱ حبه\nروغن زیتون: ۱ قاشق غذاخوری\nنمک و فلفل: به مقدار لازم","steps_text":"۱. پاستا را طبق دستور بسته در آب جوش و نمک بپزید.\n۲. سیر خردشده را کوتاه در روغن تفت دهید.\n۳. گوجه را اضافه کنید و ۱۰ تا ۱۵ دقیقه بپزید.\n۴. پاستا را با سس مخلوط و سرو کنید.","minutes":25,"servings":2,"difficulty":"آسان","dietary":"vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
    {"name_fa":"عدسی","name_original":"Persian lentil soup","country":"ایران","category":"سوپ","description":"غذای ساده و اقتصادی بر پایه عدس.","ingredients_text":"عدس: ۱ پیمانه\nپیاز: ۱ عدد\nسیب‌زمینی: ۱ عدد اختیاری\nزردچوبه، نمک و فلفل: به مقدار لازم","steps_text":"۱. عدس را بشویید.\n۲. پیاز خردشده را با کمی روغن و زردچوبه تفت دهید.\n۳. عدس و آب را اضافه کنید و حدود ۳۰ تا ۴۰ دقیقه بپزید.\n۴. در صورت تمایل سیب‌زمینی خردشده را اضافه کنید و تا نرم‌شدن بپزید.","minutes":45,"servings":3,"difficulty":"آسان","dietary":"vegan vegetarian","source_name":"FoodMind نمونه اولیه","source_status":"sample_unverified"},
]
EXTRA_RECIPES = [
 {"name_fa":"قورمه‌سبزی","name_original":"Ghormeh Sabzi","country":"ایران","category":"غذای اصلی","description":"خورش سبزی معطر با لوبیا و لیموعمانی.","ingredients_text":"گوشت خورشتی: ۳۰۰ گرم\nسبزی قورمه: ۵۰۰ گرم\nلوبیا قرمز: نصف پیمانه\nپیاز: ۱ عدد\nلیموعمانی: ۲ عدد\nزردچوبه، نمک و فلفل: به مقدار لازم","steps_text":"۱. لوبیا را از قبل خیس کنید.\n۲. پیاز را خرد کرده و با زردچوبه و گوشت تفت دهید.\n۳. سبزی خردشده را جداگانه سرخ کنید و همراه لوبیا و آب به قابلمه بیفزایید.\n۴. حدود ۲ تا ۳ ساعت آرام بپزید؛ لیموعمانی را در نیمه دوم پخت اضافه کنید.","minutes":180,"servings":4,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"خورش قیمه","name_original":"Khoresht Gheymeh","country":"ایران","category":"غذای اصلی","description":"خورش لپه و گوشت با لیموعمانی و سیب‌زمینی.","ingredients_text":"گوشت خورشتی: ۳۰۰ گرم\nلپه: ۱ پیمانه\nپیاز: ۱ عدد\nرب گوجه: ۲ قاشق غذاخوری\nلیموعمانی: ۲ عدد\nسیب‌زمینی: ۲ عدد\nنمک، فلفل و زردچوبه: به مقدار لازم","steps_text":"۱. لپه را بشویید و نیم‌پز کنید.\n۲. پیاز و گوشت را تفت دهید؛ زردچوبه و رب را اضافه کنید.\n۳. لپه، آب و لیموعمانی را اضافه کرده و حدود ۹۰ دقیقه بپزید.\n۴. سیب‌زمینی خلالی را سرخ کرده و هنگام سرو روی خورش بگذارید.","minutes":120,"servings":4,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"زرشک‌پلو با مرغ","name_original":"Zereshk Polo ba Morgh","country":"ایران","category":"غذای اصلی","description":"برنج زعفرانی با مرغ و زرشک شیرین‌وترش.","ingredients_text":"برنج: ۳ پیمانه\nمرغ: ۴ تکه\nزرشک: نصف پیمانه\nپیاز: ۱ عدد\nزعفران دم‌کرده: ۲ قاشق غذاخوری\nرب گوجه: ۱ قاشق غذاخوری\nنمک و ادویه: به مقدار لازم","steps_text":"۱. مرغ را با پیاز، ادویه، رب و آب بپزید تا نرم شود.\n۲. برنج را آبکش کرده و دم کنید.\n۳. زرشک را کوتاه با کمی کره و در صورت تمایل شکر تفت دهید.\n۴. زعفران و زرشک را روی برنج بریزید و با مرغ سرو کنید.","minutes":75,"servings":4,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"کشک بادمجان","name_original":"Kashk-e Bademjan","country":"ایران","category":"پیش‌غذا","description":"پیش‌غذای ایرانی با بادمجان، کشک و نعناع‌داغ.","ingredients_text":"بادمجان: ۴ عدد\nکشک: نصف پیمانه\nپیاز: ۲ عدد\nسیر: ۳ حبه\nنعناع خشک: ۱ قاشق غذاخوری\nگردو: اختیاری\nنمک و فلفل: به مقدار لازم","steps_text":"۱. بادمجان‌ها را کبابی یا سرخ کنید و له کنید.\n۲. پیاز و سیر را طلایی کنید و بادمجان را بیفزایید.\n۳. کمی آب اضافه کرده و ۱۰ دقیقه آرام بپزید.\n۴. کشک را اضافه کنید و با نعناع‌داغ و گردو تزیین کنید.","minutes":40,"servings":4,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"فلافل","name_original":"Falafel","country":"مصر","category":"غذای اصلی","description":"توپک نخود و سبزی معطر با ادویه.","ingredients_text":"نخود خشک خیسانده: ۲ پیمانه\nپیاز: ۱ عدد\nسیر: ۲ حبه\nجعفری: نصف پیمانه\nزیره و گشنیز آسیاب‌شده: هرکدام ۱ قاشق چای‌خوری\nنمک و روغن: به مقدار لازم","steps_text":"۱. نخود خیسانده و آبکش‌شده را با پیاز، سیر و سبزی چرخ کنید.\n۲. ادویه و نمک را اضافه کنید و مخلوط را ۳۰ دقیقه خنک کنید.\n۳. گلوله‌های کوچک بسازید.\n۴. در روغن داغ تا طلایی‌شدن سرخ کنید یا در فر چرب‌شده بپزید.","minutes":50,"servings":4,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"حمص","name_original":"Hummus","country":"لبنان","category":"پیش‌غذا","description":"دیپ نخود و ارده با آب‌لیمو و سیر.","ingredients_text":"نخود پخته: ۲ پیمانه\nارده: ۳ قاشق غذاخوری\nآب‌لیمو: ۲ قاشق غذاخوری\nسیر: ۱ حبه\nروغن زیتون: ۱ قاشق غذاخوری\nنمک و آب: به مقدار لازم","steps_text":"۱. نخود، ارده، آب‌لیمو، سیر و نمک را در غذاساز بریزید.\n۲. هنگام مخلوط‌کردن کمی آب سرد اضافه کنید تا بافت نرم شود.\n۳. در ظرف بکشید و روغن زیتون روی آن بریزید.","minutes":10,"servings":4,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"شاکشوکا","name_original":"Shakshuka","country":"تونس","category":"صبحانه","description":"تخم‌مرغ در سس گوجه و فلفل ادویه‌دار.","ingredients_text":"تخم‌مرغ: ۳ عدد\nگوجه خردشده: ۳۰۰ گرم\nفلفل دلمه‌ای: ۱ عدد\nپیاز: ۱ عدد\nسیر: ۲ حبه\nپاپریکا و زیره: به مقدار لازم","steps_text":"۱. پیاز و فلفل را خرد کرده و نرم تفت دهید.\n۲. سیر، گوجه و ادویه را اضافه کنید و ۱۰ تا ۱۵ دقیقه بپزید.\n۳. در سس گودی ایجاد کنید و تخم‌مرغ‌ها را داخل آن بشکنید.\n۴. درِ تابه را بگذارید تا سفیده‌ها ببندند.","minutes":25,"servings":2,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"لازانیا","name_original":"Lasagna","country":"ایتالیا","category":"غذای اصلی","description":"لایه‌های ورق لازانیا، سس گوشت و پنیر.","ingredients_text":"ورق لازانیا: ۹ عدد\nگوشت چرخ‌کرده: ۳۰۰ گرم\nپیاز: ۱ عدد\nسس گوجه: ۲ پیمانه\nپنیر موزارلا: ۲۰۰ گرم\nسس بشامل: ۱ پیمانه","steps_text":"۱. پیاز و گوشت را تفت دهید و سس گوجه را اضافه کنید.\n۲. در ظرف فر، سس، ورق لازانیا، مایه گوشت و پنیر را لایه‌لایه بچینید.\n۳. بشامل و پنیر را روی لایه آخر بریزید.\n۴. در فر ۱۸۰ درجه حدود ۳۵ تا ۴۵ دقیقه بپزید و پیش از برش کمی استراحت دهید.","minutes":60,"servings":4,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"پیتزای مارگاریتا","name_original":"Pizza Margherita","country":"ایتالیا","category":"غذای اصلی","description":"پیتزای ساده با گوجه، موزارلا و ریحان.","ingredients_text":"خمیر پیتزا: ۱ عدد\nسس گوجه: نصف پیمانه\nپنیر موزارلا: ۱۵۰ گرم\nریحان تازه: چند برگ\nروغن زیتون: ۱ قاشق غذاخوری","steps_text":"۱. فر را با بالاترین دمای مناسب از قبل گرم کنید.\n۲. خمیر را باز کرده و لایه نازکی از سس بمالید.\n۳. موزارلا و کمی روغن زیتون اضافه کنید.\n۴. حدود ۸ تا ۱۲ دقیقه بپزید و پس از خروج از فر ریحان بیفزایید.","minutes":25,"servings":2,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"کربونارا","name_original":"Spaghetti Carbonara","country":"ایتالیا","category":"غذای اصلی","description":"اسپاگتی با تخم‌مرغ، پنیر و فلفل سیاه.","ingredients_text":"اسپاگتی: ۲۰۰ گرم\nتخم‌مرغ: ۲ عدد\nپنیر پارمزان: ۵۰ گرم\nبیکن یا گوشت دودی: ۸۰ گرم\nفلفل سیاه: به مقدار لازم","steps_text":"۱. اسپاگتی را در آب نمک بپزید و کمی از آب پخت نگه دارید.\n۲. گوشت دودی را در تابه تفت دهید.\n۳. تخم‌مرغ و پنیر را جداگانه مخلوط کنید.\n۴. پاستای داغ را از روی حرارت با گوشت و مخلوط تخم‌مرغ ترکیب کنید؛ با کمی آب پخت سس را یکدست کنید.","minutes":20,"servings":2,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"برنج سرخ‌شده","name_original":"Fried Rice","country":"چین","category":"غذای اصلی","description":"برنج پخته با سبزیجات و تخم‌مرغ در تابه داغ.","ingredients_text":"برنج پخته سرد: ۳ پیمانه\nتخم‌مرغ: ۲ عدد\nهویج خردشده: ۱ عدد\nنخودفرنگی: نصف پیمانه\nپیازچه: ۲ ساقه\nسس سویا: ۲ قاشق غذاخوری","steps_text":"۱. تخم‌مرغ را سریع هم بزنید و از تابه خارج کنید.\n۲. هویج و نخودفرنگی را در کمی روغن تفت دهید.\n۳. برنج سرد را اضافه کنید و روی حرارت زیاد هم بزنید.\n۴. سس سویا، تخم‌مرغ و پیازچه را اضافه کرده و داغ سرو کنید.","minutes":20,"servings":3,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"کاری مرغ","name_original":"Chicken Curry","country":"هند","category":"غذای اصلی","description":"مرغ در سس گوجه، پیاز و ادویه کاری.","ingredients_text":"مرغ خردشده: ۴۰۰ گرم\nپیاز: ۱ عدد\nگوجه خردشده: ۲ عدد\nماست یا شیر نارگیل: نصف پیمانه\nادویه کاری: ۲ قاشق چای‌خوری\nسیر و زنجبیل: به مقدار لازم","steps_text":"۱. پیاز را تفت دهید و سیر و زنجبیل را اضافه کنید.\n۲. ادویه کاری و مرغ را اضافه کرده و چند دقیقه تفت دهید.\n۳. گوجه و ماست یا شیر نارگیل را بیفزایید.\n۴. با درِ نیمه‌باز ۲۰ تا ۲۵ دقیقه بپزید تا مرغ کاملاً مغزپخت شود.","minutes":40,"servings":4,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"تاکوی مرغ","name_original":"Chicken Tacos","country":"مکزیک","category":"غذای اصلی","description":"نان ترتیلا با مرغ ادویه‌دار و سبزیجات تازه.","ingredients_text":"مرغ نواری: ۳۰۰ گرم\nنان ترتیلا: ۶ عدد\nفلفل دلمه‌ای: ۱ عدد\nکاهو و گوجه: به مقدار لازم\nآب‌لیمو: ۱ قاشق غذاخوری\nپاپریکا و زیره: به مقدار لازم","steps_text":"۱. مرغ را با آب‌لیمو و ادویه مزه‌دار کنید.\n۲. مرغ و فلفل را در تابه داغ بپزید تا مرغ کاملاً پخته شود.\n۳. ترتیلاها را گرم کنید.\n۴. مرغ، کاهو و گوجه را داخل نان بریزید و سرو کنید.","minutes":30,"servings":3,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"راتاتویی","name_original":"Ratatouille","country":"فرانسه","category":"غذای اصلی","description":"خوراک سبزیجات مدیترانه‌ای با گوجه و بادمجان.","ingredients_text":"بادمجان: ۱ عدد\nکدو سبز: ۲ عدد\nفلفل دلمه‌ای: ۱ عدد\nگوجه: ۳ عدد\nپیاز: ۱ عدد\nسیر، آویشن و روغن زیتون: به مقدار لازم","steps_text":"۱. همه سبزیجات را به قطعات یکسان خرد کنید.\n۲. پیاز و سیر را تفت دهید و گوجه را اضافه کنید.\n۳. بادمجان، کدو و فلفل را اضافه کنید و با آویشن مزه‌دار کنید.\n۴. در ظرف را بگذارید و ۳۰ تا ۴۰ دقیقه آرام بپزید تا سبزیجات نرم شوند.","minutes":50,"servings":4,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"سوپ مرغ و سبزیجات","name_original":"Chicken Vegetable Soup","country":"بین‌المللی","category":"سوپ","description":"سوپ خانگی گرم با مرغ، هویج و سبزیجات.","ingredients_text":"مرغ: ۲۵۰ گرم\nهویج: ۲ عدد\nسیب‌زمینی: ۱ عدد\nپیاز: ۱ عدد\nآب مرغ یا آب: ۱ لیتر\nرشته سوپی: نصف پیمانه","steps_text":"۱. پیاز و مرغ را با آب بپزید و کف آن را بگیرید.\n۲. هویج و سیب‌زمینی خردشده را اضافه کنید.\n۳. پس از نرم‌شدن مرغ آن را ریش‌ریش کنید.\n۴. رشته را اضافه کنید و طبق زمان بسته بپزید؛ نمک و فلفل را تنظیم کنید.","minutes":50,"servings":4,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"پنکیک","name_original":"Pancakes","country":"آمریکا","category":"صبحانه","description":"پنکیک نرم برای صبحانه با عسل یا میوه.","ingredients_text":"آرد: ۱ پیمانه\nشیر: ۱ پیمانه\nتخم‌مرغ: ۱ عدد\nبیکینگ‌پودر: ۲ قاشق چای‌خوری\nشکر: ۱ قاشق غذاخوری\nکره آب‌شده: ۲ قاشق غذاخوری","steps_text":"۱. مواد خشک را مخلوط کنید.\n۲. شیر، تخم‌مرغ و کره را اضافه کرده و فقط تا یکدست‌شدن هم بزنید.\n۳. مقدار کمی از مایه را روی تابه چرب‌شده بریزید.\n۴. وقتی حباب زد برگردانید و سمت دیگر را طلایی کنید.","minutes":20,"servings":3,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"براونی شکلاتی","name_original":"Chocolate Brownies","country":"آمریکا","category":"دسر","description":"کیک شکلاتی فشرده با بافت مرطوب.","ingredients_text":"شکلات تلخ: ۱۵۰ گرم\nکره: ۱۰۰ گرم\nشکر: سه‌چهارم پیمانه\nتخم‌مرغ: ۲ عدد\nآرد: نصف پیمانه\nپودر کاکائو: ۲ قاشق غذاخوری","steps_text":"۱. فر را روی ۱۷۵ درجه گرم کنید و قالب را آماده کنید.\n۲. شکلات و کره را ذوب کنید و کمی خنک کنید.\n۳. شکر و تخم‌مرغ را اضافه کنید، سپس آرد و کاکائو را آرام مخلوط کنید.\n۴. در قالب بریزید و حدود ۲۰ تا ۲۵ دقیقه بپزید؛ وسط براونی کمی مرطوب بماند.","minutes":35,"servings":8,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"دال عدس","name_original":"Indian Red Lentil Dal","country":"هند","category":"غذای اصلی","description":"خوراک عدس قرمز با ادویه‌های گرم.","ingredients_text":"عدس قرمز: ۱ پیمانه\nپیاز: ۱ عدد\nگوجه: ۲ عدد\nسیر: ۲ حبه\nزردچوبه و زیره: هرکدام نصف قاشق چای‌خوری\nآب: ۳ پیمانه","steps_text":"۱. پیاز را تفت دهید و سیر و ادویه‌ها را اضافه کنید.\n۲. گوجه خردشده و عدس شسته را بیفزایید.\n۳. آب را اضافه کنید و ۲۰ تا ۲۵ دقیقه بپزید تا عدس نرم شود.\n۴. نمک را تنظیم کنید و با برنج یا نان سرو کنید.","minutes":35,"servings":3,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"سوشی ساده","name_original":"Simple Sushi Rolls","country":"ژاپن","category":"غذای اصلی","description":"رول برنج ژاپنی با خیار و آووکادو؛ مناسب نسخه گیاهی.","ingredients_text":"برنج سوشی پخته: ۲ پیمانه\nورق نوری: ۳ عدد\nخیار: نصف عدد\nآووکادو: ۱ عدد\nسرکه برنج: ۲ قاشق غذاخوری\nنمک و شکر: مقدار کم","steps_text":"۱. برنج پخته را با سرکه برنج، کمی نمک و شکر مخلوط کنید و خنک کنید.\n۲. ورق نوری را روی حصیر بگذارید و لایه نازکی برنج روی آن پخش کنید.\n۳. خیار و آووکادو را در مرکز قرار دهید و محکم رول کنید.\n۴. با چاقوی مرطوب به قطعات برش بزنید.","minutes":45,"servings":2,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"سالاد تبوله","name_original":"Tabbouleh","country":"لبنان","category":"سالاد","description":"سالاد جعفری و گوجه با بلغور و آب‌لیمو.","ingredients_text":"جعفری خردشده: ۲ پیمانه\nگوجه: ۲ عدد\nبلغور ریز: یک‌چهارم پیمانه\nنعناع: کمی\nآب‌لیمو: ۳ قاشق غذاخوری\nروغن زیتون: ۲ قاشق غذاخوری","steps_text":"۱. بلغور را با کمی آب خیس کنید تا نرم شود و آب اضافی را بگیرید.\n۲. جعفری، نعناع و گوجه را ریز خرد کنید.\n۳. مواد را با بلغور مخلوط کنید.\n۴. آب‌لیمو، روغن زیتون و نمک را اضافه کنید و خنک سرو کنید.","minutes":20,"servings":3,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"دلمه برگ مو","name_original":"Stuffed Grape Leaves","country":"ایران","category":"غذای اصلی","description":"برگ مو پرشده با برنج، سبزی و لپه.","ingredients_text":"برگ مو: ۳۰ عدد\nبرنج: نصف پیمانه\nلپه نیم‌پز: نصف پیمانه\nسبزی دلمه: ۱ پیمانه\nپیاز: ۱ عدد\nآب‌لیمو یا سرکه: ۲ قاشق غذاخوری","steps_text":"۱. برنج را نیم‌پز کنید و با لپه، سبزی و پیاز تفت‌داده مخلوط کنید.\n۲. برگ‌ها را آماده کنید و مقدار کمی مایه در هر برگ بگذارید.\n۳. برگ‌ها را محکم بپیچید و فشرده در قابلمه بچینید.\n۴. کمی آب و آب‌لیمو اضافه کنید و با حرارت کم حدود ۴۵ تا ۶۰ دقیقه بپزید.","minutes":80,"servings":5,"difficulty":"متوسط","source_status":"sample_unverified"},
 {"name_fa":"چیکن شنیتسل","name_original":"Chicken Schnitzel","country":"اتریش","category":"غذای اصلی","description":"فیله مرغ نازک با پوشش سوخاری ترد.","ingredients_text":"سینه مرغ: ۲ عدد\nآرد: نصف پیمانه\nتخم‌مرغ: ۲ عدد\nپودر سوخاری: ۱ پیمانه\nنمک، فلفل و روغن: به مقدار لازم","steps_text":"۱. مرغ را به ورقه‌های نازک برش دهید و کمی بکوبید.\n۲. هر تکه را به ترتیب در آرد، تخم‌مرغ زده‌شده و پودر سوخاری بغلتانید.\n۳. در تابه با روغن متوسط سرخ کنید تا طلایی و کاملاً مغزپخت شود.\n۴. روی دستمال روغن‌گیر بگذارید و با لیمو سرو کنید.","minutes":30,"servings":2,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"نودل رامن ساده","name_original":"Simple Ramen","country":"ژاپن","category":"سوپ","description":"کاسه نودل با آبگوشت، قارچ و تخم‌مرغ.","ingredients_text":"نودل: ۲ بسته\nآب مرغ یا سبزیجات: ۱ لیتر\nقارچ: ۱۵۰ گرم\nتخم‌مرغ: ۲ عدد\nسس سویا: ۲ قاشق غذاخوری\nپیازچه: ۲ ساقه","steps_text":"۱. تخم‌مرغ‌ها را حدود ۷ تا ۹ دقیقه بپزید و پوست بگیرید.\n۲. آبگوشت را با سس سویا گرم کنید و قارچ را در آن بپزید.\n۳. نودل را طبق دستور بسته بپزید و در کاسه بریزید.\n۴. آبگوشت و قارچ را اضافه کنید و با تخم‌مرغ و پیازچه سرو کنید.","minutes":25,"servings":2,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"سالاد سزار با مرغ","name_original":"Chicken Caesar Salad","country":"آمریکا","category":"سالاد","description":"کاهو، مرغ گریل‌شده، کروتان و سس سزار.","ingredients_text":"کاهو: ۱ بوته\nسینه مرغ: ۲ عدد\nنان تست مکعبی: ۱ پیمانه\nپنیر پارمزان: ۴۰ گرم\nسس سزار: ۴ قاشق غذاخوری","steps_text":"۱. مرغ را با نمک و فلفل مزه‌دار کنید و کاملاً بپزید؛ سپس برش بزنید.\n۲. نان مکعبی را با کمی روغن برشته کنید.\n۳. کاهو را بشویید و خشک کنید.\n۴. کاهو، سس، مرغ، کروتان و پنیر را درست پیش از سرو مخلوط کنید.","minutes":25,"servings":2,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"کیک هویج","name_original":"Carrot Cake","country":"بریتانیا","category":"دسر","description":"کیک ادویه‌ای با هویج رنده‌شده.","ingredients_text":"هویج رنده‌شده: ۲ پیمانه\nآرد: ۲ پیمانه\nتخم‌مرغ: ۳ عدد\nشکر: ۱ پیمانه\nروغن: سه‌چهارم پیمانه\nدارچین: ۱ قاشق چای‌خوری\nبیکینگ‌پودر: ۲ قاشق چای‌خوری","steps_text":"۱. فر را روی ۱۷۵ درجه گرم کنید.\n۲. تخم‌مرغ، شکر و روغن را مخلوط کنید.\n۳. آرد، دارچین و بیکینگ‌پودر را اضافه کنید و سپس هویج را هم بزنید.\n۴. در قالب بریزید و ۳۵ تا ۴۵ دقیقه بپزید تا خلال دندان تمیز بیرون بیاید.","minutes":55,"servings":8,"difficulty":"آسان","source_status":"sample_unverified"},
 {"name_fa":"خوراک سبزیجات مدیترانه‌ای","name_original":"Mediterranean Vegetable Stew","country":"یونان","category":"غذای اصلی","description":"خوراک ساده لوبیا و سبزیجات با گوجه و سبزی معطر.","ingredients_text":"لوبیای سفید پخته: ۲ پیمانه\nگوجه خردشده: ۲ پیمانه\nپیاز: ۱ عدد\nهویج: ۱ عدد\nسیر: ۲ حبه\nروغن زیتون و آویشن: به مقدار لازم","steps_text":"۱. پیاز، هویج و سیر را خرد کرده و تفت دهید.\n۲. گوجه، لوبیا، آویشن و کمی آب را اضافه کنید.\n۳. ۲۵ تا ۳۰ دقیقه آرام بپزید تا سس غلیظ شود.\n۴. نمک و فلفل را تنظیم کرده و با نان سرو کنید.","minutes":40,"servings":4,"difficulty":"آسان","source_status":"sample_unverified"}
]

def init_db() -> None:
    Base.metadata.create_all(engine)
    # Seed newly added dishes even when the database already contains older rows.
    with SessionLocal() as db:
        existing = set(db.scalars(select(Recipe.name_fa)).all())
        for row in SAMPLE_RECIPES + EXTRA_RECIPES:
            if row['name_fa'] not in existing:
                db.add(Recipe(**row))
                existing.add(row['name_fa'])
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

def is_admin(telegram_id: int | None) -> bool:
    return bool(ADMIN_ID and telegram_id == ADMIN_ID)

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 آمار", callback_data="admin:stats"),
         InlineKeyboardButton(text="📚 مدیریت غذاها", callback_data="admin:recipes")],
        [InlineKeyboardButton(text="➕ افزودن غذا", callback_data="admin:add")],
        [InlineKeyboardButton(text="🔐 عضویت اجباری", callback_data="admin:membership")],
        [InlineKeyboardButton(text="⬅️ منوی اصلی", callback_data="home")],
    ])

class AddRecipeFlow(StatesGroup):
    name = State()
    country = State()
    category = State()
    minutes = State()
    servings = State()
    ingredients = State()
    steps = State()

class MembershipFlow(StatesGroup):
    title = State()
    chat_id = State()
    invite_link = State()

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

dp = Dispatcher(storage=MemoryStorage())
bot_instance: Bot | None = None

def list_required_channels() -> list[MembershipChannel]:
    with SessionLocal() as db:
        return list(db.scalars(select(MembershipChannel).order_by(MembershipChannel.id)).all())

def membership_keyboard(channels: list[MembershipChannel]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"عضویت در {c.title}"[:64], url=c.invite_link)] for c in channels]
    rows.append([InlineKeyboardButton(text="✅ بررسی عضویت", callback_data="membership:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def user_has_required_memberships(user_id: int, telegram_bot: Bot) -> tuple[bool, str | None]:
    channels = list_required_channels()
    for channel in channels:
        try:
            member = await telegram_bot.get_chat_member(chat_id=channel.chat_id, user_id=user_id)
            if member.status not in ("member", "administrator", "creator") and not (member.status == "restricted" and getattr(member, "is_member", False)):
                return False, channel.title
        except Exception:
            log.exception("Membership verification failed for configured chat %s", channel.chat_id)
            return False, channel.title
    return True, None

async def show_membership_gate(message_or_call: Any, telegram_bot: Bot) -> None:
    channels = list_required_channels()
    text = "🔐 برای استفاده از FoodMind AI، ابتدا در کانال‌ها/گروه‌های زیر عضو شو و بعد «بررسی عضویت» را بزن."
    if not channels:
        return
    markup = membership_keyboard(channels)
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup)
    elif message_or_call.message:
        await message_or_call.message.answer(text, reply_markup=markup)
        await message_or_call.answer()

class MembershipGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if not user or is_admin(user.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "membership:check":
            return await handler(event, data)
        channels = list_required_channels()
        if not channels:
            return await handler(event, data)
        ok, failed_title = await user_has_required_memberships(user.id, data["bot"])
        if ok:
            return await handler(event, data)
        text = "🔐 برای شروع، ابتدا عضو کانال/گروه‌های اجباری شو و سپس عضویتت را بررسی کن."
        markup = membership_keyboard(channels)
        if isinstance(event, Message):
            await event.answer(text, reply_markup=markup)
        elif isinstance(event, CallbackQuery):
            await event.answer("ابتدا باید در کانال‌ها/گروه‌های اجباری عضو شوی.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=markup)
        return None

dp.message.outer_middleware(MembershipGuard())
dp.callback_query.outer_middleware(MembershipGuard())

@dp.callback_query(F.data == "membership:check")
async def membership_check(call: CallbackQuery):
    channels = list_required_channels()
    ok, failed_title = await user_has_required_memberships(call.from_user.id, call.bot)
    if not ok:
        await call.answer("هنوز عضویت کامل نیست یا بررسی کانال ممکن نیست.", show_alert=True)
        if call.message:
            await call.message.answer(f"لطفاً عضویت در «{html.escape(failed_title or 'کانال اجباری')}» را بررسی کن و دوباره امتحان کن.", reply_markup=membership_keyboard(channels))
        return
    remember_user(call.from_user.id, call.from_user.full_name)
    await call.answer("عضویت تأیید شد 🎉")
    if call.message:
        await call.message.answer("عالیه! حالا می‌تونی از ربات استفاده کنی 🍲", reply_markup=main_keyboard())

@dp.message(CommandStart())
async def start(message: Message):
    if message.from_user:
        remember_user(message.from_user.id, message.from_user.full_name)
    keyboard = main_keyboard()
    if message.from_user and is_admin(message.from_user.id):
        keyboard = InlineKeyboardMarkup(inline_keyboard=main_keyboard().inline_keyboard + [[InlineKeyboardButton(text="🛠 پنل ادمین", callback_data="admin:menu")]])
    await message.answer("سلام! به <b>FoodMind AI</b> خوش اومدی 🍲\\nاز اینجا غذاهای جهان رو جست‌وجو کن، دستور پخت ببین یا با مواد داخل خونه غذا پیدا کن.", reply_markup=keyboard)

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("برای جست‌وجو نام غذا را بفرست. برای جست‌وجوی مواد، مثلاً بنویس: «با سیب‌زمینی».\nاز دکمه‌های منو برای پیشنهاد، کشف غذا، علاقه‌مندی و فهرست خرید استفاده کن.", reply_markup=main_keyboard())

@dp.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ این بخش فقط برای مدیر ربات است.")
        return
    await state.clear()
    await message.answer("🛠 <b>پنل مدیریت FoodMind AI</b>", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin:membership")
async def admin_membership(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    await state.clear()
    await call.answer()
    channels = list_required_channels()
    rows = [[InlineKeyboardButton(text=f"🗑 حذف {c.title}"[:64], callback_data=f"admin:membership:delete:{c.id}")] for c in channels]
    rows.append([InlineKeyboardButton(text="➕ افزودن کانال/گروه", callback_data="admin:membership:add")])
    rows.append([InlineKeyboardButton(text="⬅️ پنل ادمین", callback_data="admin:menu")])
    text = "🔐 <b>مدیریت عضویت اجباری</b>\nکاربر تا زمانی که عضو همه موارد این فهرست نباشد، نمی‌تواند از ربات استفاده کند. ربات باید در هر کانال/گروه دسترسی بررسی عضویت داشته باشد."
    if call.message:
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "admin:membership:add")
async def admin_membership_add(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    await state.set_state(MembershipFlow.title)
    await call.answer()
    if call.message:
        await call.message.answer("عنوان کانال یا گروه را بفرست؛ مثلاً «کانال آموزش آشپزی». برای لغو /cancel را بفرست.")

@dp.callback_query(F.data.startswith("admin:membership:delete:"))
async def admin_membership_delete(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    try:
        channel_id = int(call.data.rsplit(":", 1)[1])
    except ValueError:
        await call.answer("شناسه نامعتبر است.", show_alert=True); return
    with SessionLocal() as db:
        channel = db.get(MembershipChannel, channel_id)
        if channel:
            db.delete(channel); db.commit()
            result = "مورد عضویت حذف شد."
        else:
            result = "مورد پیدا نشد."
    await call.answer(result, show_alert=True)
    if call.message:
        await call.message.answer("فهرست عضویت اجباری:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 حذف {c.title}"[:64], callback_data=f"admin:membership:delete:{c.id}")]
            for c in list_required_channels()
        ] + [[InlineKeyboardButton(text="➕ افزودن کانال/گروه", callback_data="admin:membership:add")],
             [InlineKeyboardButton(text="⬅️ پنل ادمین", callback_data="admin:menu")]]))

@dp.message(MembershipFlow.title)
async def admin_membership_title(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    title = (message.text or "").strip()
    if not title:
        await message.answer("عنوان خالی است؛ دوباره بفرست."); return
    await state.update_data(membership_title=title[:180])
    await state.set_state(MembershipFlow.chat_id)
    await message.answer("شناسه چت را بفرست؛ برای کانال عمومی مثل @channel و برای کانال خصوصی مثل -1001234567890. ربات باید ادمین کانال/گروه باشد.")

@dp.message(MembershipFlow.chat_id)
async def admin_membership_chat_id(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    chat_id = (message.text or "").strip()
    if not (chat_id.startswith("@") or re.fullmatch(r"-?\d+", chat_id)):
        await message.answer("شناسه نامعتبر است. @username یا شناسه عددی چت را بفرست."); return
    await state.update_data(membership_chat_id=chat_id)
    await state.set_state(MembershipFlow.invite_link)
    await message.answer("لینک عضویت را بفرست؛ مانند https://t.me/channel یا لینک دعوت خصوصی.")

@dp.message(MembershipFlow.invite_link)
async def admin_membership_invite_link(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    link = (message.text or "").strip()
    if not re.match(r"^https?://t\.me/\S+$", link):
        await message.answer("لطفاً لینک معتبر تلگرام با قالب https://t.me/... بفرست."); return
    data = await state.get_data()
    try:
        # Verify the bot can access the target before saving a rule users cannot pass.
        await message.bot.get_chat(data["membership_chat_id"])
        with SessionLocal() as db:
            existing = db.scalar(select(MembershipChannel).where(MembershipChannel.chat_id == data["membership_chat_id"]))
            if existing:
                existing.title = data["membership_title"]
                existing.invite_link = link
            else:
                db.add(MembershipChannel(title=data["membership_title"], chat_id=data["membership_chat_id"], invite_link=link))
            db.commit()
    except Exception:
        log.exception("Could not register required membership chat")
        await message.answer("❌ ربات به این کانال/گروه دسترسی ندارد. ابتدا ربات را به کانال/گروه اضافه و ادمین کن، سپس دوباره تلاش کن.")
        return
    await state.clear()
    await message.answer(f"✅ عضویت اجباری «{html.escape(data['membership_title'])}» ثبت شد.", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin:menu")
async def admin_menu(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    await state.clear(); await call.answer()
    if call.message: await call.message.answer("🛠 <b>پنل مدیریت FoodMind AI</b>", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    await call.answer()
    with SessionLocal() as db:
        users = int(db.scalar(select(func.count(User.id))) or 0)
        recipes = int(db.scalar(select(func.count(Recipe.id))) or 0)
        favorites = int(db.scalar(select(func.count(Favorite.id))) or 0)
        unreviewed = int(db.scalar(select(func.count(Recipe.id)).where(Recipe.source_status.in_(["sample_unverified", "imported_unreviewed"]))) or 0)
    if call.message:
        await call.message.answer(f"📊 <b>آمار مدیریتی</b>\n🍽 دستورها: {recipes}\n👤 کاربران ثبت‌شده: {users}\n❤️ ذخیره‌ها: {favorites}\n🔎 نیازمند بررسی منبع: {unreviewed}")

@dp.callback_query(F.data == "admin:recipes")
async def admin_recipes(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    await call.answer()
    rows = search_recipes(limit=15)
    buttons = [[InlineKeyboardButton(text=f"🍽 {r.name_fa}", callback_data=f"recipe:{r.id}"), InlineKeyboardButton(text="🗑 حذف", callback_data=f"admin:delete:{r.id}")] for r in rows]
    buttons.append([InlineKeyboardButton(text="⬅️ پنل ادمین", callback_data="admin:menu")])
    if call.message: await call.message.answer("📚 <b>مدیریت غذاها</b>\nبرای حذف هر غذا دکمه حذف را بزن:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("admin:delete:"))
async def admin_delete_recipe(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    recipe_id = int(call.data.rsplit(":", 1)[1])
    with SessionLocal() as db:
        recipe = db.get(Recipe, recipe_id)
        if recipe:
            db.delete(recipe); db.commit(); result = "غذا حذف شد."
        else: result = "غذا پیدا نشد."
    await call.answer(result, show_alert=True)

@dp.callback_query(F.data == "admin:add")
async def admin_add_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز", show_alert=True); return
    await state.set_state(AddRecipeFlow.name); await call.answer()
    if call.message: await call.message.answer("نام غذا را بفرست. برای لغو /cancel را ارسال کن.")

@dp.message(Command("cancel"), StateFilter("*"))
async def admin_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("عملیات لغو شد.")

@dp.message(AddRecipeFlow.name)
async def admin_add_name(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    await state.update_data(name=(message.text or "").strip()[:180]); await state.set_state(AddRecipeFlow.country)
    await message.answer("کشور یا منطقهٔ این غذا؟")

@dp.message(AddRecipeFlow.country)
async def admin_add_country(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    await state.update_data(country=(message.text or "نامشخص").strip()[:100]); await state.set_state(AddRecipeFlow.category)
    await message.answer("دسته‌بندی غذا؟ مثلاً غذای اصلی، صبحانه، دسر یا نوشیدنی")

@dp.message(AddRecipeFlow.category)
async def admin_add_category(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    await state.update_data(category=(message.text or "غذای اصلی").strip()[:80]); await state.set_state(AddRecipeFlow.minutes)
    await message.answer("زمان آماده‌سازی به دقیقه؟ فقط عدد بفرست.")

@dp.message(AddRecipeFlow.minutes)
async def admin_add_minutes(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    try:
        minutes = int((message.text or "").strip())
        if not 1 <= minutes <= 1440: raise ValueError()
    except ValueError:
        await message.answer("یک عدد بین ۱ تا ۱۴۴۰ وارد کن."); return
    await state.update_data(minutes=minutes); await state.set_state(AddRecipeFlow.servings)
    await message.answer("این دستور برای چند نفر است؟ فقط عدد بفرست.")

@dp.message(AddRecipeFlow.servings)
async def admin_add_servings(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    try:
        servings = int((message.text or "").strip())
        if not 1 <= servings <= 100: raise ValueError()
    except ValueError:
        await message.answer("یک عدد بین ۱ تا ۱۰۰ وارد کن."); return
    await state.update_data(servings=servings); await state.set_state(AddRecipeFlow.ingredients)
    await message.answer("مواد اولیه را بفرست؛ هر ماده را در یک خط بنویس.")

@dp.message(AddRecipeFlow.ingredients)
async def admin_add_ingredients(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    ingredients = (message.text or "").strip()
    if len(ingredients) < 3:
        await message.answer("لطفاً مواد اولیه را کامل‌تر وارد کن."); return
    await state.update_data(ingredients=ingredients[:10000]); await state.set_state(AddRecipeFlow.steps)
    await message.answer("مراحل پخت را بفرست؛ هر مرحله را در یک خط بنویس.")

@dp.message(AddRecipeFlow.steps)
async def admin_add_steps(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await state.clear(); await message.answer("⛔ دسترسی غیرمجاز."); return
    steps = (message.text or "").strip()
    if len(steps) < 5:
        await message.answer("مراحل پخت را کامل‌تر وارد کن."); return
    data = await state.get_data()
    with SessionLocal() as db:
        recipe = Recipe(name_fa=data["name"], country=data["country"], category=data["category"],
            description="دستور ثبت‌شده توسط مدیر.", ingredients_text=data["ingredients"],
            steps_text=steps[:15000], minutes=data["minutes"], servings=data["servings"],
            difficulty="نامشخص", source_name="ثبت‌شده توسط مدیر", source_status="admin_entered")
        db.add(recipe); db.commit(); db.refresh(recipe)
        recipe_id, recipe_name = recipe.id, recipe.name_fa
    await state.clear()
    await message.answer(f"✅ دستور «{html.escape(recipe_name)}» با شناسه {recipe_id} ثبت شد.", reply_markup=admin_keyboard())

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
    query = re.sub(r"^(با مواد|با|جستجو|جست‌وجو)\\s*", "", raw, flags=re.I).strip()
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
        try:
            me = await bot_instance.get_me()
            log.info("Telegram bot authenticated as @%s (id=%s)", me.username, me.id)
            asyncio.create_task(dp.start_polling(bot_instance, handle_signals=False))
            log.info("Telegram polling started")
        except Exception:
            log.exception("Telegram bot startup failed; check BOT_TOKEN and ensure no other polling instance is running")
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
