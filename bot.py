import os,asyncio,sqlite3,logging
from datetime import datetime,timedelta
from aiogram import Bot,Dispatcher,F
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,CallbackQuery,ChatPermissions
from aiogram.enums import ChatMemberStatus
from aiohttp import web
TOKEN=os.getenv("BOT_TOKEN"); ADM={int(x) for x in os.getenv("ADMIN_IDS","").replace(" ","").split(",") if x}
if not TOKEN: raise RuntimeError("BOT_TOKEN is required")
logging.basicConfig(level=logging.INFO); db=sqlite3.connect(os.getenv("DB_PATH","bot.db"),check_same_thread=False)
db.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT,name TEXT,joined TEXT);
CREATE TABLE IF NOT EXISTS filters(chat INTEGER,word TEXT,PRIMARY KEY(chat,word));
CREATE TABLE IF NOT EXISTS settings(chat INTEGER PRIMARY KEY,welcome INTEGER DEFAULT 1);\nCREATE TABLE IF NOT EXISTS warnings(chat INTEGER,user INTEGER,count INTEGER,PRIMARY KEY(chat,user));\nCREATE TABLE IF NOT EXISTS spam(chat INTEGER,user INTEGER,last TEXT,count INTEGER,PRIMARY KEY(chat,user))
CREATE TABLE IF NOT EXISTS warnings(chat INTEGER,user INTEGER,count INTEGER,PRIMARY KEY(chat,user))
CREATE TABLE IF NOT EXISTS spam(chat INTEGER,user INTEGER,last TEXT,count INTEGER,PRIMARY KEY(chat,user))"""); db.commit()
bot=Bot(TOKEN); dp=Dispatcher(); pending=set()
def save(m):
 u=m.from_user; db.execute("INSERT OR IGNORE INTO users VALUES(?,?,?,?)",(u.id,u.username,u.full_name,datetime.utcnow().isoformat())); db.execute("UPDATE users SET username=?,name=? WHERE id=?",(u.username,u.full_name,u.id)); db.commit()
def admin(uid): return uid in ADM
def menu(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 آمار",callback_data="stats"),InlineKeyboardButton(text="👥 کاربران",callback_data="users")],[InlineKeyboardButton(text="📢 همگانی",callback_data="bc"),InlineKeyboardButton(text="⚙️ امکانات",callback_data="features")]])
async def group_admin(m):
 if m.chat.type=="private": await m.answer("این دستور داخل گروه است."); return False
 if admin(m.from_user.id): return True
 try:
  x=await bot.get_chat_member(m.chat.id,m.from_user.id)
  if x.status in {ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.CREATOR}: return True
 except: pass
 await m.answer("⛔ فقط ادمین گروه."); return False
def target(m): return m.reply_to_message.from_user if m.reply_to_message else None
@dp.message(CommandStart())
async def start(m):
 save(m); await m.answer("🛠 ربات همه‌کاره آماده است." if admin(m.from_user.id) else "سلام 👋 ربات آماده است. /help",reply_markup=menu() if admin(m.from_user.id) else None)
@dp.message(Command("help"))
async def help(m):
 save(m); await m.answer("🤖 امکانات:\n/id شناسه\n\nگروه: /ban /unban /mute /unmute /del /pin /filter کلمه /unfilter کلمه /filters /welcome on|off\n\nادمین: /admin /broadcast")
@dp.message(Command("id"))
async def ident(m): await m.answer(f"🆔 User: {m.from_user.id}\n💬 Chat: {m.chat.id}")
@dp.message(Command("admin"))
async def admin_cmd(m):
 save(m)
 if not admin(m.from_user.id): return await m.answer("⛔ دسترسی ندارید.")
 await m.answer("🛠 پنل مدیریت",reply_markup=menu())
@dp.message(Command("ban"))
async def ban(m):
 if not await group_admin(m): return
 u=target(m)
 if not u:return await m.answer("کاربر را ریپلای کن.")
 try: await bot.ban_chat_member(m.chat.id,u.id); await m.answer(f"🚫 {u.full_name} مسدود شد.")
 except Exception as e: await m.answer(f"❌ {e}")
@dp.message(Command("unban"))
async def unban(m):
 if not await group_admin(m): return
 u=target(m)
 if not u:return await m.answer("کاربر را ریپلای کن.")
 try: await bot.unban_chat_member(m.chat.id,u.id,only_if_banned=True); await m.answer("✅ رفع مسدودی شد.")
 except Exception as e: await m.answer(f"❌ {e}")
@dp.message(Command("mute"))
async def mute(m):
 if not await group_admin(m): return
 u=target(m)
 if not u:return await m.answer("کاربر را ریپلای کن.")
 try: await bot.restrict_chat_member(m.chat.id,u.id,permissions=ChatPermissions(can_send_messages=False),until_date=datetime.utcnow()+timedelta(minutes=60)); await m.answer("🔇 کاربر ۶۰ دقیقه ساکت شد.")
 except Exception as e: await m.answer(f"❌ {e}")
@dp.message(Command("unmute"))
async def unmute(m):
 if not await group_admin(m): return
 u=target(m)
 if not u:return await m.answer("کاربر را ریپلای کن.")
 try: await bot.restrict_chat_member(m.chat.id,u.id,permissions=ChatPermissions(can_send_messages=True)); await m.answer("🔊 رفع سکوت شد.")
 except Exception as e: await m.answer(f"❌ {e}")
@dp.message(Command("del"))
async def delete(m):
 if not await group_admin(m): return
 if not m.reply_to_message:return await m.answer("پیام را ریپلای کن.")
 try: await m.reply_to_message.delete(); await m.delete()
 except: pass
@dp.message(Command("pin"))
async def pin(m):
 if not await group_admin(m): return
 if not m.reply_to_message:return await m.answer("پیام را ریپلای کن.")
 try: await m.reply_to_message.pin(); await m.answer("📌 سنجاق شد.")
 except Exception as e: await m.answer(f"❌ {e}")
@dp.message(Command("filter"))
async def add_filter(m):
 if not await group_admin(m): return
 p=m.text.split(maxsplit=1)
 if len(p)<2:return await m.answer("مثال: /filter کلمه")
 db.execute("INSERT OR IGNORE INTO filters VALUES(?,?)",(m.chat.id,p[1].lower().strip()));db.commit();await m.answer("✅ فیلتر اضافه شد.")
@dp.message(Command("unfilter"))
async def rem_filter(m):
 if not await group_admin(m): return
 p=m.text.split(maxsplit=1)
 if len(p)<2:return await m.answer("مثال: /unfilter کلمه")
 db.execute("DELETE FROM filters WHERE chat=? AND word=?",(m.chat.id,p[1].lower().strip()));db.commit();await m.answer("✅ حذف شد.")
@dp.message(Command("filters"))
async def filters(m):
 r=db.execute("SELECT word FROM filters WHERE chat=?",(m.chat.id,)).fetchall();await m.answer("🔎 فیلترها:\n"+("\n".join("• "+x[0] for x in r) or "خالی"))
@dp.message(Command("rules"))
async def rules(m):
 await m.answer("📜 قوانین:\n1) احترام\n2) بدون اسپم\n3) بدون تبلیغ و لینک غیرمجاز")

@dp.message(Command("warn"))
async def warn(m):
 if not await group_admin(m): return
 u=target(m)
 if not u: return await m.answer("کاربر را ریپلای کن.")
 await m.answer(f"⚠️ اخطار برای {u.full_name} ثبت شد.")

@dp.message(Command("promote"))
async def promote(m):
 if not await group_admin(m): return
 u=target(m)
 if not u: return await m.answer("کاربر را ریپلای کن.")
 try:
  await bot.promote_chat_member(m.chat.id,u.id,can_manage_chat=True,can_delete_messages=True,can_restrict_members=True,can_pin_messages=True)
  await m.answer("👑 کاربر ادمین شد.")
 except Exception as e: await m.answer(f"❌ {e}")

@dp.message(Command("demote"))
async def demote(m):
 if not await group_admin(m): return
 u=target(m)
 if not u: return await m.answer("کاربر را ریپلای کن.")
 try:
  await bot.promote_chat_member(m.chat.id,u.id,can_manage_chat=False,can_delete_messages=False,can_restrict_members=False,can_pin_messages=False)
  await m.answer("✅ دسترسی‌های مدیریتی حذف شد.")
 except Exception as e: await m.answer(f"❌ {e}")

@dp.message(Command("antilink"))
async def antilink(m):
 if not await group_admin(m): return
 p=m.text.split(maxsplit=1); v=p[1].lower() if len(p)>1 else ""
 if v not in ("on","off"): return await m.answer("/antilink on یا /antilink off")
 db.execute("INSERT OR IGNORE INTO settings(chat) VALUES(?)",(m.chat.id,))
 db.execute("UPDATE settings SET antilink=? WHERE chat=?",(1 if v=="on" else 0,m.chat.id)); db.commit()
 await m.answer("🔗 ضدلینک "+("فعال شد." if v=="on" else "خاموش شد."))

@dp.message(Command("antispam"))
async def antispam(m):
 if not await group_admin(m): return
 p=m.text.split(maxsplit=1); v=p[1].lower() if len(p)>1 else ""
 if v not in ("on","off"): return await m.answer("/antispam on یا /antispam off")
 db.execute("INSERT OR IGNORE INTO settings(chat) VALUES(?)",(m.chat.id,))
 db.execute("UPDATE settings SET antispam=? WHERE chat=?",(1 if v=="on" else 0,m.chat.id)); db.commit()
 await m.answer("🛡 ضداسپم "+("فعال شد." if v=="on" else "خاموش شد."))

@dp.message(Command("warn"))
async def warn(m):
 if not await group_admin(m): return
 u=target(m)
 if not u: return await m.answer("کاربر را ریپلای کن.")
 row=db.execute("SELECT count FROM warnings WHERE chat=? AND user=?",(m.chat.id,u.id)).fetchone()
 n=(row[0] if row else 0)+1
 db.execute("INSERT OR REPLACE INTO warnings VALUES(?,?,?)",(m.chat.id,u.id,n)); db.commit()
 if n>=3:
  try:
   await bot.restrict_chat_member(m.chat.id,u.id,permissions=ChatPermissions(can_send_messages=False),until_date=datetime.utcnow()+timedelta(hours=1))
  except: pass
  await m.answer(f"🔴 اخطار {n}/3 — {u.full_name} یک ساعت محدود شد.")
 else: await m.answer(f"⚠️ اخطار {n}/3 برای {u.full_name}")

@dp.message(Command("warnings"))
async def warnings(m):
 u=target(m) or m.from_user
 row=db.execute("SELECT count FROM warnings WHERE chat=? AND user=?",(m.chat.id,u.id)).fetchone()
 await m.answer(f"⚠️ اخطارهای {u.full_name}: {row[0] if row else 0}/3")

@dp.message(Command("clearwarn"))
async def clearwarn(m):
 if not await group_admin(m): return
 u=target(m)
 if not u: return await m.answer("کاربر را ریپلای کن.")
 db.execute("DELETE FROM warnings WHERE chat=? AND user=?",(m.chat.id,u.id)); db.commit()
 await m.answer("✅ اخطارهای کاربر پاک شد.")

@dp.message(Command("welcome"))
async def welcome(m):
 if not await group_admin(m):return
 p=m.text.split(maxsplit=1); v=p[1].lower() if len(p)>1 else ""
 if v not in ("on","off"):return await m.answer("/welcome on یا /welcome off")
 db.execute("INSERT OR IGNORE INTO settings(chat) VALUES(?)",(m.chat.id,));db.execute("UPDATE settings SET welcome=? WHERE chat=?",(v=="on",m.chat.id));db.commit();await m.answer("✅ تنظیم شد.")
@dp.message(F.new_chat_members)
async def new(m):
 r=db.execute("SELECT welcome FROM settings WHERE chat=?",(m.chat.id,)).fetchone()
 if r and not r[0]:return
 await m.answer("👋 خوش آمدید "+", ".join(x.full_name for x in m.new_chat_members)+"!")
@dp.callback_query(F.data.in_({"stats","users","features"}))
async def panel(c):
 if not admin(c.from_user.id):return await c.answer("⛔",show_alert=True)
 if c.data=="stats":t=f"📊 کاربران: {db.execute('SELECT COUNT(*) FROM users').fetchone()[0]}\n🔎 فیلترها: {db.execute('SELECT COUNT(*) FROM filters').fetchone()[0]}"
 elif c.data=="users":
  r=db.execute("SELECT id,name,username FROM users ORDER BY joined DESC LIMIT 20").fetchall();t="👥 کاربران:\n"+("\n".join(f"{i+1}. {n} @{u or '-'} | {uid}" for i,(uid,n,u) in enumerate(r)) or "خالی")
 else:t="⚙️ مدیریت گروه، فیلتر کلمات، خوشامد، آمار، کاربران و پیام همگانی فعال است."
 await c.message.edit_text(t,reply_markup=menu());await c.answer()
@dp.callback_query(F.data=="bc")
async def bc(c):
 if not admin(c.from_user.id):return await c.answer("⛔",show_alert=True)
 pending.add(c.from_user.id);await c.message.answer("📢 پیام همگانی را بفرست. /cancel");await c.answer()
@dp.message(Command("broadcast"))
async def broadcast(m):
 if not admin(m.from_user.id):return await m.answer("⛔")
 pending.add(m.from_user.id);await m.answer("📢 پیام را بفرست. /cancel")
@dp.message(Command("cancel"))
async def cancel(m):pending.discard(m.from_user.id);await m.answer("لغو شد.")
@dp.message()
async def allmsg(m):
 save(m)
 if admin(m.from_user.id) and m.from_user.id in pending:
  pending.discard(m.from_user.id);ok=bad=0
  for (uid,) in db.execute("SELECT id FROM users"):
   try:await bot.copy_message(uid,m.chat.id,m.message_id);ok+=1
   except:bad+=1
   await asyncio.sleep(.04)
  return await m.answer(f"📢 تمام شد\n✅ {ok}\n❌ {bad}")
 if m.chat.type!="private" and m.text:
  row=db.execute("SELECT welcome FROM settings WHERE chat=?",(m.chat.id,)).fetchone() or (0,)\n  antilink=0; antispam=0
  words=[x[0] for x in db.execute("SELECT word FROM filters WHERE chat=?",(m.chat.id,))]
  link=("http://" in m.text.lower() or "https://" in m.text.lower() or "t.me/" in m.text.lower())
  blocked=any(w in m.text.lower() for w in words) or (antilink and link)
  if antispam:
   now=datetime.utcnow()
   s=db.execute("SELECT last,count FROM spam WHERE chat=? AND user=?",(m.chat.id,m.from_user.id)).fetchone()
   if s:
    try: recent=(now-datetime.fromisoformat(s[0])).total_seconds()<8
    except: recent=False
    count=s[1]+1 if recent else 1
   else: count=1
   db.execute("INSERT OR REPLACE INTO spam VALUES(?,?,?,?)",(m.chat.id,m.from_user.id,now.isoformat(),count)); db.commit()
   if count>=5: blocked=True
  if blocked:
   try: await m.delete()
   except: pass
   return
async def health(_):return web.Response(text="OK")
async def main():
 app=web.Application();app.router.add_get("/",health);app.router.add_get("/health",health);r=web.AppRunner(app);await r.setup();await web.TCPSite(r,"0.0.0.0",int(os.getenv("PORT","8080"))).start();await dp.start_polling(bot)
if __name__=="__main__":asyncio.run(main())