#!/usr/bin/env python3
"""Telegram Inventory Bot - Multi-Channel Sync"""

import os
import sqlite3
import random
import time
import threading
import asyncio
import urllib.request
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "6422629080:AAESCucEB-w_64J4smXaKYHXs6kV-Lx1tVA")
ADMIN = [1380999385]
CHANNEL = "-1001192930889"
CHANNEL_ID = "1192930889"
PRICE_LIST_MSG_ID = 3
DM_LINK = "https://t.me/WT710"
PRICE_LIST_LINK = "https://t.me/c/1192930889/3"
PRODUCT_LIST_LINK = "https://t.me/c/1192930889/3"
TOS_LINK = "https://t.me/+GEimB8xUClY4MjIx"
REFER_LINK = "https://t.me/c/1192930889/610"
QUOTE_API_KEY = "cYcRDmqvz3mMilttRd2Y80apwB6L0xUWkNCk2Bbl"

CATEGORIES = [("Flower", "flower"), ("Concentrate", "concentrate"), ("Dispos", "dispos"), ("Edibles", "edibles"), ("Psychedelic", "psychedelic")]

scheduler_running = False

# --- Winning Team website integration ---------------------------------
from password_manager import rotate_if_needed
try:
    from webapp import app as flask_app
except Exception as _e:
    flask_app = None
    print(f"[webapp] import failed: {_e}")

def _run_flask():
    if flask_app is None:
        return
    import os
    port = int(os.getenv("PORT", "8080"))
    print(f"[webapp] starting on 0.0.0.0:{port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
# ----------------------------------------------------------------------

LAST_QUOTE_MSG_FILE = "last_quote_msg.txt"

def get_last_quote_msg_id():
    try:
        with open(LAST_QUOTE_MSG_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return None

def set_last_quote_msg_id(msg_id):
    with open(LAST_QUOTE_MSG_FILE, "w") as f:
        f.write(str(msg_id))

LAST_MORNING_FILE = "last_quote_morning.txt"
LAST_AFTERNOON_FILE = "last_quote_afternoon.txt"
LAST_EVENING_FILE = "last_quote_evening.txt"

# Track last product post refresh (to keep posts deletable)
LAST_REFRESH_FILE = "last_refresh.txt"

def get_last_refresh_time():
    try:
        with open(LAST_REFRESH_FILE, "r") as f:
            return float(f.read().strip())
    except:
        return 0

def set_last_refresh_time(timestamp):
    with open(LAST_REFRESH_FILE, "w") as f:
        f.write(str(timestamp))

def get_last_post_for_file(filepath):
    try:
        with open(filepath, "r") as f:
            return int(f.read().strip())
    except:
        return None

def set_last_post_for_file(filepath, day):
    with open(filepath, "w") as f:
        f.write(str(day))

async def refresh_all_product_posts(bot):
    """Delete and repost all product posts to keep them within 48-hour deletable window"""
    print("[REFRESH] Starting product post refresh...")
    for p in db.get_all():
        post_text = f"✦ <b>{p[1]}</b>\n"
        if p[2]: post_text += f"<blockquote>{p[2]}</blockquote>\n"
        
        # Main channel
        if p[7]:
            try:
                await bot.delete_message(chat_id=int(CHANNEL), message_id=int(p[7]))
            except Exception as e:
                print(f"[REFRESH] Failed to delete main channel post for {p[1]}: {e}")
        
        try:
            msg = await send_product_to_channel(bot, CHANNEL, p, post_text, kb_channel_product())
            db.update(p[0], msg_id=msg.message_id)
            print(f"[REFRESH] Reposted {p[1]} to main channel (new msg_id: {msg.message_id})")
        except Exception as e:
            print(f"[REFRESH] Failed to repost {p[1]} to main channel: {e}")
        
        # Connected channels
        for cm in db.get_channel_msgs(p[0]):
            channel_id = cm[0]
            if cm[1]:
                try:
                    await bot.delete_message(chat_id=int(channel_id), message_id=int(cm[1]))
                except Exception as e:
                    print(f"[REFRESH] Failed to delete channel {channel_id} post for {p[1]}: {e}")
            
            try:
                msg = await send_product_to_channel(bot, channel_id, p, post_text, kb_other_channel(channel_id))
                db.set_channel_msg(p[0], channel_id, msg.message_id, "product")
                print(f"[REFRESH] Reposted {p[1]} to channel {channel_id} (new msg_id: {msg.message_id})")
            except Exception as e:
                print(f"[REFRESH] Failed to repost {p[1]} to channel {channel_id}: {e}")
            
            # Update product list in this channel
            await update_channel_list(bot, channel_id)
    
    # Update price list (links will be updated automatically since we updated msg_ids)
    await update_price_list_all(bot)
    set_last_refresh_time(time.time())
    print("[REFRESH] Product post refresh complete!")

class DB:
    def __init__(self):
        self.conn = sqlite3.connect("inventory.db", check_same_thread=False)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, description TEXT, cat TEXT, price TEXT, media_type TEXT, media_id TEXT, msg_id INTEGER, low_stock_msg_id INTEGER)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, channel_title TEXT, list_msg_id INTEGER DEFAULT 0)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS channel_msgs (product_id INTEGER, channel_id TEXT, msg_id INTEGER, low_stock_msg_id INTEGER, PRIMARY KEY (product_id, channel_id))""")
        try:
            self.conn.execute("ALTER TABLE channels ADD COLUMN list_msg_id INTEGER DEFAULT 0")
        except:
            pass
        try:
            self.conn.execute("ALTER TABLE channels ADD COLUMN dm_link TEXT DEFAULT ''")
        except:
            pass
        self.conn.commit()

    def add(self, name, description, cat, price, media_type=None, media_id=None, msg_id=None, low_stock_msg_id=None):
        self.conn.execute("""INSERT INTO products (name, description, cat, price, media_type, media_id, msg_id, low_stock_msg_id) VALUES (?,?,?,?,?,?,?,?)""", (name, description, cat, price, media_type, media_id, msg_id, low_stock_msg_id))
        self.conn.commit()
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update(self, pid, **kwargs):
        valid_columns = ["name", "description", "cat", "price", "media_type", "media_id", "msg_id", "low_stock_msg_id"]
        for k, v in kwargs.items():
            if k not in valid_columns:
                continue
            self.conn.execute(f"UPDATE products SET {k}=? WHERE id=?", (v, pid))
        self.conn.commit()

    def get_all(self):
        return self.conn.execute("SELECT * FROM products ORDER BY cat, name").fetchall()

    def get(self, pid):
        return self.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()

    def delete(self, pid):
        self.conn.execute("DELETE FROM products WHERE id=?", (pid,))
        self.conn.execute("DELETE FROM channel_msgs WHERE product_id=?", (pid,))
        self.conn.commit()

    def add_channel(self, channel_id, channel_title=""):
        self.conn.execute("INSERT OR IGNORE INTO channels (channel_id, channel_title) VALUES (?,?)", (channel_id, channel_title))
        self.conn.commit()

    def remove_channel(self, channel_id):
        self.conn.execute("DELETE FROM channels WHERE channel_id=?", (channel_id,))
        self.conn.execute("DELETE FROM channel_msgs WHERE channel_id=?", (channel_id,))
        self.conn.commit()

    def get_channels(self):
        return self.conn.execute("SELECT channel_id, channel_title FROM channels").fetchall()

    def set_channel_msg(self, product_id, channel_id, msg_id, msg_type="product"):
        existing = self.conn.execute("SELECT * FROM channel_msgs WHERE product_id=? AND channel_id=?", (product_id, channel_id)).fetchone()
        if existing:
            if msg_type == "product":
                self.conn.execute("UPDATE channel_msgs SET msg_id=? WHERE product_id=? AND channel_id=?", (msg_id, product_id, channel_id))
            else:
                self.conn.execute("UPDATE channel_msgs SET low_stock_msg_id=? WHERE product_id=? AND channel_id=?", (msg_id, product_id, channel_id))
        else:
            if msg_type == "product":
                self.conn.execute("INSERT INTO channel_msgs (product_id, channel_id, msg_id) VALUES (?,?,?)", (product_id, channel_id, msg_id))
            else:
                self.conn.execute("INSERT INTO channel_msgs (product_id, channel_id, low_stock_msg_id) VALUES (?,?,?)", (product_id, channel_id, msg_id))
        self.conn.commit()

    def get_channel_msgs(self, product_id):
        return self.conn.execute("SELECT channel_id, msg_id, low_stock_msg_id FROM channel_msgs WHERE product_id=?", (product_id,)).fetchall()

    def set_channel_list_msg_id(self, channel_id, msg_id):
        self.conn.execute("UPDATE channels SET list_msg_id=? WHERE channel_id=?", (msg_id, channel_id))
        self.conn.commit()

    def get_channel_list_msg_id(self, channel_id):
        row = self.conn.execute("SELECT list_msg_id FROM channels WHERE channel_id=?", (channel_id,)).fetchone()
        return row[0] if row else 0

    def set_channel_dm_link(self, channel_id, dm_link):
        self.conn.execute("UPDATE channels SET dm_link=? WHERE channel_id=?", (dm_link, channel_id))
        self.conn.commit()

    def get_channel_dm_link(self, channel_id):
        row = self.conn.execute("SELECT dm_link FROM channels WHERE channel_id=?", (channel_id,)).fetchone()
        return row[0] if row and row[0] else None

    def get_channel_product_msg_id(self, product_id, channel_id):
        row = self.conn.execute("SELECT msg_id FROM channel_msgs WHERE product_id=? AND channel_id=?", (product_id, channel_id)).fetchone()
        return row[0] if row else None

db = DB()

def product_count():
    ps = db.get_all()
    if not ps: return "0 products"
    by = {}
    for p in ps: by.setdefault(p[3], []).append(p)
    parts = [f"{len(items)} {cat}" for cat, items in by.items()]
    return ", ".join(parts)

def kb_main():
    count = product_count()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Product", callback_data="p_add")],
        [InlineKeyboardButton("Edit Prices", callback_data="p_edit")],
        [InlineKeyboardButton("Delete Product", callback_data="p_delete")],
        [InlineKeyboardButton("Low Stock Alert", callback_data="p_low")],
        [InlineKeyboardButton("Price List", callback_data="m_price")],
        [InlineKeyboardButton("Connected Channels", callback_data="m_channels")]
    ])

def kb_products():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Product", callback_data="p_add")],
        [InlineKeyboardButton("Edit Prices", callback_data="p_edit")],
        [InlineKeyboardButton("Delete Product", callback_data="p_delete")],
        [InlineKeyboardButton("Low Stock Alert", callback_data="p_low")],
        [InlineKeyboardButton("Back to Menu", callback_data="m_main")]
    ])

def kb_cat():
    return InlineKeyboardMarkup([[InlineKeyboardButton(n, callback_data=f"c_{k}")] for n, k in CATEGORIES] + [[InlineKeyboardButton("Back", callback_data="m_main")]])

def kb_skip():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Skip Media", callback_data="skip_media")]])

def kb_back_main():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_main")]])

def kb_back_products():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_main")]])

def kb_price_edit_list():
    ps = db.get_all()
    if not ps:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_main")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{p[1]}  |  {p[4]}", callback_data=f"pe_{p[0]}")] for p in ps] + [[InlineKeyboardButton("Back", callback_data="m_main")]])

def kb_edit_action(pid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("Edit Price", callback_data=f"ep_{pid}")], [InlineKeyboardButton("Back to List", callback_data="p_edit")]])

def kb_del_list():
    ps = db.get_all()
    if not ps:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_main")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"Delete {p[1]}", callback_data=f"pd_{p[0]}")] for p in ps] + [[InlineKeyboardButton("Back", callback_data="m_main")]])

def kb_low_stock_list():
    ps = db.get_all()
    if not ps:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="m_main")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{p[1]}", callback_data=f"pl_{p[0]}")] for p in ps] + [[InlineKeyboardButton("Back", callback_data="m_main")]])

def kb_channel_product():
    return InlineKeyboardMarkup([[InlineKeyboardButton("PRESS HERE TO DM ORDER", url=DM_LINK)], [InlineKeyboardButton("FULL PRICE LIST", url=PRICE_LIST_LINK)]])

def kb_other_channel(channel_id):
    dm_link = db.get_channel_dm_link(channel_id) or DM_LINK
    list_msg_id = db.get_channel_list_msg_id(channel_id)
    if list_msg_id:
        link = f"https://t.me/c/{str(channel_id).replace('-100', '')}/{list_msg_id}"
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("PRESS HERE TO DM ORDER", url=dm_link)],
            [InlineKeyboardButton("FULL PRODUCT LIST", url=link)]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PRESS HERE TO DM ORDER", url=dm_link)],
        [InlineKeyboardButton("FULL PRODUCT LIST", url=PRODUCT_LIST_LINK)]
    ])

def kb_channel_products():
    return InlineKeyboardMarkup([[InlineKeyboardButton("PRESS HERE TO DM ORDER", url=DM_LINK)], [InlineKeyboardButton("FULL PRODUCT LIST", url=PRODUCT_LIST_LINK)]])

def kb_channel_prices():
    return InlineKeyboardMarkup([[InlineKeyboardButton("PRESS HERE TO DM ORDER", url=DM_LINK)], [InlineKeyboardButton("TOS AND FAQ", url=TOS_LINK)], [InlineKeyboardButton("SHARE OUR WEBSITE", url=REFER_LINK)]])

def cat_emoji(cat):
    icons = {"flower": "Flower", "dispos": "Dispos", "edibles": "Edibles", "concentrate": "Concentrate", "psychedelic": "Psychedelic"}
    return icons.get(cat, cat.upper())

def format_all():
    ps = db.get_all()
    if not ps: return "No products yet."
    by = {}
    for p in ps: by.setdefault(p[3], []).append(p)
    text = ""
    for cat, items in by.items():
        text += f"{cat_emoji(cat)}:\n"
        for p in items: text += f"  {p[1]} - {p[4]}\n"
        text += "\n"
    return text.strip()

def format_price():
    ps = db.get_all()
    if not ps: return "No products yet."
    by = {}
    for p in ps: by.setdefault(p[3], []).append(p)
    text = "Price List\n\n"
    for cat, items in by.items():
        text += f"{cat_emoji(cat)}:\n"
        for p in items: text += f"  {p[1]} - {p[4]}\n"
        text += "\n"
    return text.strip()

def format_price_post():
    ps = db.get_all()
    msg = "WELCOME TO OUR MENU!\n\n<blockquote>\n➡️ Everything on the menu is available!\n➡️ Menu changes frequently!\n➡️ Please like our product posts and participate in our polls so we can make sure everything is to your satisfaction.\n</blockquote>\n\n✅CURRENT INVENTORY✅\n\n<blockquote>\n"
    if not ps:
        msg += "- MORE COMING SOON!\n"
    else:
        by = {}
        for p in ps: by.setdefault(p[3], []).append(p)
        for cat in ["flower", "dispos", "edibles", "concentrate", "psychedelic"]:
            if cat in by:
                if cat == "flower": msg += "Flower: (dm for QP and up)\n"
                elif cat == "dispos": msg += "Carts & Disposables:\n"
                elif cat == "edibles": msg += "Edibles:\n"
                elif cat == "concentrate": msg += "Concentrate:\n"
                elif cat == "psychedelic": msg += "Psychedelic:\n"
                for p in by[cat]:
                    if p[7]:
                        link = f"https://t.me/c/{CHANNEL_ID}/{p[7]}"
                        msg += f'- <a href="{link}"><b>{p[1]}</b></a>\n  {p[4]}\n'
                    else:
                        msg += f"- <b>{p[1]}</b>\n  {p[4]}\n"
                msg += "\n"
    msg += "</blockquote>\n\nThank you for your support!\n"
    return msg

def format_product_list():
    ps = db.get_all()
    if not ps:
        return "No products yet."
    by = {}
    for p in ps: by.setdefault(p[3], []).append(p)
    text = "PRODUCT LIST\n\n"
    for cat, items in by.items():
        text += f"{cat_emoji(cat)}:\n"
        for p in items: text += f"  {p[1]} - {p[4]}\n"
        text += "\n"
    return text.strip()

def format_channel_product_list(channel_id):
    ps = db.get_all()
    msg = "PRODUCT LIST\n\n"
    if not ps:
        msg += "- MORE COMING SOON!\n"
    else:
        by = {}
        for p in ps: by.setdefault(p[3], []).append(p)
        for cat in ["flower", "dispos", "edibles", "concentrate", "psychedelic"]:
            if cat in by:
                if cat == "flower": msg += "🌸 Flower: (dm for QP and up)\n"
                elif cat == "dispos": msg += "💨 Carts & Disposables:\n"
                elif cat == "edibles": msg += "🍪 Edibles:\n"
                elif cat == "concentrate": msg += "🧪 Concentrate:\n"
                elif cat == "psychedelic": msg += "🌀 Psychedelic:\n"
                for p in by[cat]:
                    ch_msg_id = db.get_channel_product_msg_id(p[0], channel_id)
                    if ch_msg_id:
                        clean = str(channel_id).replace('-100', '') if str(channel_id).startswith('-100') else str(channel_id)
                        link = f"https://t.me/c/{clean}/{ch_msg_id}"
                        msg += f'  - <a href="{link}"><b>{p[1]}</b></a>\n'
                    else:
                        msg += f"  - <b>{p[1]}</b>\n"
                msg += "\n"
    return msg.strip()

def format_product_post(p):
    post_text = f"- <b>{p[1]}</b>\n"
    if p[2]: post_text += f"<blockquote>{p[2]}</blockquote>\n"
    return post_text

def get_quote():
    url = "https://api.api-ninjas.com/v1/quotes?category=inspirational"
    headers = {"X-Api-Key": QUOTE_API_KEY}
    try:
        req = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req, timeout=10)
        data = json.loads(response.read().decode())
        if data and len(data) > 0:
            quote = data[0].get('quote', '')
            if len(quote) > 80:
                quote = quote[:77] + "..."
            return quote
    except: pass

    short_quotes = [
        "Stay positive, work hard, make it happen.",
        "Every day is a new opportunity to grow.",
        "Small steps lead to big changes.",
        "You are stronger than you think.",
        "Focus on the good, ignore the rest.",
        "One day at a time, one step at a time.",
        "Keep going, never give up on yourself.",
        "Believe in yourself and your journey.",
        "Today is a fresh start, make it count.",
        "Progress not perfection, keep moving.",
        "Your potential is limitless, dream big.",
        "Stay humble, stay hungry, stay focused.",
        "Good vibes only, guard your energy.",
        "You got this, keep pushing forward.",
        "Focus on progress, not perfection.",
    ]
    return random.choice(short_quotes)

def get_greeting():
    hour = datetime.now().hour
    ct_hour = (hour - 6) % 24
    if ct_hour < 12: return "Good morning!"
    elif ct_hour < 18: return "Good afternoon!"
    else: return "Good evening!"

async def post_motivation_quote(bot):
    try:
        old_msg_id = get_last_quote_msg_id()
        if old_msg_id:
            try:
                await bot.delete_message(CHANNEL, old_msg_id)
            except:
                pass

        quote = get_quote()
        greeting = get_greeting()
        msg_text = f"{greeting} We hope your day is great! All inventory is currently available!\n\nMotivational Quote:\n<blockquote>{quote}</blockquote>"
        msg = await bot.send_message(CHANNEL, msg_text, parse_mode='HTML', reply_markup=kb_channel_product())

        set_last_quote_msg_id(msg.message_id)
        print(f"Posted motivation quote: {msg.message_id}")
    except Exception as e:
        print(f"Post quote error: {e}")

async def update_channel_list(bot, channel_id):
    try:
        list_msg_id = db.get_channel_list_msg_id(channel_id)
        if list_msg_id:
            try:
                await bot.edit_message_text(chat_id=channel_id, message_id=list_msg_id, text=format_channel_product_list(channel_id), parse_mode='HTML')
                return
            except Exception as e:
                print(f"Edit list failed in {channel_id} (msg_id={list_msg_id}): {e}")
        msg = await bot.send_message(channel_id, format_channel_product_list(channel_id), parse_mode='HTML')
        db.set_channel_list_msg_id(channel_id, msg.message_id)
    except Exception as e:
        print(f"Update list in {channel_id} error: {e}")

async def update_product_lists_all(bot):
    for ch in db.get_channels():
        await update_channel_list(bot, ch[0])

async def update_price_list_all(bot):
    try:
        await bot.edit_message_text(
            chat_id=CHANNEL,
            message_id=PRICE_LIST_MSG_ID,
            text=format_price_post(),
            parse_mode='HTML',
            reply_markup=kb_channel_prices()
        )
    except Exception as e:
        print(f"Update price list in main channel error: {e}")
    for ch in db.get_channels():
        await update_channel_list(bot, ch[0])

async def send_product_to_channel(bot, channel_id, p, post_text, reply_markup):
    if p[5] == 'photo':
        return await bot.send_photo(channel_id, p[6], caption=post_text, parse_mode='HTML', reply_markup=reply_markup)
    elif p[5] == 'video':
        return await bot.send_video(channel_id, p[6], caption=post_text, parse_mode='HTML', reply_markup=reply_markup)
    elif p[5] == 'gif':
        return await bot.send_animation(channel_id, p[6], caption=post_text, parse_mode='HTML', reply_markup=reply_markup)
    else:
        return await bot.send_message(channel_id, post_text, parse_mode='HTML', reply_markup=reply_markup)

async def post_product_all_channels(bot, p, post_text):
    try:
        msg = await send_product_to_channel(bot, CHANNEL, p, post_text, kb_channel_product())
        db.update(p[0], msg_id=msg.message_id)
    except Exception as e:
        print(f"Post to main channel error: {e}")
    for ch in db.get_channels():
        try:
            msg = await send_product_to_channel(bot, ch[0], p, post_text, kb_other_channel(ch[0]))
            db.set_channel_msg(p[0], ch[0], msg.message_id, "product")
            await update_channel_list(bot, ch[0])
        except Exception as e:
            print(f"Post to channel {ch[0]} error: {e}")

async def delete_product_all_channels(bot, p):
    errors = []
    print(f"[DEBUG] Deleting product {p[0]} ({p[1]})")
    print(f"[DEBUG] Main channel msg_id: {p[7]}, low_stock_msg_id: {p[8]}")
    ch_msgs = db.get_channel_msgs(p[0])
    print(f"[DEBUG] Channel msgs: {ch_msgs}")
    
    async def _del(chat_id, msg_id, label):
        if not msg_id:
            errors.append(f"{label}: no message ID stored in database")
            return
        print(f"[DEBUG] Deleting {label}: chat_id={chat_id}, msg_id={msg_id}")
        try:
            await bot.delete_message(chat_id=int(chat_id), message_id=int(msg_id))
            print(f"[DEBUG] Successfully deleted {label}")
        except Exception as e:
            errors.append(f"{label} (chat_id={chat_id}, msg_id={msg_id}): {type(e).__name__}: {e}")
            print(f"[DEBUG] Failed to delete {label}: {type(e).__name__}: {e}")

    await _del(CHANNEL, p[7], "main channel product post")
    await _del(CHANNEL, p[8], "main channel low stock alert")
    ch_ids = set()
    for cm in ch_msgs:
        ch_ids.add(cm[0])
        await _del(cm[0], cm[1], f"channel {cm[0]} product post")
        await _del(cm[0], cm[2], f"channel {cm[0]} low stock alert")
    for ch_id in ch_ids:
        await update_channel_list(bot, ch_id)
    return errors

async def low_stock_all_channels(bot, p):
    link = f"https://t.me/c/{CHANNEL_ID}/{p[7]}"
    text = f"⚠️ LOW STOCK ALERT ⚠️\n\n<blockquote>Running low on <a href=\"{link}\"><b>{p[1]}</b></a>. Act fast!</blockquote>"
    try:
        msg = await bot.send_message(CHANNEL, text, parse_mode='HTML', reply_to_message_id=p[7], reply_markup=kb_channel_product())
        db.update(p[0], low_stock_msg_id=msg.message_id)
    except Exception as e:
        print(f"Low stock main channel error: {e}")
    for cm in db.get_channel_msgs(p[0]):
        try:
            msg = await bot.send_message(cm[0], text, parse_mode='HTML', reply_to_message_id=cm[1], reply_markup=kb_other_channel(cm[0]))
            db.set_channel_msg(p[0], cm[0], msg.message_id, "low_stock")
        except Exception as e:
            print(f"Low stock channel {cm[0]} error: {e}")

def run_scheduler(app, main_loop):
    global scheduler_running
    while scheduler_running:
        try:
            now = datetime.now()
            current_day = now.day
            bot = app.bot
            try:
                future = asyncio.run_coroutine_threadsafe(rotate_if_needed(bot), main_loop)
                future.result(timeout=30)
            except Exception as e:
                print(f"[password] rotate error: {e}")
            
            # Refresh product posts every 47 hours to keep them deletable
            last_refresh = get_last_refresh_time()
            if time.time() - last_refresh > 47 * 3600:  # 47 hours
                try:
                    future = asyncio.run_coroutine_threadsafe(refresh_all_product_posts(bot), main_loop)
                    future.result(timeout=120)
                    print("Product posts refreshed!")
                except Exception as e:
                    print(f"Product post refresh error: {e}")
            
            if 15 <= now.hour < 18:
                last_morning = get_last_post_for_file(LAST_MORNING_FILE)
                if current_day != last_morning and random.random() < 0.05:
                    set_last_post_for_file(LAST_MORNING_FILE, current_day)
                    try:
                        future = asyncio.run_coroutine_threadsafe(post_motivation_quote(bot), main_loop)
                        future.result(timeout=30)
                        print("Morning quote posted!")
                    except Exception as e:
                        print(f"Morning quote error: {e}")
            elif 18 <= now.hour < 23:
                last_afternoon = get_last_post_for_file(LAST_AFTERNOON_FILE)
                if current_day != last_afternoon and random.random() < 0.05:
                    set_last_post_for_file(LAST_AFTERNOON_FILE, current_day)
                    try:
                        future = asyncio.run_coroutine_threadsafe(post_motivation_quote(bot), main_loop)
                        future.result(timeout=30)
                        print("Afternoon quote posted!")
                    except Exception as e:
                        print(f"Afternoon quote error: {e}")
            elif now.hour < 3:
                last_evening = get_last_post_for_file(LAST_EVENING_FILE)
                if current_day != last_evening and random.random() < 0.05:
                    set_last_post_for_file(LAST_EVENING_FILE, current_day)
                    try:
                        future = asyncio.run_coroutine_threadsafe(post_motivation_quote(bot), main_loop)
                        future.result(timeout=30)
                        print("Evening quote posted!")
                    except Exception as e:
                        print(f"Evening quote error: {e}")
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(60)

async def start_cmd(update, context):
    if update.effective_user.id not in ADMIN:
        await update.message.reply_text("No access")
        return
    ps = db.get_all()
    ch_count = len(db.get_channels())
    menu_text = (
        "Inventory Bot\n\n"
        f"Products: {len(ps)}  |  Channels: {ch_count}\n"
        f"{product_count()}\n\n"
        "Choose an option:"
    )
    await update.message.reply_text(menu_text, reply_markup=kb_main())

async def set_dm_link(update, context):
    if update.effective_user.id not in ADMIN:
        await update.message.reply_text("No access")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Set the DM link for a connected channel.\n\n"
            "Usage: /setdm <channel_id> <dm_link>\n\n"
            "Example: /setdm -1001234567890 https://t.me/channelowner"
        )
        return
    channel_id = context.args[0]
    dm_link = context.args[1]
    channels = db.get_channels()
    if not any(c[0] == channel_id for c in channels):
        await update.message.reply_text(f"Channel {channel_id} is not connected.\nUse /manage first.")
        return
    db.set_channel_dm_link(channel_id, dm_link)
    bot = context.bot
    # Update all existing product posts in this channel with the new DM keyboard
    for cm in db.conn.execute("SELECT DISTINCT product_id FROM channel_msgs WHERE channel_id=?", (channel_id,)).fetchall():
        p = db.get(cm[0])
        if p:
            ch_msg_id = db.get_channel_product_msg_id(p[0], channel_id)
            if ch_msg_id:
                try:
                    await bot.edit_message_reply_markup(chat_id=channel_id, message_id=ch_msg_id, reply_markup=kb_other_channel(channel_id))
                except Exception as e:
                    print(f"Error updating DM link for product {p[1]} in {channel_id}: {e}")
    await update_channel_list(bot, channel_id)
    await update.message.reply_text(f"DM link set for {channel_id}: {dm_link}\nExisting product posts updated.", reply_markup=kb_main())

async def channels_cmd(update, context):
    if update.effective_user.id not in ADMIN:
        await update.message.reply_text("No access")
        return
    channels = db.get_channels()
    if not channels:
        await update.message.reply_text(
            "No connected channels.\n\n"
            "Use /manage <channel_id> to connect one.\n"
            "The bot must be an admin in the target channel."
        )
        return
    text = "Connected Channels:\n\n"
    for c in channels:
        dm = db.get_channel_dm_link(c[0])
        dm_text = f", DM: {dm}" if dm else ""
        text += f"  {c[1]} ({c[0]}{dm_text})\n"
    text += "\nUse the menu to disconnect channels."
    await update.message.reply_text(text, reply_markup=kb_main())

async def manage_other_channel(update, context):
    if update.effective_user.id not in ADMIN:
        await update.message.reply_text("No access")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Connect a channel so all product changes sync there too.\n\n"
            "Usage: /manage <channel_id> <dm_link>\n\n"
            "Example: /manage -1001234567890 https://t.me/channelowner\n\n"
            "The DM link is the Telegram link the order button will open for this channel (e.g. https://t.me/ChannelOwnerDm)."
        )
        return
    try:
        channel_id = context.args[0]
        dm_link = context.args[1]
        if channel_id.startswith('@'):
            channel_id = channel_id[1:]
        bot = context.bot
        chat = await bot.get_chat(channel_id)
        db.add_channel(channel_id, chat.title)
        db.set_channel_dm_link(channel_id, dm_link)
        await update.message.reply_text(
            f"Connected: {chat.title}\n\n"
            f"New products, edits, deletions, and low stock alerts will now sync to this channel automatically.\n\n"
            f"Use /channels to see all connected channels.",
            reply_markup=kb_main()
        )
        # Send product list first so list_msg_id exists for the "FULL PRODUCT LIST" button
        await update_channel_list(context.bot, channel_id)
        # Copy existing products to the new channel
        for p in db.get_all():
            try:
                post_text = format_product_post(p)
                msg = await send_product_to_channel(context.bot, channel_id, p, post_text, kb_other_channel(channel_id))
                db.set_channel_msg(p[0], channel_id, msg.message_id, "product")
            except Exception as e:
                print(f"Error copying product {p[1]} to new channel {channel_id}: {e}")
        # Update the product list with links to the channel's own posts
        await update_channel_list(context.bot, channel_id)
        context.user_data['manage_channel_id'] = channel_id
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cb_unmanage(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_unmanage: {q.data}")
    await q.answer()
    channel_id = q.data.replace("uc_", "")
    channel = db.get_channels()
    title = channel_id
    for c in channel:
        if c[0] == channel_id:
            title = c[1]
            break
    db.remove_channel(channel_id)
    await q.edit_message_text(f"Disconnected {title} ({channel_id}).", reply_markup=kb_main())

async def cb_cancel_add(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_cancel_add: {q.data}")
    await q.answer()
    context.user_data.clear()
    await q.edit_message_text("Cancelled", reply_markup=kb_main())

async def cb_category(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_category: {q.data}")
    await q.answer()
    context.user_data['cat'] = q.data.replace("c_", "")
    context.user_data['step'] = "name"
    await q.edit_message_text("Product Name:")

async def cb_skip_media(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_skip_media: {q.data}")
    await q.answer()
    context.user_data['media_type'] = None
    context.user_data['media_id'] = None
    context.user_data['step'] = "price"
    await q.edit_message_text("Price:")

async def cb_main(update, context):
    q = update.callback_query
    print(f"[DEBUG] Callback: {q.data} from user {q.from_user.id}")
    await q.answer()
    d = q.data
    if d == "m_main":
        ps = db.get_all()
        ch_count = len(db.get_channels())
        menu_text = (
            "Inventory Bot\n\n"
            f"Products: {len(ps)}  |  Channels: {ch_count}\n"
            f"{product_count()}\n\n"
            "Choose an option:"
        )
        await q.edit_message_text(menu_text, reply_markup=kb_main())
    elif d == "m_products": await q.edit_message_text("Menu:", reply_markup=kb_main())
    elif d == "m_all": await q.edit_message_text(format_all(), reply_markup=kb_back_main())
    elif d == "m_price": await q.edit_message_text(format_price(), reply_markup=kb_back_main())
    elif d == "p_add": await q.edit_message_text("Choose a category:", reply_markup=kb_cat())
    elif d == "p_edit": await q.edit_message_text("Select product to edit:", reply_markup=kb_price_edit_list())
    elif d == "p_delete": await q.edit_message_text("Select product to delete:", reply_markup=kb_del_list())
    elif d == "p_low": await q.edit_message_text("Select product for Low Stock Alert:", reply_markup=kb_low_stock_list())
    elif d == "m_channels":
        channels = db.get_channels()
        if not channels:
            await q.edit_message_text("No connected channels.\n\nUse /manage <channel_id> to connect one.", reply_markup=kb_back_main())
            return
        text = "Connected Channels:\n\n"
        buttons = []
        for c in channels:
            text += f" {c[1]} ({c[0]})\n"
            buttons.append([InlineKeyboardButton(f"Disconnect {c[1]}", callback_data=f"uc_{c[0]}")])
        buttons.append([InlineKeyboardButton("Back", callback_data="m_main")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def cb_edit_select(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_edit_select: {q.data}")
    await q.answer()
    p = db.get(int(q.data.replace("pe_", "")))
    if p: await q.edit_message_text(f"Edit: {p[1]}\nPrice: {p[4]}", reply_markup=kb_edit_action(p[0]))

async def cb_edit_price(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_edit_price: {q.data}")
    await q.answer()
    context.user_data['edit_pid'] = int(q.data.replace("ep_", ""))
    context.user_data['step'] = 'edit_price'
    await q.edit_message_text("New price:")

async def cb_del(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_del: {q.data}")
    await q.answer()
    bot = context.bot
    pid = int(q.data.replace("pd_", ""))
    p = db.get(pid)
    errors = []
    if p:
        errors = await delete_product_all_channels(bot, p)
        db.delete(pid)
    await update_price_list_all(bot)
    await update_product_lists_all(bot)
    msg = "Product removed from database and price list."
    if errors:
        msg += "\n\nCould not fully delete some messages:\n" + "\n".join(errors)
        msg += "\n\nTry promoting the bot to admin with 'Delete messages' permission, then delete again."
    await q.edit_message_text(msg, reply_markup=kb_main())

async def cb_low_stock(update, context):
    q = update.callback_query
    print(f"[DEBUG] cb_low_stock: {q.data}")
    await q.answer()
    bot = context.bot
    pid = int(q.data.replace("pl_", ""))
    p = db.get(pid)
    if p and p[7]:
        await low_stock_all_channels(bot, p)
        await q.edit_message_text("Low Stock Alert sent to all channels!", reply_markup=kb_main())
    else:
        await q.edit_message_text("Product post not found!", reply_markup=kb_main())

async def connect_other_bot(update, context):
    if update.effective_user.id not in ADMIN:
        await update.message.reply_text("No access")
        return
    await update.message.reply_text("To connect another bot, please add this bot to your channel and then send /start")

async def on_bot_added(update, context):
    if update.effective_chat.type == 'channel':
        bot = context.bot
        bot_id = update.effective_chat.id
        chat = await bot.get_chat(bot_id)
        db.add_channel(str(bot_id), chat.title)
        # Send product list first so list_msg_id exists for the "FULL PRODUCT LIST" button
        await update_channel_list(bot, str(bot_id))
        # Post existing products to the channel
        for p in db.get_all():
            try:
                post_text = format_product_post(p)
                msg = await send_product_to_channel(bot, bot_id, p, post_text, kb_other_channel(str(bot_id)))
                db.set_channel_msg(p[0], str(bot_id), msg.message_id, "product")
            except Exception as e:
                print(f"Error posting product {p[1]} to bot {bot_id}: {e}")
        # Update the product list with links to the channel's own posts
        await update_channel_list(bot, str(bot_id))
        await context.bot.send_message(ADMIN[0], f"Bot added to channel {chat.title} ({bot_id}) and all products posted!\n\nSet a DM link for this channel: /setdm {bot_id} <dm link>")

async def msg_any(update, context):
    if not update.effective_user or update.effective_user.id not in ADMIN:
        return
    step = (context.user_data or {}).get('step', 0)
    bot = context.bot

    if step == "name":
        context.user_data['name'] = update.message.text.strip()
        context.user_data['step'] = "desc"
        await update.message.reply_text("Description:")
    elif step == "desc":
        context.user_data['description'] = update.message.text.strip()
        context.user_data['step'] = "media"
        await update.message.reply_text("Image/Video/GIF or Skip:", reply_markup=kb_skip())
    elif step == "price":
        context.user_data['price'] = update.message.text.strip()
        pid = db.add(context.user_data.get('name'), context.user_data.get('description', ''), context.user_data.get('cat', 'flower'), context.user_data.get('price'), context.user_data.get('media_type'), context.user_data.get('media_id'), None, None)
        p = db.get(pid)
        post_text = f"✦ <b>{p[1]}</b>\n"
        if p[2]: post_text += f"<blockquote>{p[2]}</blockquote>\n"
        await post_product_all_channels(bot, p, post_text)
        await update_price_list_all(bot)
        await update_product_lists_all(bot)
        context.user_data.clear()
        await update.message.reply_text("Product added to all channels!", reply_markup=kb_main())
    elif step == 'edit_price':
        new_price = update.message.text.strip()
        pid = context.user_data.get('edit_pid')
        if pid:
            p = db.get(pid)
            db.update(pid, price=new_price)
            post_text = f"✦ <b>{p[1]}</b>\n"
            if p[2]: post_text += f"<blockquote>{p[2]}</blockquote>\n"
            try:
                await bot.edit_message_caption(chat_id=CHANNEL, message_id=p[7], caption=post_text, parse_mode='HTML', reply_markup=kb_channel_product())
            except: pass
            for cm in db.get_channel_msgs(pid):
                try:
                    await bot.edit_message_caption(chat_id=cm[0], message_id=cm[1], caption=post_text, parse_mode='HTML', reply_markup=kb_other_channel(cm[0]))
                except: pass
            await update_price_list_all(bot)
            await update_product_lists_all(bot)
        context.user_data.clear()
        await update.message.reply_text("Price updated in all channels!", reply_markup=kb_main())
    elif step == "media":
        context.user_data['price'] = update.message.text.strip()
        pid = db.add(context.user_data.get('name'), context.user_data.get('description', ''), context.user_data.get('cat', 'flower'), context.user_data.get('price'), context.user_data.get('media_type'), context.user_data.get('media_id'), None, None)
        p = db.get(pid)
        post_text = f"✦ <b>{p[1]}</b>\n"
        if p[2]: post_text += f"<blockquote>{p[2]}</blockquote>\n"
        await post_product_all_channels(bot, p, post_text)
        await update_price_list_all(bot)
        await update_product_lists_all(bot)
        context.user_data.clear()
        await update.message.reply_text("Product added to all channels!", reply_markup=kb_main())

async def msg_media(update, context):
    if not update.effective_user or update.effective_user.id not in ADMIN:
        return
    step = (context.user_data or {}).get('step')
    if step == "media":
        msg = update.message
        if msg.photo:
            context.user_data['media_type'] = 'photo'
            context.user_data['media_id'] = msg.photo[-1].file_id
        elif msg.video:
            context.user_data['media_type'] = 'video'
            context.user_data['media_id'] = msg.video.file_id
        elif msg.animation:
            context.user_data['media_type'] = 'gif'
            context.user_data['media_id'] = msg.animation.file_id
        else:
            await update.message.reply_text("Send image/video/gif:")
            return
        context.user_data['step'] = "price"
        await update.message.reply_text("Price:")

def main():
    global scheduler_running
    app = Application.builder().token(BOT_TOKEN).build()
    scheduler_running = True

    # Delete any existing webhook to enable polling
    async def _delete_webhook():
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
            print("[startup] Webhook deleted, polling enabled")
        except Exception as e:
            print(f"[startup] Webhook delete error: {e}")

    import asyncio
    asyncio.get_event_loop().run_until_complete(_delete_webhook())

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("connect", connect_other_bot))
    app.add_handler(CommandHandler("manage", manage_other_channel))
    app.add_handler(CommandHandler("channels", channels_cmd))
    app.add_handler(CommandHandler("setdm", set_dm_link))

    app.add_handler(CallbackQueryHandler(cb_cancel_add, pattern="cancel_add"))
    app.add_handler(CallbackQueryHandler(cb_category, pattern="c_"))
    app.add_handler(CallbackQueryHandler(cb_skip_media, pattern="skip_media"))
    app.add_handler(CallbackQueryHandler(cb_edit_select, pattern="pe_"))
    app.add_handler(CallbackQueryHandler(cb_edit_price, pattern="ep_"))
    app.add_handler(CallbackQueryHandler(cb_del, pattern="pd_"))
    app.add_handler(CallbackQueryHandler(cb_low_stock, pattern="pl_"))
    app.add_handler(CallbackQueryHandler(cb_unmanage, pattern="uc_"))
    app.add_handler(CallbackQueryHandler(cb_main, pattern="m_|p_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_any))
    app.add_handler(MessageHandler(filters.PHOTO, msg_media))
    app.add_handler(MessageHandler(filters.VIDEO, msg_media))
    app.add_handler(MessageHandler(filters.ANIMATION, msg_media))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))

    main_loop = asyncio.get_event_loop()
    scheduler_thread = threading.Thread(target=run_scheduler, args=(app, main_loop), daemon=True)
    scheduler_thread.start()

    # Start the Flask website in a background thread
    flask_thread = threading.Thread(target=_run_flask, daemon=True)
    flask_thread.start()

    # Force-refresh the channel password post at startup
    async def _bootstrap_password():
        await rotate_if_needed(app.bot, force=False)
    try:
        main_loop.create_task(_bootstrap_password())
    except Exception as e:
        print(f"[password] bootstrap schedule error: {e}")

    print("Bot running...")
    app.run_polling(allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post", "callback_query"])
    scheduler_running = False

if __name__ == "__main__":
    main()
