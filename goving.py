import asyncio
import logging
import sqlite3
import os
import json
import requests
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [6997318168, 7344521311]
CRYPTOBOT_TOKEN = os.environ.get("CRYPTOBOT_TOKEN", "")

# Настройки
CARD_NUMBER = "2200700527205453"
STAR_RATE = 1.5
USD_RATE = 85.0

PREMIUM_PRICES = {
    "3m": {"rub": 1124.11, "name": "3 месяца"},
    "6m": {"rub": 1498.81, "name": "6 месяцев"}, 
    "1y": {"rub": 2716.59, "name": "1 год"}
}

REPUTATION_CHANNEL = "https://t.me/+3pbAABRgo1ljOTJi"
NEWS_CHANNEL = "https://t.me/NewsDigistars"
SUPPORT_USER = "Voidovi"
CHANNEL_ID = -1003632929882
CHANNEL_USERNAME = "NewsDigistars"

# ========== CRYPTOBOT ==========
class CryptoBotAPI:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount, description=""):
        try:
            url = f"{self.base_url}/createInvoice"
            headers = {"Crypto-Pay-API-Token": self.token}
            
            amount_usdt = amount / 85.0
            
            data = {
                "asset": "USDT",
                "amount": str(round(amount_usdt, 2)),
                "description": description[:1024],
                "paid_btn_name": "openBot",
                "paid_btn_url": "https://t.me/DigiStoreBot",
                "payload": f"order_{int(datetime.now().timestamp())}",
                "allow_anonymous": False
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=30)
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]
                return {
                    "success": True,
                    "invoice_id": invoice["invoice_id"],
                    "pay_url": invoice["pay_url"],
                    "amount": invoice["amount"],
                    "asset": invoice["asset"]
                }
            else:
                return {"success": False, "error": result.get("error", {}).get("name", "Unknown error")}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def check_invoice_status(self, invoice_id):
        try:
            url = f"{self.base_url}/getInvoices"
            headers = {"Crypto-Pay-API-Token": self.token}
            
            params = {"invoice_ids": invoice_id}
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]["items"][0]
                return {
                    "success": True,
                    "status": invoice["status"],
                    "paid_at": invoice.get("paid_at"),
                    "amount": invoice.get("amount")
                }
            else:
                return {"success": False, "error": result.get("error", {}).get("name", "Unknown error")}
                
        except Exception as e:
            return {"success": False, "error": str(e)}

cryptobot = CryptoBotAPI(CRYPTOBOT_TOKEN) if CRYPTOBOT_TOKEN else None

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name="digistore.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_type TEXT,
            recipient TEXT,
            details TEXT,
            amount_rub REAL,
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            invoice_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, full_name):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name)
        )
        self.conn.commit()
    
    def add_order(self, user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id=None):
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO orders 
            (user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id) 
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id)
        )
        order_id = cursor.lastrowid
        self.conn.commit()
        return order_id
    
    def update_order_status(self, order_id, status):
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
    
    def update_invoice_id(self, order_id, invoice_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET invoice_id = ? WHERE id = ?",
            (invoice_id, order_id)
        )
        self.conn.commit()
    
    def add_payment_photo(self, order_id, file_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET details = json_set(details, '$.payment_photo', ?) WHERE id = ?",
            (file_id, order_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
    
    def get_active_orders(self):
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id, user_id, order_type, recipient, details, amount_rub, 
                       payment_method, status, created_at 
                FROM orders 
                WHERE status NOT IN ('completed', 'cancelled')
                ORDER BY created_at DESC
            """)
            return cursor.fetchall()
        except Exception as e:
            return []
    
    def get_order(self, order_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT user_id, order_type, recipient, details, amount_rub, 
                   payment_method, status, invoice_id, created_at 
            FROM orders WHERE id = ?
        """, (order_id,))
        return cursor.fetchone()
    
    def get_user_orders_count(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,))
        return cursor.fetchone()[0]
    
    def get_user_info(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT username, full_name, created_at FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()
    
    def get_users_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]
    
    def get_total_orders_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders")
        return cursor.fetchone()[0]
    
    def get_total_revenue(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT SUM(amount_rub) FROM orders WHERE status IN ('confirmed', 'completed')")
        result = cursor.fetchone()[0]
        return result if result else 0

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()

user_states = {}
admin_confirmations = {}

# ========== НАСТРОЙКА MENU BUTTON ==========
async def setup_menu_button():
    """Настройка menu button с одной командой /start"""
    try:
        commands = [
            types.BotCommand(command="start", description="🚀 Запустить бота"),
        ]
        
        await bot.set_my_commands(commands)
        print("✅ Menu button настроен с командой /start")
    except Exception as e:
        print(f"❌ Ошибка настройки menu button: {e}")

# ========== ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ==========
async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        
        valid_statuses = [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        ]
        
        return chat_member.status in valid_statuses
    except Exception as e:
        return False

async def require_subscription(user_id: int, message: types.Message = None, callback: types.CallbackQuery = None):
    subscribe_text = (
        "<b>📢 Подпишитесь на канал</b>\n\n"
        "Чтобы пользоваться ботом, необходимо подписаться на наш канал:\n\n"
        f"👉 <b>Канал:</b> @{CHANNEL_USERNAME}\n\n"
        "После подписки нажмите кнопку ниже для проверки:"
    )
    
    subscribe_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME}")],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")]
    ])
    
    if message:
        await message.answer(subscribe_text, reply_markup=subscribe_kb, parse_mode="HTML")
    elif callback:
        await callback.message.answer(subscribe_text, reply_markup=subscribe_kb, parse_mode="HTML")

# ========== КЛАВИАТУРЫ ==========
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐️ Купить звезды", callback_data="buy_stars"),
            InlineKeyboardButton(text="👑 Купить премиум", callback_data="buy_premium")
        ],
        [
            InlineKeyboardButton(text="💱 Обмен валют", callback_data="exchange"),
            InlineKeyboardButton(text="🧮 Калькулятор", callback_data="calculator")
        ],
        [
            InlineKeyboardButton(text="🎩 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="📊 Информация", callback_data="info")
        ],
        [
            InlineKeyboardButton(text="🆘 Тех поддержка", url=f"https://t.me/{SUPPORT_USER}")
        ]
    ])

def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Активные заказы", callback_data="admin_active_orders")],
        [InlineKeyboardButton(text="🤖 Бот", callback_data="admin_bot_stats")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
    ])

def confirm_payment_kb(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"confirm_paid_{order_id}")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def back_kb(target):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=target)]
    ])

def calculator_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

# ========== ГЛАВНОЕ МЕНЮ С ЦИТАТОЙ ==========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, message=message)
        return
    
    username = message.from_user.username or ""
    full_name = message.from_user.full_name
    
    db.add_user(user_id, username, full_name)
    
    caption = (
        "<b>🪐 Digi Store - Главное меню</b>\n\n"
        "<blockquote>C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары</blockquote>\n\n"
        "<b>Выберите действие:</b>"
    )
    
    await message.answer(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )

async def show_main_menu(message: types.Message):
    caption = (
        "<b>🪐 Digi Store - Главное меню</b>\n\n"
        "<blockquote>C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары</blockquote>\n\n"
        "<b>Выберите действие:</b>"
    )
    
    await message.answer(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "check_subscription")
async def check_subscription_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if await check_subscription(user_id):
        username = callback.from_user.username or ""
        full_name = callback.from_user.full_name
        
        db.add_user(user_id, username, full_name)
        
        caption = (
            "<b>✅ Отлично! Вы подписаны на канал.</b>\n\n"
            "<b>🪐 Digi Store - Главное меню</b>\n\n"
            "<blockquote>C помощью нашего магазина вы можете:\n"
            "• ⭐️ Купить Telegram Stars\n"
            "• 👑 Купить Telegram Premium\n"
            "• 💱 Обменять рубли на доллары</blockquote>\n\n"
            "<b>Выберите действие:</b>"
        )
        
        await callback.message.edit_text(
            text=caption,
            reply_markup=main_menu_kb(),
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        await require_subscription(user_id, callback=callback)
    
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    caption = (
        "<b>🪐 Digi Store - Главное меню</b>\n\n"
        "<blockquote>C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары</blockquote>\n\n"
        "<b>Выберите действие:</b>"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

# ========== ПРОФИЛЬ ==========
@dp.callback_query(F.data == "profile")
async def profile_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    user_info = db.get_user_info(user_id)
    
    if user_info:
        username, full_name, created_at = user_info
        orders_count = db.get_user_orders_count(user_id)
        
        if created_at:
            if isinstance(created_at, str):
                reg_date = created_at[:10]
                reg_time = created_at[11:16]
            else:
                reg_date = str(created_at)[:10]
                reg_time = str(created_at)[11:16]
        else:
            reg_date = "Неизвестно"
            reg_time = ""
        
        caption = (
            f"<b>🎩 Профиль</b>\n\n"
            f"<b>🆔 ID:</b> {user_id}\n"
            f"<b>📝 Имя:</b> @{username if username else 'Нет юзернейма'}\n\n"
            f"<b>📦 Заказы:</b>\n"
            f"├ <b>Всего заказов:</b> {orders_count};\n\n"
            f"<b>📅 Регистрация:</b> {reg_date} {reg_time}."
        )
    else:
        caption = (
            f"<b>🎩 Профиль</b>\n\n"
            f"<b>🆔 ID:</b> {user_id}\n"
            f"<b>📝 Имя:</b> @{callback.from_user.username or 'Нет юзернейма'}\n\n"
            f"<b>📦 Заказы:</b>\n"
            f"├ <b>Всего заказов:</b> 0;\n\n"
            f"<b>📅 Регистрация:</b> Недавно."
        )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="profile")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# ========== КАЛЬКУЛЯТОР ==========
@dp.callback_query(F.data == "calculator")
async def calculator_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    user_states[callback.from_user.id] = {"action": "waiting_calculation"}
    
    example_text = (
        "<blockquote>1+1=2</blockquote>\n\n"
        "<b>🧮 Калькулятор</b>\n\n"
        "Вы можете посчитать свои расходы или планировать покупки.\n\n"
        "Введите математическое выражение для расчета:\n"
        "<b>Поддерживаемые операции:</b>\n"
        "• <b>Сложение:</b> + (например: 100 + 50)\n"
        "• <b>Вычитание:</b> - (например: 100 - 30)\n"
        "• <b>Умножение:</b> * или × (например: 10 * 5 или 10 × 5)\n"
        "• <b>Деление:</b> / или : (например: 100 / 2 или 100 : 2)\n\n"
        "<b>Примеры:</b>\n"
        "• 45×34\n"
        "• 100+200-50\n"
        "• 1000/5*2\n"
        "• (100+200)*3"
    )
    
    await callback.message.edit_text(
        text=example_text,
        reply_markup=calculator_back_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

def calculate_expression(expression: str):
    try:
        expression = expression.replace('×', '*').replace(':', '/')
        expression = expression.replace(' ', '')
        
        allowed_chars = set('0123456789+-*/.() ')
        if not all(c in allowed_chars for c in expression):
            return None, "Недопустимые символы в выражении"
        
        result = eval(expression)
        return result, None
    except ZeroDivisionError:
        return None, "Деление на ноль невозможно"
    except Exception as e:
        return None, f"Ошибка в выражении: {str(e)}"

# ========== ПОКУПКА ЗВЕЗД ==========
@dp.callback_query(F.data == "buy_stars")
async def buy_stars_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    user_states[callback.from_user.id] = {"action": "waiting_stars_recipient"}
    
    caption = (
        "<b>⭐️ Покупка Telegram Stars</b>\n\n"
        f"<b>Курс:</b> 1 звезда = {STAR_RATE} RUB\n"
        "<b>Диапазон:</b> от 50 до 1,000,000 звезд\n\n"
        "<b>✏️ Введите username получателя (можно с @):</b>"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=back_kb("main_menu"),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_premium")
async def buy_premium_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    price_text = ""
    for key, value in PREMIUM_PRICES.items():
        price_text += f"• <b>{value['name']}:</b> {value['rub']:.2f} RUB\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 месяца", callback_data="premium_3m")],
        [InlineKeyboardButton(text="6 месяцев", callback_data="premium_6m")],
        [InlineKeyboardButton(text="1 год", callback_data="premium_1y")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    caption = (
        "<b>👑 Покупка Telegram Premium</b>\n\n"
        "<b>Выберите период:</b>\n\n"
        f"{price_text}"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("premium_"))
async def premium_period_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    period = callback.data.replace("premium_", "")
    
    if period in PREMIUM_PRICES:
        user_states[callback.from_user.id] = {
            "action": "waiting_premium_recipient",
            "period": period,
            "amount_rub": PREMIUM_PRICES[period]["rub"]
        }
        
        caption = (
            f"<b>👑 Telegram Premium - {PREMIUM_PRICES[period]['name']}</b>\n\n"
            f"<b>Цена:</b> {PREMIUM_PRICES[period]['rub']:.2f} RUB\n\n"
            "<b>✏️ Введите username получателя (можно с @):</b>"
        )
        
        await callback.message.edit_text(
            text=caption,
            reply_markup=back_kb("buy_premium"),
            parse_mode="HTML"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "exchange")
async def exchange_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    user_states[callback.from_user.id] = {"action": "waiting_exchange_amount"}
    
    caption = (
        "<b>💱 Обмен валют</b>\n\n"
        f"<b>Курс:</b> 1 USD = {USD_RATE} RUB\n\n"
        "<b>Введите сумму в рублях для обмена:</b>\n"
        "(Минимум: 100 RUB)\n\n"
        "<b>💳 Оплата только картой!</b>"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=back_kb("main_menu"),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "info")
async def info_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if not await check_subscription(user_id):
        await require_subscription(user_id, callback=callback)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Репутация", url=REPUTATION_CHANNEL)],
        [InlineKeyboardButton(text="📰 Новости", url=NEWS_CHANNEL)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    caption = "<b>📊 Информация</b>\n\n<b>Выберите раздел:</b>"
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# ========== АДМИН ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    caption = "<b>🛠️ Админ панель</b>\n\n<b>Выберите действие:</b>"
    
    await message.answer(
        text=caption,
        reply_markup=admin_menu_kb(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_bot_stats")
async def admin_bot_stats_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    users_count = db.get_users_count()
    orders_count = db.get_total_orders_count()
    active_orders = len(db.get_active_orders())
    total_revenue = db.get_total_revenue()
    
    cursor = db.conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = ?", (today,))
    today_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM orders WHERE DATE(created_at) = ?", (today,))
    today_orders = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(amount_rub) FROM orders WHERE DATE(created_at) = ? AND status IN ('confirmed', 'completed')", (today,))
    today_revenue_result = cursor.fetchone()[0]
    today_revenue = today_revenue_result if today_revenue_result else 0
    
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM orders WHERE created_at >= datetime('now', '-1 day')")
    active_last_24h = cursor.fetchone()[0]
    
    caption = (
        "<b>🤖 Статистика бота</b>\n\n"
        f"<b>👥 Всего пользователей:</b> {users_count}\n"
        f"<b>📊 Активных за 24ч:</b> {active_last_24h}\n\n"
        
        f"<b>📦 Всего заказов:</b> {orders_count}\n"
        f"<b>⏳ Активных заказов:</b> {active_orders}\n"
        f"<b>💰 Общая выручка:</b> {total_revenue:.2f} RUB\n\n"
        
        f"<b>📅 Сегодня ({today}):</b>\n"
        f"├ <b>Новых пользователей:</b> {today_users}\n"
        f"├ <b>Новых заказов:</b> {today_orders}\n"
        f"└ <b>Выручка за день:</b> {today_revenue:.2f} RUB\n\n"
        
        f"<b>📈 Средний чек:</b> {total_revenue/orders_count:.2f} RUB\n" if orders_count > 0 else ""
        f"<b>🏪 Конверсия:</b> {orders_count/users_count*100:.1f}%\n" if users_count > 0 else ""
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_bot_stats")],
        [InlineKeyboardButton(text="📦 Активные заказы", callback_data="admin_active_orders")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(Command("dbcheck"))
async def db_check_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        cursor = db.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM orders")
        orders_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT id, order_type, status, amount_rub FROM orders ORDER BY id")
        all_orders = cursor.fetchall()
        
        report = f"<b>📊 Отчет базы данных:</b>\n\n"
        report += f"<b>👥 Пользователей:</b> {users_count}\n"
        report += f"<b>📦 Всего заказов:</b> {orders_count}\n\n"
        
        if all_orders:
            report += "<b>📋 Список всех заказов:</b>\n"
            for order in all_orders:
                order_id, order_type, status, amount_rub = order
                report += f"#{order_id} | {order_type} | {status} | {amount_rub:.2f} RUB\n"
        else:
            report += "❌ <b>Заказов нет в базе</b>\n"
        
        await message.answer(report, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка БД:</b> {e}", parse_mode="HTML")

@dp.callback_query(F.data == "admin_active_orders")
async def admin_active_orders_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    orders = db.get_active_orders()
    
    if not orders:
        caption = (
            "<b>📦 Активные заказы</b>\n\n"
            "❌ <b>Нет активных заказов</b>\n\n"
            "<b>Заказы появятся здесь, когда:</b>\n"
            "• Пользователь создаст заказ\n"
            "• Пользователь отправит фото оплаты\n"
            "• Заказ не будет выполнен или отменен"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_active_orders")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ])
    else:
        caption = "<b>📦 Активные заказы</b>\n\n"
        
        keyboard_buttons = []
        
        for order in orders:
            order_id, user_id, order_type, recipient, details, amount_rub, payment_method, status, created_at = order
            
            status_emoji = {
                'pending': '⏳',
                'waiting_payment': '💳',
                'waiting_confirmation': '📸',
                'waiting_crypto': '💎',
                'confirmed': '✅'
            }.get(status, '❓')
            
            if created_at:
                if isinstance(created_at, str):
                    created_short = created_at[:16]
                else:
                    created_short = str(created_at)[:16]
            else:
                created_short = "---"
            
            caption += f"{status_emoji} <b>Заказ #{order_id}</b>\n"
            caption += f"<b>Тип:</b> {order_type}\n"
            
            try:
                details_dict = json.loads(details) if details else {}
                
                if order_type == "stars":
                    stars = details_dict.get("stars", 0)
                    caption += f"<b>Кол-во:</b> {stars} звезд\n"
                elif order_type == "premium":
                    period = details_dict.get("period", "")
                    period_name = PREMIUM_PRICES.get(period, {}).get("name", "")
                    caption += f"<b>Период:</b> {period_name}\n"
                elif order_type == "exchange":
                    amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                    caption += f"<b>К выдаче:</b> {amount_usd:.2f} USD\n"
            except:
                pass
            
            if recipient:
                caption += f"<b>👤 Получатель:</b> @{recipient}\n"  # Добавлен @ перед юзернеймом
            
            caption += f"<b>Сумма:</b> {amount_rub:.2f} RUB\n"
            caption += f"<b>Метод:</b> {payment_method}\n"
            caption += f"<b>Дата:</b> {created_short}\n"
            caption += f"<b>Статус:</b> {status}\n\n"
            
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"📦 Управление заказом #{order_id}", 
                    callback_data=f"manage_order_{order_id}"
                )
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔄 Обновить список", callback_data="admin_active_orders")
        ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin_back")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    try:
        await callback.message.edit_text(
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        await callback.message.answer(
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    await callback.answer(f"📊 Загружено {len(orders)} заказов")

@dp.callback_query(F.data.startswith("manage_order_"))
async def manage_order_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    try:
        order_id = int(callback.data.replace("manage_order_", ""))
        
        order = db.get_order(order_id)
        
        if not order:
            await callback.answer("❌ Заказ не найден")
            return
        
        user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
        
        details_dict = {}
        try:
            if details:
                details_dict = json.loads(details)
        except:
            pass
        
        photo_file_id = details_dict.get("payment_photo") if details_dict else None
        
        if photo_file_id and status in ["waiting_confirmation", "confirmed"]:
            try:
                photo_caption = f"<b>📸 Фото оплаты заказа #{order_id}</b>\n\n"
                photo_caption += f"<b>🆔 Заказ:</b> #{order_id}\n"
                photo_caption += f"<b>📦 Тип:</b> {order_type}\n"
                photo_caption += f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB"
                
                await bot.send_photo(
                    callback.message.chat.id,
                    photo=photo_file_id,
                    caption=photo_caption,
                    parse_mode="HTML"
                )
            except Exception as e:
                pass
        
        caption = f"<b>🛠️ Управление заказом #{order_id}</b>\n\n"
        
        caption += f"<b>👤 Покупатель:</b>\n"
        caption += f"   <b>ID:</b> {user_id}\n"
        
        caption += f"\n<b>📦 Детали заказа:</b>\n"
        caption += f"   <b>Тип:</b> {order_type}\n"
        
        if order_type == "stars":
            stars = details_dict.get("stars", 0)
            caption += f"   <b>⭐️ Звезд:</b> {stars}\n"
        elif order_type == "premium":
            period = details_dict.get("period", "")
            period_name = PREMIUM_PRICES.get(period, {}).get("name", "")
            caption += f"   <b>👑 Период:</b> {period_name}\n"
        elif order_type == "exchange":
            amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
            caption += f"   <b>💸 К выдаче:</b> {amount_usd:.2f} USD\n"
        
        if recipient:
            caption += f"   <b>👤 Получатель:</b> @{recipient}\n"  # Добавлен @ перед юзернеймом
        
        caption += f"   <b>💰 Сумма:</b> {amount_rub:.2f} RUB\n"
        caption += f"   <b>💳 Метод:</b> {payment_method}\n"
        caption += f"   <b>📊 Статус:</b> {status}\n"
        
        if photo_file_id:
            caption += f"   <b>📸 Фото оплаты:</b> ✅ Есть\n"
        else:
            caption += f"   <b>📸 Фото оплаты:</b> ❌ Нет\n"
        
        keyboard_buttons = []
        
        if status == "waiting_confirmation":
            keyboard_buttons.append([
                InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_payment_{order_id}")
            ])
            keyboard_buttons.append([
                InlineKeyboardButton(text="❌ Отклонить заказ", callback_data=f"admin_reject_order_{order_id}")
            ])
        
        elif status == "waiting_crypto":
            keyboard_buttons.append([
                InlineKeyboardButton(text="💎 Проверить оплату", callback_data=f"check_crypto_{order_id}")
            ])
            keyboard_buttons.append([
                InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"admin_reject_order_{order_id}")
            ])
        
        elif status == "confirmed":
            keyboard_buttons.append([
                InlineKeyboardButton(text="📦 Я передал товар", callback_data=f"admin_delivered_{order_id}")
            ])
        
        else:
            keyboard_buttons.append([
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_confirm_payment_{order_id}")
            ])
            keyboard_buttons.append([
                InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_reject_order_{order_id}")
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"manage_order_{order_id}"),
            InlineKeyboardButton(text="📦 К заказам", callback_data="admin_active_orders")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.answer(
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer("✅ Информация о заказе загружена")
        
    except ValueError as e:
        await callback.answer("❌ Ошибка: неверный ID заказа")
    except Exception as e:
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data.startswith("admin_confirm_payment_"))
async def admin_confirm_payment_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_confirm_payment_", ""))
    
    admin_confirmations[callback.from_user.id] = {
        "action": "confirm_payment",
        "order_id": order_id
    }
    
    caption = (
        f"<b>⚠️ ВНИМАНИЕ!</b>\n\n"
        f"Вы собираетесь подтвердить оплату заказа #{order_id}.\n\n"
        f"<b>Перед подтверждением проверьте:</b>\n"
        f"1. Фото оплаты соответствует сумме\n"
        f"2. Реквизиты отправителя верны\n"
        f"3. Время оплаты корректное\n\n"
        f"Если всё верно, нажмите кнопку ниже для окончательного подтверждения."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА, я всё проверил и подтверждаю", callback_data=f"admin_final_confirm_{order_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"manage_order_{order_id}")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_final_confirm_"))
async def admin_final_confirm_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_final_confirm_", ""))
    
    db.update_order_status(order_id, "confirmed")
    
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"✅ <b>Ваш заказ #{order_id} подтвержден!</b>\n\n"
                f"Товар будет отправлен в течение 15 минут - 3 часа.",
                parse_mode="HTML"
            )
        except:
            pass
    
    if callback.from_user.id in admin_confirmations:
        del admin_confirmations[callback.from_user.id]
    
    await callback.answer("✅ Заказ подтвержден!")
    await admin_active_orders_handler(callback)

@dp.callback_query(F.data.startswith("admin_reject_order_"))
async def admin_reject_order_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_reject_order_", ""))
    
    admin_confirmations[callback.from_user.id] = {
        "action": "reject_order",
        "order_id": order_id
    }
    
    caption = (
        f"<b>⚠️ ВНИМАНИЕ!</b>\n\n"
        f"Вы собираетесь отклонить заказ #{order_id}.\n\n"
        f"<b>Перед отклонением проверьте:</b>\n"
        f"1. Причина отклонения обоснована\n"
        f"2. Пользователь будет уведомлен\n"
        f"3. Деньги будут возвращены при необходимости\n\n"
        f"Если всё верно, нажмите кнопку ниже для окончательного отклонения."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ ДА, отклоняю заказ", callback_data=f"admin_final_reject_{order_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"manage_order_{order_id}")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_final_reject_"))
async def admin_final_reject_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_final_reject_", ""))
    
    db.update_order_status(order_id, "cancelled")
    
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"❌ <b>Ваш заказ #{order_id} отклонен.</b>\n\n"
                f"По вопросам обращайтесь в поддержку.",
                parse_mode="HTML"
            )
        except:
            pass
    
    if callback.from_user.id in admin_confirmations:
        del admin_confirmations[callback.from_user.id]
    
    await callback.answer("❌ Заказ отклонен")
    await admin_active_orders_handler(callback)

@dp.callback_query(F.data.startswith("admin_delivered_"))
async def admin_delivered_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_delivered_", ""))
    
    admin_confirmations[callback.from_user.id] = {
        "action": "delivered",
        "order_id": order_id
    }
    
    caption = (
        f"<b>⚠️ ПОДТВЕРЖДЕНИЕ ПЕРЕДАЧИ</b>\n\n"
        f"Вы подтверждаете, что передали товар по заказу #{order_id}?\n\n"
        f"<b>Перед подтверждением проверьте:</b>\n"
        f"1. Товар передан получателю\n"
        f"2. Получатель подтвердил получение\n"
        f"3. Всё соответствует заказу\n\n"
        f"После подтверждения заказ будет помечен как выполненный и исчезнет из списка."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА, товар передан", callback_data=f"admin_final_delivered_{order_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"manage_order_{order_id}")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_final_delivered_"))
async def admin_final_delivered_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_final_delivered_", ""))
    
    db.update_order_status(order_id, "completed")
    
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"🎉 <b>Ваш заказ #{order_id} выполнен!</b>\n\n"
                f"Спасибо за покупку! 😊",
                parse_mode="HTML"
            )
        except:
            pass
    
    if callback.from_user.id in admin_confirmations:
        del admin_confirmations[callback.from_user.id]
    
    await callback.answer("✅ Заказ выполнен!")
    await admin_active_orders_handler(callback)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    orders = db.get_active_orders()
    active_count = len(orders)
    
    caption = (
        f"<b>📊 Статистика магазина</b>\n\n"
        f"<b>📦 Активных заказов:</b> {active_count}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    caption = "<b>🛠️ Админ панель</b>\n\n<b>Выберите действие:</b>"
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=admin_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

# ========== ОБРАБОТКА ФОТО ОПЛАТЫ ==========
@dp.message(F.photo)
async def handle_payment_photo(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in user_states:
        await message.answer("Пожалуйста, используйте кнопки меню.")
        return
    
    state = user_states[user_id]
    
    if state.get("action") == "waiting_payment_photo":
        order_id = state.get("order_id")
        order = db.get_order(order_id)
        
        if not order:
            await message.answer("❌ Заказ не найден")
            return
        
        user_id_db, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
        
        photo_file_id = message.photo[-1].file_id
        
        try:
            details_dict = json.loads(details) if details else {}
            details_dict["payment_photo"] = photo_file_id
            db.add_payment_photo(order_id, photo_file_id)
        except:
            pass
        
        db.update_order_status(order_id, "waiting_confirmation")
        
        del user_states[user_id]
        
        for admin_id in ADMIN_IDS:
            try:
                photo_caption = f"<b>📸 Новое фото оплаты | Заказ #{order_id}</b>"
                
                await bot.send_photo(
                    admin_id,
                    photo=photo_file_id,
                    caption=photo_caption,
                    parse_mode="HTML"
                )
                
                admin_message = f"<b>🆕 Новый заказ ожидает проверки</b>\n\n"
                admin_message += f"<b>🆔 Заказ:</b> #{order_id}\n"
                admin_message += f"<b>👤 Пользователь:</b> {message.from_user.username or 'Нет юзернейма'}\n"
                admin_message += f"<b>🆔 ID:</b> {message.from_user.id}\n"
                admin_message += f"<b>📦 Тип:</b> {order_type}\n"
                admin_message += f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n"
                
                if order_type == "exchange":
                    try:
                        details_dict = json.loads(details) if details else {}
                        amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                        admin_message += f"<b>💸 К выдаче:</b> {amount_usd:.2f} USD\n"
                    except:
                        pass
                else:
                    admin_message += f"<b>👤 Получатель:</b> @{recipient}\n"  # Добавлен @ перед юзернеймом
                
                admin_message += f"\n<b>Для проверки зайдите в /admin → 📦 Активные заказы</b>"
                
                await bot.send_message(admin_id, admin_message, parse_mode="HTML")
                
            except Exception as e:
                pass
        
        if order_type == "exchange":
            try:
                details_dict = json.loads(details) if details else {}
                amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                user_message = (
                    f"✅ <b>Фото оплаты получено!</b>\n"
                    f"<b>💸 Вы получаете:</b> {amount_usd:.2f} USD\n"
                    f"<b>💰 Оплачено:</b> {amount_rub:.2f} RUB\n\n"
                    "Заказ передан админу на проверку.\n"
                    "После проверки USD будут отправлены вам в течение 15 минут - 3 часа."
                )
            except:
                user_message = (
                    "✅ <b>Фото оплаты получено!</b> Заказ передан админу на проверку.\n"
                    "После проверки USD будут отправлены вам в течение 15 минут - 3 часа."
                )
        else:
            user_message = (
                "✅ <b>Фото оплаты получено!</b> Заказ передан админу на проверку.\n"
                "После проверки товар будет доставлен в течение 15 минут - 3 часа."
            )
        
        await message.answer(user_message, parse_mode="HTML")
        await show_main_menu(message)

# ========== ОПЛАТА КАРТОЙ ==========
@dp.callback_query(F.data.startswith("card_pay_"))
async def card_payment_handler(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("card_pay_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    db.update_order_status(order_id, "waiting_payment")
    
    caption = (
        f"<b>💳 Оплата картой</b>\n\n"
        f"<b>🆔 Заказ:</b> #{order_id}\n"
        f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n\n"
        f"<b>Реквизиты для перевода:</b>\n"
        f"{CARD_NUMBER}\n\n"
        "<b>Инструкция:</b>\n"
        "1. Переведите точную сумму\n"
        "2. Сохраните скриншот перевода\n"
        "3. Нажмите '✅ Я оплатил'\n"
        "4. Отправьте фото оплаты\n"
        "5. Админ проверит оплату\n\n"
        "✅ После проверки товар будет доставлен в течение 15 минут - 3 часа"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=confirm_payment_kb(order_id),
        parse_mode="HTML"
    )
    await callback.answer()

# ========== ОПЛАТА CRYPTOBOT ==========
@dp.callback_query(F.data.startswith("crypto_pay_"))
async def crypto_payment_handler(callback: types.CallbackQuery):
    if not cryptobot:
        await callback.answer("❌ CryptoBot временно недоступен")
        return
    
    order_id = int(callback.data.replace("crypto_pay_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    result = await cryptobot.create_invoice(
        amount=amount_rub,
        description=f"Заказ #{order_id} | {order_type}"
    )
    
    if result["success"]:
        db.update_invoice_id(order_id, result["invoice_id"])
        db.update_order_status(order_id, "waiting_crypto")
        
        amount_usdt = amount_rub / 85.0
        
        caption = (
            f"<b>💎 Оплата через CryptoBot</b>\n\n"
            f"<b>🆔 Заказ:</b> #{order_id}\n"
            f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n"
            f"<b>💱 К оплате:</b> {amount_usdt:.2f} USDT\n\n"
            "<b>Для оплаты:</b>\n"
            "1. Нажмите кнопку ниже\n"
            "2. Оплатите счет в CryptoBot\n"
            "3. После оплаты нажмите '✅ Проверить оплату'\n\n"
            "✅ Оплата проверяется автоматически, товар доставляется в течение 15 минут - 3 часа"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оплатить в CryptoBot", url=result["pay_url"])],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_crypto_{order_id}")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(
            text=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.answer(f"❌ Ошибка: {result['error']}")
    
    await callback.answer()

# ========== ПРОВЕРКА CRYPTOBOT ОПЛАТЫ ==========
@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: types.CallbackQuery):
    if not cryptobot:
        await callback.answer("❌ CryptoBot временно недоступен")
        return
    
    order_id = int(callback.data.replace("check_crypto_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    if not invoice_id:
        await callback.answer("❌ Нет invoice_id для проверки")
        return
    
    await callback.answer("🔍 Проверяем оплату...")
    
    result = await cryptobot.check_invoice_status(invoice_id)
    
    if result["success"]:
        if result["status"] == "paid":
            db.update_order_status(order_id, "confirmed")
            
            for admin_id in ADMIN_IDS:
                try:
                    admin_message = (
                        f"<b>💎 CryptoBot оплата ПОДТВЕРЖДЕНА</b>\n\n"
                        f"<b>🆔 Заказ:</b> #{order_id}\n"
                        f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n"
                        f"<b>📦 Тип:</b> {order_type}\n"
                    )
                    
                    if order_type != "exchange":
                        admin_message += f"<b>👤 Получатель:</b> @{recipient}\n"  # Добавлен @ перед юзернеймом
                    
                    admin_message += f"\n<b>✅ Статус:</b> ОПЛАЧЕНО\n"
                    admin_message += f"<b>👨‍💼 Перейдите в админ панель для выполнения заказа</b>"
                    
                    await bot.send_message(admin_id, admin_message, parse_mode="HTML")
                except:
                    pass
            
            try:
                await bot.send_message(
                    user_id,
                    f"✅ <b>Оплата подтверждена!</b>\n\n"
                    f"<b>🆔 Ваш заказ:</b> #{order_id}\n"
                    f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n\n"
                    f"Товар будет отправлен в течение 15 минут - 3 часа!",
                    parse_mode="HTML"
                )
            except:
                pass
            
            caption = (
                f"<b>💎 Оплата подтверждена!</b>\n\n"
                f"<b>🆔 Заказ:</b> #{order_id}\n"
                f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n"
                f"<b>✅ Статус:</b> ОПЛАЧЕНО\n\n"
                f"Админ уведомлен о платеже. Товар будет отправлен в течение 15 минут - 3 часа!"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await callback.message.edit_text(
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        elif result["status"] == "active":
            await callback.answer(
                "❌ Счет не оплачен! Пожалуйста, оплатите счет в CryptoBot.",
                show_alert=True
            )
            
        elif result["status"] == "expired":
            db.update_order_status(order_id, "cancelled")
            
            caption = f"❌ <b>Счет просрочен!</b>\n\nЗаказ #{order_id} отменен."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await callback.message.edit_text(
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
    else:
        await callback.answer(
            f"❌ Ошибка проверки: {result.get('error', 'Неизвестная ошибка')}",
            show_alert=True
        )

# ========== ПОДТВЕРЖДЕНИЕ ОПЛАТЫ КАРТОЙ ==========
@dp.callback_query(F.data.startswith("confirm_paid_"))
async def confirm_card_payment(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("confirm_paid_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    user_states[callback.from_user.id] = {
        "action": "waiting_payment_photo",
        "order_id": order_id
    }
    
    await callback.message.edit_text(
        f"<b>📸 Пришлите фото/скриншот оплаты</b>\n\n"
        f"<b>🆔 Заказ:</b> #{order_id}\n"
        f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n\n"
        "Пожалуйста, отправьте скриншот перевода.\n"
        "После отправки фото заказ будет передан админу на проверку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"cancel_photo_{order_id}")]
        ]),
        parse_mode="HTML"
    )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_photo_"))
async def cancel_photo_handler(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("cancel_photo_", ""))
    
    if callback.from_user.id in user_states:
        del user_states[callback.from_user.id]
    
    await card_payment_handler(callback)

# ========== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ==========
@dp.message(F.text)
async def handle_text_messages(message: types.Message):
    if message.text.startswith('/'):
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS and not await check_subscription(user_id):
        await require_subscription(user_id, message=message)
        return
    
    if user_id in user_states and user_states[user_id].get("action") == "waiting_payment_photo":
        await message.answer("📸 Пожалуйста, отправьте фото/скриншот оплаты")
        return
    
    text = message.text.strip()
    
    if user_id not in user_states:
        await message.answer("Используйте меню", reply_markup=main_menu_kb())
        return
    
    state = user_states[user_id]
    action = state.get("action")
    
    if action == "waiting_calculation":
        result, error = calculate_expression(text)
        
        if error:
            await message.answer(
                f"❌ <b>Ошибка:</b> {error}\n\n"
                "Попробуйте ввести выражение снова:",
                reply_markup=calculator_back_kb(),
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"<blockquote>{text} = {result}</blockquote>\n\n"
                "<b>✅ Результат вычисления:</b>\n"
                f"<b>Выражение:</b> {text}\n"
                f"<b>Результат:</b> {result}\n\n"
                "Введите новое выражение для расчета или вернитесь в меню:",
                reply_markup=calculator_back_kb(),
                parse_mode="HTML"
            )
        return
    
    def is_english_username(username):
        pattern = r'^[a-zA-Z0-9_]+$'
        return bool(re.match(pattern, username))
    
    if action == "waiting_stars_recipient":
        recipient = text.strip()
        
        if recipient.startswith('@'):
            recipient = recipient[1:]
            
        if not recipient:
            await message.answer("❌ Введите username получателя (можно с @)")
            return
        
        if not is_english_username(recipient):
            await message.answer(
                "❌ <b>Пожалуйста, укажите юзернейм на английском языке.</b>\n\n"
                "Юзернейм должен содержать только:\n"
                "• Латинские буквы (a-z, A-Z)\n"
                "• Цифры (0-9)\n"
                "• Нижнее подчеркивание (_)\n\n"
                "Пример: @username123 или user_name",
                parse_mode="HTML"
            )
            return
        
        state["recipient"] = recipient
        state["action"] = "waiting_stars_amount"
        
        await message.answer(
            f"✅ <b>Получатель:</b> @{recipient}\n\n"
            "<b>Теперь введите количество звезд (от 50 до 1,000,000):</b>",
            reply_markup=back_kb("buy_stars"),
            parse_mode="HTML"
        )
    
    elif action == "waiting_stars_amount":
        try:
            stars = int(text)
            if stars < 50 or stars > 1000000:
                await message.answer("❌ Количество звезд должно быть от 50 до 1,000,000")
                return
            
            amount_rub = stars * STAR_RATE
            recipient = state.get("recipient", "")
            
            state["stars_amount"] = stars
            state["amount_rub"] = amount_rub
            
            order_id = db.add_order(
                user_id, "stars", recipient, 
                json.dumps({"stars": stars}), 
                amount_rub, "card"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перевод на карту", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_stars")]
            ])
            
            if cryptobot:
                keyboard.inline_keyboard.insert(0, [
                    InlineKeyboardButton(text="💎 CryptoBot", callback_data=f"crypto_pay_{order_id}")
                ])
            
            await message.answer(
                f"✅ <b>{stars} звезд для @{recipient}</b>\n"
                f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n\n"
                "<b>Выберите способ оплаты:</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        except ValueError:
            await message.answer("❌ Пожалуйста, введите число")
    
    elif action == "waiting_premium_recipient":
        recipient = text.strip()
        
        if recipient.startswith('@'):
            recipient = recipient[1:]
            
        if not is_english_username(recipient):
            await message.answer(
                "❌ <b>Пожалуйста, укажите юзернейм на английском языке.</b>\n\n"
                "Юзернейм должен содержать только:\n"
                "• Латинские буквы (a-z, A-Z)\n"
                "• Цифры (0-9)\n"
                "• Нижнее подчеркивание (_)\n\n"
                "Пример: @username123 или user_name",
                parse_mode="HTML"
            )
            return
            
        period = state.get("period")
        amount_rub = state.get("amount_rub")
        
        if period and amount_rub:
            state["recipient"] = recipient
            
            order_id = db.add_order(
                user_id, "premium", recipient,
                json.dumps({"period": period}),
                amount_rub, "card"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перевод на карту", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_premium")]
            ])
            
            if cryptobot:
                keyboard.inline_keyboard.insert(0, [
                    InlineKeyboardButton(text="💎 CryptoBot", callback_data=f"crypto_pay_{order_id}")
                ])
            
            await message.answer(
                f"✅ <b>{PREMIUM_PRICES[period]['name']} для @{recipient}</b>\n"
                f"<b>💰 Сумма:</b> {amount_rub:.2f} RUB\n\n"
                "<b>Выберите способ оплаты:</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    
    elif action == "waiting_exchange_amount":
        try:
            amount_rub = float(text)
            if amount_rub < 100:
                await message.answer("❌ Минимальная сумма: 100 RUB")
                return
            
            amount_usd = amount_rub / USD_RATE
            
            order_id = db.add_order(
                user_id, "exchange", "",
                json.dumps({
                    "amount_rub": amount_rub, 
                    "amount_usd": amount_usd,
                    "exchange_rate": USD_RATE
                }),
                amount_rub, "card"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить картой", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="exchange")]
            ])
            
            await message.answer(
                f"✅ <b>Обмен валют</b>\n"
                f"<b>📊 Курс:</b> 1 USD = {USD_RATE} RUB\n"
                f"<b>💸 Вы получаете:</b> {amount_usd:.2f} USD\n"
                f"<b>💰 К оплате:</b> {amount_rub:.2f} RUB\n\n"
                "<b>💳 Оплата только картой!</b>\n"
                "После оплаты пришлите скриншот перевода.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        except ValueError:
            await message.answer("❌ Пожалуйста, введите число")

# ========== ЗАПУСК БОТА ==========
async def main():
    print("=" * 50)
    print("🚀 Digi Store Bot запускается...")
    print("=" * 50)
    
    if not BOT_TOKEN:
        print("❌ ОШИБКА: BOT_TOKEN не найден!")
        print("ℹ️  Установите переменную окружения BOT_TOKEN")
        exit(1)
    
    print(f"🤖 Бот: ✅ Настроен")
    print(f"👑 Админ ID: {ADMIN_IDS}")
    print(f"💎 CryptoBot: {'✅ Настроен' if CRYPTOBOT_TOKEN else '❌ Нет токена'}")
    print(f"💳 Карта: {CARD_NUMBER}")
    print(f"🆘 Тех поддержка: @{SUPPORT_USER}")
    print(f"📢 Канал: @{CHANNEL_USERNAME} (ID: {CHANNEL_ID})")
    print("=" * 50)
    
    await setup_menu_button()
    
    print("✅ Menu button настроен с командой /start")
    print("🔵 Рядом с чатом будет синяя кнопка с командой /start")
    print("=" * 50)
    print("✅ Бот готов к работе")
    print("ℹ️  Проверка подписки на канал: АКТИВНА")
    print("ℹ️  Админ панель с статистикой: АКТИВНА")
    print("ℹ️  Текст главного меню в цитате: АКТИВНО")
    print("ℹ️  Юзернеймы с @ в админ панели: АКТИВНО")
    print("=" * 50)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())