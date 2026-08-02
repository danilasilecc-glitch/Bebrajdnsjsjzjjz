import os
import time
import sqlite3
import random
import threading
import json
from datetime import datetime, timedelta
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

bot = telebot.TeleBot(BOT_TOKEN)

# === БАЗА ДАННЫХ ===
conn = sqlite3.connect("space_empire.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    captain_name TEXT,
    level INTEGER DEFAULT 1,
    exp INTEGER DEFAULT 0,
    exp_to_next INTEGER DEFAULT 100,
    credits INTEGER DEFAULT 500,
    stars INTEGER DEFAULT 0,
    energy INTEGER DEFAULT 100,
    max_energy INTEGER DEFAULT 100,
    attack INTEGER DEFAULT 10,
    defense INTEGER DEFAULT 10,
    ship_hp INTEGER DEFAULT 100,
    max_ship_hp INTEGER DEFAULT 100,
    colony_level INTEGER DEFAULT 1,
    resources INTEGER DEFAULT 100,
    last_attack_time INTEGER DEFAULT 0,
    last_mine_time INTEGER DEFAULT 0,
    last_daily_time INTEGER DEFAULT 0,
    clan_id INTEGER DEFAULT NULL,
    shield INTEGER DEFAULT 0,
    weapon INTEGER DEFAULT 0,
    engine INTEGER DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    trade_cooldown INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS clans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    leader_id INTEGER,
    members TEXT DEFAULT '',
    created_at INTEGER,
    level INTEGER DEFAULT 1,
    treasury INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS wars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clan1_id INTEGER,
    clan2_id INTEGER,
    started_at INTEGER,
    status TEXT DEFAULT 'active'
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS market (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER,
    item_type TEXT,
    item_value INTEGER,
    price INTEGER,
    created_at INTEGER
)
''')

conn.commit()

# === КОНСТАНТЫ ===
ATTACK_COOLDOWN = 300  # 5 минут
MINE_COOLDOWN = 600     # 10 минут
DAILY_BONUS = 100
DAILY_STARS = 2
MAX_CLAN_MEMBERS = 20
SHOP_ITEMS = {
    "energy_pack": {"name": "⚡ Энергопак", "price_stars": 5, "effect": {"energy": 50}},
    "shield_boost": {"name": "🛡️ Усиление щитов", "price_stars": 10, "effect": {"shield": 10}},
    "weapon_boost": {"name": "🔫 Усиление оружия", "price_stars": 15, "effect": {"weapon": 10}},
    "engine_boost": {"name": "🚀 Усиление двигателя", "price_stars": 20, "effect": {"engine": 10}},
    "ship_repair": {"name": "🔧 Ремонт корабля", "price_stars": 8, "effect": {"ship_hp": 50}},
    "colony_boost": {"name": "🏗️ Развитие колонии", "price_stars": 25, "effect": {"colony_level": 1}},
    "exp_boost": {"name": "📈 Книга опыта", "price_stars": 12, "effect": {"exp": 100}}
}

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def get_player(user_id):
    cursor.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def create_player(user_id, username):
    cursor.execute(
        "INSERT INTO players (user_id, username, captain_name, credits) VALUES (?, ?, ?, ?)",
        (user_id, username, username, 500)
    )
    conn.commit()

def update_exp(user_id, exp_gain):
    player = get_player(user_id)
    if not player:
        return
    exp = player[3] + exp_gain
    level = player[2]
    exp_to_next = player[4]
    while exp >= exp_to_next:
        exp -= exp_to_next
        level += 1
        exp_to_next = int(exp_to_next * 1.5)
        cursor.execute(
            "UPDATE players SET max_energy = max_energy + 5, max_ship_hp = max_ship_hp + 10, attack = attack + 2, defense = defense + 2 WHERE user_id = ?",
            (user_id,)
        )
    cursor.execute(
        "UPDATE players SET level = ?, exp = ?, exp_to_next = ? WHERE user_id = ?",
        (level, exp, exp_to_next, user_id)
    )
    conn.commit()
    return level, exp, exp_to_next

def get_clan_members(clan_id):
    cursor.execute("SELECT members FROM clans WHERE id = ?", (clan_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        return []
    return result[0].split(",")

def add_clan_member(clan_id, user_id):
    members = get_clan_members(clan_id)
    if len(members) >= MAX_CLAN_MEMBERS:
        return False
    if str(user_id) in members:
        return False
    members.append(str(user_id))
    cursor.execute("UPDATE clans SET members = ? WHERE id = ?", (",".join(members), clan_id))
    cursor.execute("UPDATE players SET clan_id = ? WHERE user_id = ?", (clan_id, user_id))
    conn.commit()
    return True

def remove_clan_member(clan_id, user_id):
    members = get_clan_members(clan_id)
    if str(user_id) not in members:
        return False
    members.remove(str(user_id))
    cursor.execute("UPDATE clans SET members = ? WHERE id = ?", (",".join(members), clan_id))
    cursor.execute("UPDATE players SET clan_id = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    return True

def get_player_stats(user_id):
    player = get_player(user_id)
    if not player:
        return None
    return {
        "username": player[1],
        "captain_name": player[2],
        "level": player[3],
        "exp": player[4],
        "exp_to_next": player[5],
        "credits": player[6],
        "stars": player[7],
        "energy": player[8],
        "max_energy": player[9],
        "attack": player[10],
        "defense": player[11],
        "ship_hp": player[12],
        "max_ship_hp": player[13],
        "colony_level": player[14],
        "resources": player[15],
        "shield": player[19],
        "weapon": player[20],
        "engine": player[21],
        "clan_id": player[16],
        "is_banned": player[22]
    }

# === КЛАВИАТУРЫ ===

def main_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 Статус", callback_data="status"),
        InlineKeyboardButton("⛏️ Добыча", callback_data="mine"),
        InlineKeyboardButton("⚔️ Атака", callback_data="attack"),
        InlineKeyboardButton("🏆 Топ", callback_data="top"),
        InlineKeyboardButton("👥 Кланы", callback_data="clans"),
        InlineKeyboardButton("🏪 Магазин", callback_data="shop"),
        InlineKeyboardButton("📦 Рынок", callback_data="market"),
        InlineKeyboardButton("⭐ Донат", callback_data="donate"),
        InlineKeyboardButton("📖 Помощь", callback_data="help")
    )
    return kb

def attack_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⚔️ Найти жертву", callback_data="find_target"),
        InlineKeyboardButton("🛡️ Укрепить защиту", callback_data="boost_defense"),
        InlineKeyboardButton("🚀 Ускорить атаку", callback_data="boost_attack"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_main")
    )
    return kb

def clan_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 Мои кланы", callback_data="my_clans"),
        InlineKeyboardButton("📜 Список кланов", callback_data="clan_list"),
        InlineKeyboardButton("➕ Создать клан", callback_data="create_clan"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_main")
    )
    return kb

# ========================================
# === АДМИН-ПАНЕЛЬ (СКРЫТАЯ) ===
# ========================================

ADMIN_IDS = [6708740152]  # ТВОЙ ID

def admin_panel():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👤 Все игроки", callback_data="admin_all_players"),
        InlineKeyboardButton("💰 Выдать кредиты", callback_data="admin_give_credits"),
        InlineKeyboardButton("💸 Забрать кредиты", callback_data="admin_take_credits"),
        InlineKeyboardButton("⭐ Выдать звёзды", callback_data="admin_give_stars"),
        InlineKeyboardButton("🚫 Забрать звёзды", callback_data="admin_take_stars"),
        InlineKeyboardButton("📦 Выдать ресурсы", callback_data="admin_give_resources"),
        InlineKeyboardButton("📦 Забрать ресурсы", callback_data="admin_take_resources"),
        InlineKeyboardButton("📈 Выдать опыт", callback_data="admin_give_exp"),
        InlineKeyboardButton("🔨 Забанить", callback_data="admin_ban"),
        InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban"),
        InlineKeyboardButton("🗑️ Удалить игрока", callback_data="admin_delete_player"),
        InlineKeyboardButton("🔙 Выйти", callback_data="admin_exit")
    )
    return kb

@bot.message_handler(commands=['rgscsddxagdacbs'])
def admin_cmd(msg):
    user_id = msg.from_user.id
    if user_id not in ADMIN_IDS:
        bot.reply_to(msg, "❌ Недостаточно прав.")
        return
    bot.send_message(
        user_id,
        "🛡️ **Админ-панель**\n\nВыбери действие:",
        parse_mode='Markdown',
        reply_markup=admin_panel()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_handle(call):
    user_id = call.from_user.id
    if user_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ Недостаточно прав.")
        return
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if data == "admin_all_players":
        cursor.execute("SELECT user_id, username, captain_name, level, credits, stars, is_banned FROM players ORDER BY user_id")
        players = cursor.fetchall()
        if not players:
            bot.edit_message_text("❌ Нет игроков.", chat_id, msg_id, reply_markup=admin_panel())
            bot.answer_callback_query(call.id)
            return
        text = "👤 **Все игроки:**\n\n"
        for p in players:
            status = "🔴 Забанен" if p[6] else "🟢 Активен"
            text += f"`{p[0]}` | @{p[1]} | {p[2]} | Ур. {p[3]} | 💰{p[4]} | ⭐{p[5]} | {status}\n"
        if len(text) > 4000:
            text = text[:4000] + "\n\n... (слишком много игроков)"
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=admin_panel())
        bot.answer_callback_query(call.id)
        return

    if data == "admin_give_credits":
        bot.send_message(chat_id, "Введи `user_id` и сумму через пробел (например: `123456789 1000`):")
        bot.register_next_step_handler(call.message, admin_give_credits_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_take_credits":
        bot.send_message(chat_id, "Введи `user_id` и сумму через пробел (например: `123456789 500`):")
        bot.register_next_step_handler(call.message, admin_take_credits_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_give_stars":
        bot.send_message(chat_id, "Введи `user_id` и количество звёзд через пробел (например: `123456789 50`):")
        bot.register_next_step_handler(call.message, admin_give_stars_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_take_stars":
        bot.send_message(chat_id, "Введи `user_id` и количество звёзд через пробел (например: `123456789 20`):")
        bot.register_next_step_handler(call.message, admin_take_stars_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_give_resources":
        bot.send_message(chat_id, "Введи `user_id` и количество ресурсов через пробел (например: `123456789 500`):")
        bot.register_next_step_handler(call.message, admin_give_resources_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_take_resources":
        bot.send_message(chat_id, "Введи `user_id` и количество ресурсов через пробел (например: `123456789 200`):")
        bot.register_next_step_handler(call.message, admin_take_resources_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_give_exp":
        bot.send_message(chat_id, "Введи `user_id` и количество опыта через пробел (например: `123456789 1000`):")
        bot.register_next_step_handler(call.message, admin_give_exp_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_ban":
        bot.send_message(chat_id, "Введи `user_id` игрока для бана (например: `123456789`):")
        bot.register_next_step_handler(call.message, admin_ban_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_unban":
        bot.send_message(chat_id, "Введи `user_id` игрока для разбана (например: `123456789`):")
        bot.register_next_step_handler(call.message, admin_unban_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_delete_player":
        bot.send_message(chat_id, "⚠️ Введи `user_id` игрока для ПОЛНОГО удаления (например: `123456789`):")
        bot.register_next_step_handler(call.message, admin_delete_player_step)
        bot.answer_callback_query(call.id)
        return

    if data == "admin_exit":
        bot.edit_message_text("🛡️ Выход из админ-панели.", chat_id, msg_id, reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

def admin_give_credits_step(msg):
    try:
        uid, amount = map(int, msg.text.split())
        cursor.execute("UPDATE players SET credits = credits + ? WHERE user_id = ?", (amount, uid))
        conn.commit()
        bot.reply_to(msg, f"✅ Игроку `{uid}` выдано {amount} кредитов.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id сумма`")

def admin_take_credits_step(msg):
    try:
        uid, amount = map(int, msg.text.split())
        cursor.execute("UPDATE players SET credits = credits - ? WHERE user_id = ?", (amount, uid))
        conn.commit()
        bot.reply_to(msg, f"✅ У игрока `{uid}` забрано {amount} кредитов.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id сумма`")

def admin_give_stars_step(msg):
    try:
        uid, amount = map(int, msg.text.split())
        cursor.execute("UPDATE players SET stars = stars + ? WHERE user_id = ?", (amount, uid))
        conn.commit()
        bot.reply_to(msg, f"✅ Игроку `{uid}` выдано {amount} звёзд.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id количество`")

def admin_take_stars_step(msg):
    try:
        uid, amount = map(int, msg.text.split())
        cursor.execute("UPDATE players SET stars = stars - ? WHERE user_id = ?", (amount, uid))
        conn.commit()
        bot.reply_to(msg, f"✅ У игрока `{uid}` забрано {amount} звёзд.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id количество`")

def admin_give_resources_step(msg):
    try:
        uid, amount = map(int, msg.text.split())
        cursor.execute("UPDATE players SET resources = resources + ? WHERE user_id = ?", (amount, uid))
        conn.commit()
        bot.reply_to(msg, f"✅ Игроку `{uid}` выдано {amount} ресурсов.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id количество`")

def admin_take_resources_step(msg):
    try:
        uid, amount = map(int, msg.text.split())
        cursor.execute("UPDATE players SET resources = resources - ? WHERE user_id = ?", (amount, uid))
        conn.commit()
        bot.reply_to(msg, f"✅ У игрока `{uid}` забрано {amount} ресурсов.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id количество`")

def admin_give_exp_step(msg):
    try:
        uid, amount = map(int, msg.text.split())
        update_exp(uid, amount)
        bot.reply_to(msg, f"✅ Игроку `{uid}` выдано {amount} опыта.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id количество`")

def admin_ban_step(msg):
    try:
        uid = int(msg.text.strip())
        cursor.execute("UPDATE players SET is_banned = 1 WHERE user_id = ?", (uid,))
        conn.commit()
        bot.reply_to(msg, f"🔨 Игрок `{uid}` забанен.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id`")

def admin_unban_step(msg):
    try:
        uid = int(msg.text.strip())
        cursor.execute("UPDATE players SET is_banned = 0 WHERE user_id = ?", (uid,))
        conn.commit()
        bot.reply_to(msg, f"🔓 Игрок `{uid}` разбанен.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id`")

def admin_delete_player_step(msg):
    try:
        uid = int(msg.text.strip())
        cursor.execute("DELETE FROM players WHERE user_id = ?", (uid,))
        conn.commit()
        bot.reply_to(msg, f"🗑️ Игрок `{uid}` удалён.")
    except:
        bot.reply_to(msg, "❌ Ошибка. Используй: `user_id`")

# === ОБРАБОТЧИКИ КОМАНД ===

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    user_id = msg.from_user.id
    username = msg.from_user.username or f"User{user_id}"
    if not get_player(user_id):
        create_player(user_id, username)
        bot.send_message(
            user_id,
            "🚀 **Добро пожаловать в Космическую Империю!**\n\n"
            "Ты — капитан нового корабля. Исследуй, добывай, сражайся и строй свою империю.\n"
            "Используй меню для управления.\n\n"
            "⭐ **Telegram Stars** — ускоряют прокачку. Ты можешь купить их через донат.",
            parse_mode='Markdown',
            reply_markup=main_menu()
        )
    else:
        bot.send_message(user_id, "🚀 **С возвращением, капитан!**", parse_mode='Markdown', reply_markup=main_menu())

# === ОБРАБОТКА КНОПОК ===

@bot.callback_query_handler(func=lambda call: True)
def handle(call):
    user_id = call.from_user.id
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if data == "back_main":
        bot.edit_message_text("🚀 **Космическая Империя**\n\nВыбери действие:", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "help":
        text = (
            "📖 **Помощь**\n\n"
            "📊 Статус — твои характеристики.\n"
            "⛏️ Добыча — ресурсы для колонии (КД 10 мин).\n"
            "⚔️ Атака — найди жертву и ограбь (КД 5 мин).\n"
            "🏆 Топ — лучшие игроки.\n"
            "👥 Кланы — создавай/вступай в кланы.\n"
            "🏪 Магазин — покупка за ресурсы.\n"
            "📦 Рынок — торговля с игроками.\n"
            "⭐ Донат — покупка преимуществ.\n\n"
            "⚡ **КД** — задержка между действиями.\n"
            "⭐ **Stars** — внутриигровая валюта Телеграм."
        )
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "status":
        stats = get_player_stats(user_id)
        if not stats:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        text = (
            f"📊 **Статус капитана**\n\n"
            f"👤 Имя: {stats['captain_name']}\n"
            f"🎯 Уровень: {stats['level']} ({stats['exp']}/{stats['exp_to_next']} XP)\n"
            f"💰 Кредиты: {stats['credits']} | ⭐ Звёзды: {stats['stars']}\n"
            f"⚡ Энергия: {stats['energy']}/{stats['max_energy']}\n"
            f"🏗️ Колония: уровень {stats['colony_level']} | Ресурсы: {stats['resources']}\n"
            f"🛡️ Щиты: {stats['shield']} | 🔫 Оружие: {stats['weapon']} | 🚀 Двигатель: {stats['engine']}\n"
            f"❤️ Корабль: {stats['ship_hp']}/{stats['max_ship_hp']}\n"
            f"⚔️ Атака: {stats['attack']} | 🛡️ Защита: {stats['defense']}"
        )
        if stats['clan_id']:
            cursor.execute("SELECT name FROM clans WHERE id = ?", (stats['clan_id'],))
            clan = cursor.fetchone()
            if clan:
                text += f"\n👥 Клан: {clan[0]}"
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "mine":
        player = get_player(user_id)
        if not player:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        now = int(time.time())
        if now - player[17] < MINE_COOLDOWN:
            remaining = MINE_COOLDOWN - (now - player[17])
            bot.answer_callback_query(call.id, f"⏳ Жди {remaining//60} мин до добычи")
            return
        mined = random.randint(10, 50) + player[21] // 2
        cursor.execute("UPDATE players SET resources = resources + ?, last_mine_time = ? WHERE user_id = ?", (mined, now, user_id))
        conn.commit()
        if random.random() < 0.1:
            bonus = random.randint(5, 20)
            cursor.execute("UPDATE players SET credits = credits + ? WHERE user_id = ?", (bonus, user_id))
            conn.commit()
            bot.edit_message_text(
                f"⛏️ **Добыча успешна!**\n\nРесурсы +{mined}\n💰 Бонус: {bonus} кредитов!",
                chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu()
            )
        else:
            bot.edit_message_text(
                f"⛏️ **Добыча успешна!**\n\nРесурсы +{mined}",
                chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu()
            )
        bot.answer_callback_query(call.id)
        return

    if data == "attack":
        player = get_player(user_id)
        if not player:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            return
        now = int(time.time())
        if now - player[16] < ATTACK_COOLDOWN:
            remaining = ATTACK_COOLDOWN - (now - player[16])
            bot.answer_callback_query(call.id, f"⏳ Жди {remaining//60} мин для атаки")
            return
        bot.edit_message_text("⚔️ **Атака**\n\nВыбери действие:", chat_id, msg_id, parse_mode='Markdown', reply_markup=attack_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "find_target":
        cursor.execute("SELECT user_id, captain_name, credits, resources FROM players WHERE user_id != ? AND is_banned = 0", (user_id,))
        targets = cursor.fetchall()
        if not targets:
            bot.answer_callback_query(call.id, "❌ Нет целей")
            return
        target = random.choice(targets)
        target_id, target_name, target_credits, target_resources = target
        atk = get_player_stats(user_id)['attack'] + get_player_stats(user_id)['weapon']
        dfn = get_player_stats(target_id)['defense'] + get_player_stats(target_id)['shield']
        damage = max(1, atk - dfn // 2)
        reward_credits = min(target_credits, random.randint(10, 50))
        reward_resources = min(target_resources, random.randint(5, 20))
        cursor.execute("UPDATE players SET credits = credits - ?, resources = resources - ? WHERE user_id = ?", (reward_credits, reward_resources, target_id))
        cursor.execute("UPDATE players SET credits = credits + ?, resources = resources + ? WHERE user_id = ?", (reward_credits, reward_resources, user_id))
        exp_gain = random.randint(5, 15)
        update_exp(user_id, exp_gain)
        cursor.execute("UPDATE players SET last_attack_time = ? WHERE user_id = ?", (int(time.time()), user_id))
        conn.commit()
        bot.edit_message_text(
            f"⚔️ **Атака успешна!**\n\n"
            f"🎯 Жертва: {target_name}\n"
            f"💥 Урон: {damage}\n"
            f"💰 Кредиты: +{reward_credits}\n"
            f"📦 Ресурсы: +{reward_resources}\n"
            f"⭐ Опыт: +{exp_gain}",
            chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu()
        )
        bot.answer_callback_query(call.id)
        return

    if data == "boost_defense":
        stats = get_player_stats(user_id)
        if stats['credits'] < 50:
            bot.answer_callback_query(call.id, "❌ Нужно 50 кредитов")
            return
        cursor.execute("UPDATE players SET credits = credits - 50, defense = defense + 3 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🛡️ **Защита усилена!**\n\n+3 к защите за 50 кредитов.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "boost_attack":
        stats = get_player_stats(user_id)
        if stats['credits'] < 50:
            bot.answer_callback_query(call.id, "❌ Нужно 50 кредитов")
            return
        cursor.execute("UPDATE players SET credits = credits - 50, attack = attack + 3 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("⚔️ **Атака усилена!**\n\n+3 к атаке за 50 кредитов.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "top":
        cursor.execute("SELECT captain_name, level, credits, stars FROM players WHERE is_banned = 0 ORDER BY level DESC, credits DESC LIMIT 10")
        top = cursor.fetchall()
        text = "🏆 **Топ игроков**\n\n"
        for i, (name, level, credits, stars) in enumerate(top, 1):
            text += f"{i}. {name} — Ур. {level}, 💰{credits}, ⭐{stars}\n"
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "clans":
        bot.edit_message_text("👥 **Кланы**\n\nВыбери действие:", chat_id, msg_id, parse_mode='Markdown', reply_markup=clan_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "my_clans":
        stats = get_player_stats(user_id)
        if not stats or not stats['clan_id']:
            bot.answer_callback_query(call.id, "❌ Ты не в клане")
            return
        clan_id = stats['clan_id']
        cursor.execute("SELECT name, leader_id, members, treasury FROM clans WHERE id = ?", (clan_id,))
        clan = cursor.fetchone()
        if not clan:
            bot.answer_callback_query(call.id, "❌ Клан не найден")
            return
        members = clan[2].split(",") if clan[2] else []
        text = f"👥 **Клан: {clan[0]}**\n\n👑 Лидер: {clan[1]}\n👥 Участников: {len(members)}\n💰 Сокровищница: {clan[3]}\n\nУчастники:\n"
        for m in members[:15]:
            cursor.execute("SELECT captain_name FROM players WHERE user_id = ?", (int(m),))
            name = cursor.fetchone()
            if name:
                text += f"- {name[0]}\n"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="clans"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    if data == "clan_list":
        cursor.execute("SELECT id, name, leader_id FROM clans ORDER BY id DESC LIMIT 20")
        clans = cursor.fetchall()
        if not clans:
            bot.edit_message_text("📜 **Кланы**\n\nНет созданных кланов.", chat_id, msg_id, reply_markup=main_menu())
            bot.answer_callback_query(call.id)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for clan in clans:
            kb.add(InlineKeyboardButton(f"📌 {clan[1]} (лидер: {clan[2]})", callback_data=f"clan_info_{clan[0]}"))
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="clans"))
        bot.edit_message_text("📜 **Кланы**\n\nВыбери клан для просмотра:", chat_id, msg_id, reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("clan_info_"):
        clan_id = int(data.split("_")[2])
        cursor.execute("SELECT name, leader_id, members FROM clans WHERE id = ?", (clan_id,))
        clan = cursor.fetchone()
        if not clan:
            bot.answer_callback_query(call.id, "❌ Клан не найден")
            return
        members = clan[2].split(",") if clan[2] else []
        text = f"📋 **Клан: {clan[0]}**\n\n👑 Лидер: {clan[1]}\n👥 Участников: {len(members)}\n\nУчастники:\n"
        for m in members[:15]:
            cursor.execute("SELECT captain_name FROM players WHERE user_id = ?", (int(m),))
            name = cursor.fetchone()
            if name:
                text += f"- {name[0]}\n"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📥 Вступить", callback_data=f"join_clan_{clan_id}"))
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="clan_list"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("join_clan_"):
        clan_id = int(data.split("_")[2])
        if add_clan_member(clan_id, user_id):
            bot.answer_callback_query(call.id, "✅ Ты вступил в клан!")
            bot.edit_message_text("✅ **Ты вступил в клан!**", chat_id, msg_id, reply_markup=main_menu())
        else:
            bot.answer_callback_query(call.id, "❌ Не удалось вступить в клан")
        return

    if data == "create_clan":
        bot.send_message(chat_id, "📝 **Создание клана**\n\nВведи название клана (от 3 до 15 символов):")
        bot.register_next_step_handler(call.message, create_clan_step)
        bot.answer_callback_query(call.id)
        return

    if data == "shop":
        text = "🏪 **Магазин**\n\nПокупка за ресурсы:\n"
        kb = InlineKeyboardMarkup(row_width=2)
        # Улучшения за ресурсы
        kb.add(InlineKeyboardButton("🛡️ Улучшить щиты (50 ресурсов)", callback_data="shop_shield"))
        kb.add(InlineKeyboardButton("🔫 Улучшить оружие (50 ресурсов)", callback_data="shop_weapon"))
        kb.add(InlineKeyboardButton("🚀 Улучшить двигатель (50 ресурсов)", callback_data="shop_engine"))
        kb.add(InlineKeyboardButton("🏗️ Развить колонию (100 ресурсов)", callback_data="shop_colony"))
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="back_main"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    if data == "shop_shield":
        stats = get_player_stats(user_id)
        if stats['resources'] < 50:
            bot.answer_callback_query(call.id, "❌ Нужно 50 ресурсов")
            return
        cursor.execute("UPDATE players SET resources = resources - 50, shield = shield + 5 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🛡️ **Щиты улучшены!** +5 к щитам.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "shop_weapon":
        stats = get_player_stats(user_id)
        if stats['resources'] < 50:
            bot.answer_callback_query(call.id, "❌ Нужно 50 ресурсов")
            return
        cursor.execute("UPDATE players SET resources = resources - 50, weapon = weapon + 5 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🔫 **Оружие улучшено!** +5 к оружию.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "shop_engine":
        stats = get_player_stats(user_id)
        if stats['resources'] < 50:
            bot.answer_callback_query(call.id, "❌ Нужно 50 ресурсов")
            return
        cursor.execute("UPDATE players SET resources = resources - 50, engine = engine + 5 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🚀 **Двигатель улучшен!** +5 к двигателю.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "shop_colony":
        stats = get_player_stats(user_id)
        if stats['resources'] < 100:
            bot.answer_callback_query(call.id, "❌ Нужно 100 ресурсов")
            return
        if stats['colony_level'] >= 5:
            bot.answer_callback_query(call.id, "❌ Колония уже максимального уровня")
            return
        cursor.execute("UPDATE players SET resources = resources - 100, colony_level = colony_level + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🏗️ **Колония развита!** Теперь уровень {}. Новые возможности открыты!".format(stats['colony_level']+1), chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "donate":
        text = (
            "⭐ **Донат (Telegram Stars)**\n\n"
            "Купи звёзды для ускорения прокачки:\n"
            "🛡️ 10 звёзд — +5 к щитам\n"
            "🔫 10 звёзд — +5 к оружию\n"
            "🚀 10 звёзд — +5 к двигателю\n"
            "💊 5 звёзд — восстановление энергии (50)\n"
            "🔧 3 звёзды — ремонт корабля (+50 HP)\n\n"
            "Звёзды покупаются через Telegram Stars. Цена: 1 Star = 1 звезда в боте."
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🛡️ Купить щиты (10⭐)", callback_data="donate_shield"),
            InlineKeyboardButton("🔫 Купить оружие (10⭐)", callback_data="donate_weapon"),
            InlineKeyboardButton("🚀 Купить двигатель (10⭐)", callback_data="donate_engine"),
            InlineKeyboardButton("💊 Энергия (5⭐)", callback_data="donate_energy"),
            InlineKeyboardButton("🔧 Ремонт (3⭐)", callback_data="donate_repair"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_main")
        )
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    if data == "donate_shield":
        stats = get_player_stats(user_id)
        if stats['stars'] < 10:
            bot.answer_callback_query(call.id, "❌ Нужно 10 звёзд")
            return
        cursor.execute("UPDATE players SET stars = stars - 10, shield = shield + 5 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🛡️ **Щиты усилены!** +5 к щитам.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "donate_weapon":
        stats = get_player_stats(user_id)
        if stats['stars'] < 10:
            bot.answer_callback_query(call.id, "❌ Нужно 10 звёзд")
            return
        cursor.execute("UPDATE players SET stars = stars - 10, weapon = weapon + 5 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🔫 **Оружие усилено!** +5 к оружию.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "donate_engine":
        stats = get_player_stats(user_id)
        if stats['stars'] < 10:
            bot.answer_callback_query(call.id, "❌ Нужно 10 звёзд")
            return
        cursor.execute("UPDATE players SET stars = stars - 10, engine = engine + 5 WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🚀 **Двигатель усилен!** +5 к двигателю.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "donate_energy":
        stats = get_player_stats(user_id)
        if stats['stars'] < 5:
            bot.answer_callback_query(call.id, "❌ Нужно 5 звёзд")
            return
        cursor.execute("UPDATE players SET stars = stars - 5, energy = max_energy WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("💊 **Энергия восстановлена!** Теперь у тебя полная энергия.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "donate_repair":
        stats = get_player_stats(user_id)
        if stats['stars'] < 3:
            bot.answer_callback_query(call.id, "❌ Нужно 3 звёзды")
            return
        cursor.execute("UPDATE players SET stars = stars - 3, ship_hp = max_ship_hp WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("🔧 **Корабль отремонтирован!**", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data == "market":
        cursor.execute("SELECT id, seller_id, item_type, item_value, price FROM market ORDER BY id DESC LIMIT 10")
        offers = cursor.fetchall()
        if not offers:
            bot.edit_message_text("📦 **Рынок**\n\nНет активных предложений.", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
            bot.answer_callback_query(call.id)
            return
        text = "📦 **Рынок**\n\n"
        kb = InlineKeyboardMarkup(row_width=1)
        for offer in offers:
            seller = get_player(offer[1])
            seller_name = seller[2] if seller else "Неизвестный"
            text += f"📌 {offer[2]} x{offer[3]} — {offer[4]} кредитов (продавец: {seller_name})\n"
            kb.add(InlineKeyboardButton(f"Купить {offer[2]} x{offer[3]}", callback_data=f"buy_market_{offer[0]}"))
        kb.add(InlineKeyboardButton("➕ Выставить товар", callback_data="market_sell"))
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="back_main"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown', reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    if data == "market_sell":
        stats = get_player_stats(user_id)
        if stats['resources'] < 10:
            bot.answer_callback_query(call.id, "❌ У тебя мало ресурсов для продажи")
            return
        price = random.randint(5, 20) * stats['resources'] // 10
        cursor.execute(
            "INSERT INTO market (seller_id, item_type, item_value, price, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, "Ресурсы", stats['resources'] // 2, price, int(time.time()))
        )
        cursor.execute("UPDATE players SET resources = resources - ? WHERE user_id = ?", (stats['resources'] // 2, user_id))
        conn.commit()
        bot.edit_message_text("📦 **Товар выставлен на рынок!**", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

    if data.startswith("buy_market_"):
        offer_id = int(data.split("_")[2])
        cursor.execute("SELECT seller_id, item_type, item_value, price FROM market WHERE id = ?", (offer_id,))
        offer = cursor.fetchone()
        if not offer:
            bot.answer_callback_query(call.id, "❌ Предложение устарело")
            return
        seller_id, item_type, item_value, price = offer
        if seller_id == user_id:
            bot.answer_callback_query(call.id, "❌ Нельзя купить у себя")
            return
        stats = get_player_stats(user_id)
        if stats['credits'] < price:
            bot.answer_callback_query(call.id, f"❌ Нужно {price} кредитов")
            return
        cursor.execute("UPDATE players SET credits = credits - ? WHERE user_id = ?", (price, user_id))
        cursor.execute("UPDATE players SET credits = credits + ? WHERE user_id = ?", (price, seller_id))
        cursor.execute("UPDATE players SET resources = resources + ? WHERE user_id = ?", (item_value, user_id))
        cursor.execute("DELETE FROM market WHERE id = ?", (offer_id,))
        conn.commit()
        bot.edit_message_text("✅ **Покупка совершена!**", chat_id, msg_id, parse_mode='Markdown', reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return

def create_clan_step(msg):
    user_id = msg.from_user.id
    name = msg.text.strip()
    if len(name) < 3 or len(name) > 15:
        bot.send_message(user_id, "❌ Название должно быть от 3 до 15 символов. Попробуй снова.")
        bot.register_next_step_handler(msg, create_clan_step)
        return
    cursor.execute("INSERT INTO clans (name, leader_id, members, created_at) VALUES (?, ?, ?, ?)", (name, user_id, str(user_id), int(time.time())))
    clan_id = cursor.lastrowid
    cursor.execute("UPDATE players SET clan_id = ? WHERE user_id = ?", (clan_id, user_id))
    conn.commit()
    bot.send_message(user_id, f"✅ **Клан {name} создан!**", parse_mode='Markdown', reply_markup=main_menu())

# === АВТО-ПИНГ (для Render) ===
def keep_alive():
    while True:
        time.sleep(300)
        try:
            bot.get_me()
            print("✅ Пинг успешен")
        except Exception as e:
            print(f"❌ Ошибка пинга: {e}")

threading.Thread(target=keep_alive, daemon=True).start()

# === ЗАПУСК ===
print("🚀 Космическая империя запущена!")
bot.infinity_polling()