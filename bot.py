import logging
import re
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
import sqlite3
import random
import traceback
import asyncio
from typing import List, Optional, Tuple
from dotenv import load_dotenv  # Новое: для загрузки переменных окружения

# Загружаем переменные окружения из .env файла
load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Читаем токен из переменных окружения
ADMIN_ID = 1034932955  # Главный админ
TEAM_CHAT_ID = -1003399713075  # ID форума/чата для подсчета участников
TEAM_CHANNEL_URL = "https://t.me/bogat_v_vorke"
TEAM_NAME = "Gods Team"

# Настройки кошелька
WALLET_MIN_LENGTH = 10
WALLET_MAX_LENGTH = 100

# Настройки выплат
MAX_WITHDRAWAL = 10000.0

# Проценты по умолчанию
DEFAULT_WORKER_PERCENT = 60
PRICE_NFT_BOT = "@PriceNFTbot"

# Путь к фото для главного меню - изменено на относительный путь
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_MENU_PHOTO_PATH = os.path.join(BASE_DIR, "assets", "photo1.jpg")

# Создайте папку assets если её нет
if not os.path.exists(os.path.join(BASE_DIR, "assets")):
    os.makedirs(os.path.join(BASE_DIR, "assets"))
    print(f"📁 Создана папка assets в {BASE_DIR}")

# Курс TON к USD (примерный) и RUB
TON_TO_USD_RATE = 1.44
TON_TO_RUB_RATE = 108.0  # Примерный курс TON к RUB

# ==================== НАСТРОЙКА ЛОГГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Проверка наличия токена
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден. Убедитесь, что он указан в .env файле")
    exit(1)

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=storage)

# ==================== БАЗА ДАННЫХ ====================
from database import Database
db = Database()

# ==================== СОСТОЯНИЯ FSM ====================
class UserStates(StatesGroup):
    # Состояния для добавления кошелька
    waiting_for_wallet = State()
    
    # Состояния для создания заявки
    waiting_for_wallet_selection = State()
    waiting_for_direction = State()
    waiting_for_gift_url = State()
    waiting_for_proofs = State()

class AdminStates(StatesGroup):
    waiting_for_reject_reason = State()
    waiting_for_payment_proof = State()
    waiting_for_percent_update = State()
    waiting_for_user_id_for_percent = State()
    waiting_for_user_id_for_balance = State()
    waiting_for_admin_username = State()
    waiting_for_broadcast_message = State()
    waiting_for_user_id_for_block = State()
    waiting_for_private_message = State()
    waiting_for_amount_setting = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def validate_wallet(wallet: str) -> bool:
    if len(wallet) < WALLET_MIN_LENGTH or len(wallet) > WALLET_MAX_LENGTH:
        return False
    
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', wallet):
        return False
    
    return True

def format_ton_to_usd(ton_amount):
    usd_amount = ton_amount * TON_TO_USD_RATE
    return f"${usd_amount:.2f}"

def format_ton_to_rub(ton_amount):
    rub_amount = ton_amount * TON_TO_RUB_RATE
    return f"{rub_amount:.2f} RUB"

def calculate_contribution_to_total(user_total, team_total):
    """Рассчитывает вклад пользователя в общую кассу"""
    if team_total == 0:
        return "0.0%"
    contribution = (user_total / team_total) * 100
    return f"{contribution:.1f}%"

def format_user_profile(user_id, user_data, user_stats):
    """Форматирует профиль пользователя с новой структурой"""
    if not user_data:
        return "Профиль не найден"
    
    (username, first_name, last_name, total_earned, team_count, 
     worker_percent, is_active, hide_from_top, days_in_team, profits_count) = user_data
    
    # Получаем статистику профитов
    if user_stats:
        total_earned_ton, total_profits, avg_profit, max_profit, \
        week_profit, month_profit, half_year_profit = user_stats
    else:
        total_earned_ton = total_earned
        total_profits = profits_count
        avg_profit = max_profit = week_profit = month_profit = half_year_profit = 0
    
    rank = db.get_user_rank(user_id)
    rank_display = f"#{rank}" if rank > 0 else "Нет"
    
    # Получаем активный кошелек
    active_wallet = db.get_active_wallet(user_id)
    wallet_display = "⛔️ Не привязан" if not active_wallet else f"✅ {active_wallet[0]} ({active_wallet[1]})"
    
    # Получаем самое частое направление
    most_common_direction = db.get_most_common_direction(user_id)
    direction_info = f"<b>🎯 Частое направление:</b> <code>{most_common_direction or 'Нет данных'}</code>\n\n" if most_common_direction else ""
    
    # Рассчитываем вклад в общую кассу
    team_stats = db.get_real_team_stats()
    team_total = team_stats[0] if team_stats else 0
    contribution = calculate_contribution_to_total(total_earned_ton, team_total)
    
    # Форматируем профиль
    profile = (
        f"<b>📋 ИНФОРМАЦИЯ О ПРОФИЛЕ</b>\n\n"
        f"{direction_info}"
        f"<b>🆔 ID:</b> <code>{user_id}</code>\n"
        f"<b>👤 Имя:</b> <i>{first_name} {last_name or ''}</i>\n"
        f"<b>📊 Процент:</b> <code>{worker_percent}%</code>\n\n"
        f"<b>📈 ПРОФИТЫ:</b>\n"
        f"Всего <b>{total_profits}</b> профитов на сумму {format_ton_to_rub(total_earned_ton)}\n"
        f"├ Средний — {format_ton_to_rub(avg_profit)}\n"
        f"├ Рекордный — {format_ton_to_rub(max_profit)}\n"
        f"├ За 7 дней — {format_ton_to_rub(week_profit)}\n"
        f"├ За 30 дней — {format_ton_to_rub(month_profit)}\n"
        f"├ За 180 дней — {format_ton_to_rub(half_year_profit)}\n"
        f"├ Ваше место в ТОПе — {rank_display}\n"
        f"└ Вклад в общую кассу ≈ {contribution}\n\n"
        f"<b>ℹ️ ИНФОРМАЦИЯ:</b>\n"
        f"• <b>В тиме:</b> {days_in_team}д\n"
        f"<b>💳 АКТИВНЫЙ КОШЕЛЕК:</b>\n"
        f"<code>{wallet_display}</code>"
    )
    return profile

def is_admin(user_id):
    return db.is_admin(user_id)

def format_username_for_top(username):
    if not username:
        return "***"
    
    if len(username) <= 5:
        return username
    else:
        visible = username[:3]
        hidden = "*" * (len(username) - 3)
        return f"{visible}{hidden}"

def format_name_for_top(name):
    if not name or name == "None":
        return "Имя скрыто"
    return name

async def send_message_with_photo(chat_id, text, reply_markup=None):
    """Универсальная функция отправки сообщения с фото"""
    try:
        if os.path.exists(MAIN_MENU_PHOTO_PATH):
            with open(MAIN_MENU_PHOTO_PATH, 'rb') as photo:
                return await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup
                )
        else:
            logger.warning(f"Фото не найдено: {MAIN_MENU_PHOTO_PATH}. Отправляю сообщение без фото.")
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup
        )

def get_back_to_main_keyboard():
    """Клавиатура для возврата в главное меню"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔙 В главное меню"))
    return markup

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    markup.add(types.KeyboardButton("📝 Создать заявку"))
    
    markup.row(
        types.KeyboardButton("👤 Профиль"),
        types.KeyboardButton("📋 Мои заявки")
    )
    markup.row(
        types.KeyboardButton("🏆 Топ воркеров"),
        types.KeyboardButton("ℹ️ Информация")
    )
    
    if user_id and is_admin(user_id):
        markup.add(types.KeyboardButton("👑 Админ панель"))
    
    return markup

def get_profile_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    user_wallets = db.get_user_wallets(user_id)
    has_wallets = len(user_wallets) > 0
    
    markup.add(types.InlineKeyboardButton("💳 Добавить кошелек", callback_data="add_wallet"))
    
    if has_wallets:
        markup.add(types.InlineKeyboardButton("📋 Мои кошельки", callback_data="my_wallets"))
    
    user_data = db.get_user_stats(user_id)
    if user_data:
        hide_from_top = user_data[7]
        hide_text = "👁️‍🗨️ Показать в топе" if hide_from_top else "👁️ Скрыть из топа"
        markup.add(types.InlineKeyboardButton(hide_text, callback_data="toggle_hide_top"))
    
    return markup

def get_info_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.add(
        types.InlineKeyboardButton("👥 Наша тима", url=TEAM_CHANNEL_URL),
        types.InlineKeyboardButton("💬 Обратная связь", callback_data="feedback")
    )
    markup.add(
        types.InlineKeyboardButton("🤖 Бот для трафферов", callback_data="traffer_bot"),
        types.InlineKeyboardButton("📰 Новости", callback_data="news")
    )
    markup.add(
        types.InlineKeyboardButton("📊 Статистика проекта", callback_data="project_stats"),
        types.InlineKeyboardButton("📚 Мануалы", callback_data="manuals")
    )
    markup.add(
        types.InlineKeyboardButton("🤵 Администрация", callback_data="administration")
    )
    
    return markup

def get_cancel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Отмена"), types.KeyboardButton("🔙 В главное меню"))
    return markup

def get_wallets_keyboard(wallets, is_for_request=True):
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for wallet_id, address, wallet_type, is_active, created_at in wallets:
        active_indicator = "✅ " if is_active else ""
        btn_text = f"{active_indicator}{address[:15]}... ({wallet_type})"
        if is_for_request:
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"select_wallet_for_request_{wallet_id}"))
        else:
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"select_wallet_{wallet_id}"))
    
    markup.add(types.InlineKeyboardButton("➕ Добавить новый кошелек", callback_data="add_new_wallet"))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_request"))
    return markup

def get_direction_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🎯 Dr@iner", callback_data="direction_drainer"),
        types.InlineKeyboardButton("💎 OTC Bot", callback_data="direction_otc"),
        types.InlineKeyboardButton("🌈 Nicegram", callback_data="direction_nicegram")
    )
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_request"))
    return markup

def get_admin_withdrawal_keyboard(withdrawal_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Указать сумму", callback_data=f"set_amount_{withdrawal_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{withdrawal_id}")
    )
    return markup

def get_admin_withdrawal_after_amount_keyboard(withdrawal_id):
    """Клавиатура после установки суммы - для подтверждения выплаты"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить выплату", callback_data=f"approve_{withdrawal_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{withdrawal_id}")
    )
    return markup

def get_admin_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("📋 Ожидающие заявки")
    )
    markup.add(
        types.KeyboardButton("👥 Все пользователи"),
        types.KeyboardButton("✏️ Изменить %")
    )
    markup.add(
        types.KeyboardButton("📢 Рассылка"),
        types.KeyboardButton("🔒 Блокировка")
    )
    markup.add(
        types.KeyboardButton("👑 Управление админами"),
        types.KeyboardButton("📨 Личное сообщение")
    )
    markup.add(
        types.KeyboardButton("🔙 В главное меню")
    )
    return markup

def get_admin_management_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("➕ Добавить админа"),
        types.KeyboardButton("➖ Удалить админа")
    )
    markup.add(
        types.KeyboardButton("📋 Список админов"),
        types.KeyboardButton("🔙 В админ меню")
    )
    return markup

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Проверяем заблокирован ли пользователь
    if db.is_user_blocked(user_id):
        await send_message_with_photo(
            user_id,
            "<b>🚫 Доступ запрещен!</b>\n\n"
            "<i>Ваш аккаунт заблокирован в системе.</i>"
        )
        return
    
    # Получаем или создаем пользователя с обновленным временем в тиме
    db.create_or_update_user(user_id, username, first_name, last_name)
    
    welcome_text = (
        f"<b>👋 Добро пожаловать в {TEAM_NAME}!</b>\n\n"
        f"<i>Твоя команда для заработка на мамонтах!</i>\n\n"
        f"<b>🏠 Главное меню</b>\n"
        f"Выберите действие:"
    )
    
    await send_message_with_photo(user_id, welcome_text, get_main_keyboard(user_id))

@dp.message_handler(lambda message: message.text == "🔙 В главное меню")
async def back_to_main_menu_handler(message: types.Message):
    """Обработчик кнопки возврата в главное меню"""
    user_id = message.from_user.id
    state = dp.current_state(chat=user_id, user=user_id)
    
    # Завершаем любое активное состояние
    try:
        await state.finish()
    except:
        pass
    
    # Всегда возвращаем в главное меню
    await send_message_with_photo(
        user_id,
        "<b>🏠 Главное меню</b>\n\n<i>Выберите действие:</i>",
        get_main_keyboard(user_id)
    )

@dp.message_handler(lambda message: message.text == "👑 Админ панель")
async def admin_panel_handler(message: types.Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    admin_text = (
        "<b>👑 ПАНЕЛЬ АДМИНИСТРАТОРА</b>\n\n"
        "<i>Доступные функции:</i>\n"
        "• <b>📊 Статистика</b> - общая информация\n"
        "• <b>📋 Ожидающие заявки</b> - список заявок на вывод\n"
        "• <b>👥 Все пользователи</b> - список всех воркеров\n"
        "• <b>✏️ Изменить %</b> - изменить процент воркеру\n"
        "• <b>📢 Рассылка</b> - отправить сообщение всем\n"
        "• <b>🔒 Блокировка</b> - заблокировать пользователя\n"
        "• <b>👑 Управление админами</b> - добавить/удалить админа\n"
        "• <b>📨 Личное сообщение</b> - отправить сообщение конкретному пользователю"
    )
    await send_message_with_photo(user_id, admin_text, get_admin_menu_keyboard())

# ==================== ОСНОВНЫЕ КНОПКИ ====================
@dp.message_handler(lambda message: message.text == "👤 Профиль")
async def profile_handler(message: types.Message):
    user_id = message.from_user.id
    user_data = db.get_user_stats(user_id)
    
    if user_data:
        # Получаем расширенную статистику профитов
        user_profit_stats = db.get_user_profit_stats(user_id)
        
        profile_text = format_user_profile(user_id, user_data, user_profit_stats)
        await send_message_with_photo(user_id, profile_text, get_profile_keyboard(user_id))
    else:
        await send_message_with_photo(user_id, "<b>❌ Ваш профиль не найден. Нажмите /start</b>")

# ==================== РАБОТА С КОШЕЛЬКАМИ ====================
@dp.callback_query_handler(lambda call: call.data == "add_wallet")
async def add_wallet_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    
    await call.answer()
    await bot.send_message(
        chat_id=user_id,
        text=(
            "<b>💳 ДОБАВЛЕНИЕ КОШЕЛЬКА</b>\n\n"
            "<i>Введите адрес вашего кошелька TON:</i>"
        ),
        reply_markup=get_cancel_keyboard()
    )
    await UserStates.waiting_for_wallet.set()

@dp.callback_query_handler(lambda call: call.data == "my_wallets")
async def my_wallets_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    wallets = db.get_user_wallets(user_id)
    
    if not wallets:
        await call.answer("У вас нет привязанных кошельков")
        return
    
    response = "<b>💳 ВАШИ КОШЕЛЬКИ:</b>\n\n"
    
    for wallet_id, address, wallet_type, is_active, created_at in wallets:
        active_status = "✅ АКТИВНЫЙ" if is_active else "❌ НЕАКТИВНЫЙ"
        response += (
            f"<b>🔸 Кошелек #{wallet_id}</b>\n"
            f"<b>💳 Адрес:</b> <code>{address}</code>\n"
            f"<b>📋 Тип:</b> <code>{wallet_type}</code>\n"
            f"<b>📊 Статус:</b> {active_status}\n"
            f"<b>📅 Добавлен:</b> <code>{created_at}</code>\n\n"
        )
    
    await call.answer()
    await send_message_with_photo(user_id, response, get_wallets_keyboard(wallets, is_for_request=False))

@dp.callback_query_handler(lambda call: call.data.startswith("select_wallet_"))
async def select_wallet_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    
    if call.data.startswith("select_wallet_"):
        wallet_id = int(call.data.split("_")[2])
        
        if db.set_active_wallet(user_id, wallet_id):
            await call.answer("✅ Кошелек выбран как активный")
            
            # Обновляем сообщение профиля
            user_data = db.get_user_stats(user_id)
            if user_data:
                user_profit_stats = db.get_user_profit_stats(user_id)
                profile_text = format_user_profile(user_id, user_data, user_profit_stats)
                try:
                    await bot.edit_message_caption(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        caption=profile_text,
                        reply_markup=get_profile_keyboard(user_id)
                    )
                except:
                    pass

@dp.callback_query_handler(lambda call: call.data == "cancel_wallet_add")
async def cancel_wallet_add_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    state = dp.current_state(chat=user_id, user=user_id)
    await state.finish()
    
    await call.answer("❌ Добавление кошелька отменено")
    await send_message_with_photo(user_id, "<b>❌ Добавление кошелька отменено</b>", get_main_keyboard(user_id))

@dp.message_handler(state=UserStates.waiting_for_wallet)
async def process_wallet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text == "❌ Отмена":
        await state.finish()
        await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_main_keyboard(user_id))
        return
    
    if message.text == "🔙 В главное меню":
        await state.finish()
        await back_to_main_menu_handler(message)
        return
    
    wallet = message.text.strip()
    
    if not validate_wallet(wallet):
        await message.answer(
            f"<b>❌ НЕВЕРНЫЙ ФОРМАТ КОШЕЛЬКА!</b>\n\n"
            f"<i>Требования:</i>\n"
            f"• Длина от {WALLET_MIN_LENGTH} до {WALLET_MAX_LENGTH} символов\n"
            f"• Только буквы, цифры и символы: _ - .\n\n"
            f"<b>Введите корректный адрес кошелька:</b>",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Сохраняем кошелек с типом "TON Wallet"
    wallet_type = "TON Wallet"
    
    # Проверяем, откуда пришел запрос - из профиля или из создания заявки
    data = await state.get_data()
    
    # Добавляем кошелек в базу
    db.add_wallet(user_id, wallet, wallet_type)
    
    if 'creating_request' in data:
        # Это добавление кошелька в процессе создания заявки
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"<b>✅ КОШЕЛЕК УСПЕШНО ДОБАВЛЕН!</b>\n\n"
                f"<b>💳 Адрес:</b> <code>{wallet}</code>\n"
                f"<b>📋 Тип:</b> <code>{wallet_type}</code>\n\n"
                f"<i>Теперь выберите направление для заявки:</i>"
            ),
            reply_markup=get_direction_keyboard()
        )
        
        # Сохраняем данные о кошельке в состоянии для использования в заявке
        await state.update_data({
            'selected_wallet_address': wallet,
            'selected_wallet_type': wallet_type,
            'selected_wallet_id': None
        })
        
        # Переходим к выбору направления
        await UserStates.waiting_for_direction.set()
    else:
        # Это обычное добавление кошелька из профиля
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"<b>✅ КОШЕЛЕК УСПЕШНО ДОБАВЛЕН!</b>\n\n"
                f"<b>💳 Адрес:</b> <code>{wallet}</code>\n"
                f"<b>📋 Тип:</b> <code>{wallet_type}</code>\n\n"
                f"<i>Теперь вы можете использовать его для выводов.</i>"
            ),
            reply_markup=get_main_keyboard(user_id)
        )
        
        # Отправляем уведомление админу
        admin_text = (
            f"<b>🔔 НОВЫЙ ДОБАВЛЕННЫЙ КОШЕЛЕК</b>\n\n"
            f"<b>👤 Воркер:</b> @{message.from_user.username or 'нет'}\n"
            f"<b>📛 Имя:</b> {message.from_user.first_name}\n"
            f"<b>💳 Кошелек:</b> <code>{wallet}</code>\n"
        )
        # Отправляем всем админам
        admins = db.get_all_admins()
        for admin_id in admins:
            if admin_id != ADMIN_ID:
                try:
                    await bot.send_message(admin_id, admin_text)
                except:
                    pass
    
    await state.finish()

@dp.callback_query_handler(lambda call: call.data == "toggle_hide_top")
async def toggle_hide_top_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    is_hidden = db.toggle_hide_from_top(user_id)
    
    status = "скрыты" if is_hidden else "показаны"
    await call.answer(f"✅ Вы {status} в топе")
    
    user_data = db.get_user_stats(user_id)
    if user_data:
        user_profit_stats = db.get_user_profit_stats(user_id)
        profile_text = format_user_profile(user_id, user_data, user_profit_stats)
        try:
            await bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=profile_text,
                reply_markup=get_profile_keyboard(user_id)
            )
        except Exception as e:
            logger.error(f"Ошибка редактирования сообщения: {e}")

# ==================== СОЗДАНИЕ ЗАЯВКИ ====================
@dp.message_handler(lambda message: message.text == "📝 Создать заявку")
async def create_request_handler(message: types.Message):
    user_id = message.from_user.id
    user_data = db.get_user_stats(user_id)
    
    if not user_data:
        await send_message_with_photo(user_id, "<b>❌ Ваш профиль не найден. Нажмите /start</b>")
        return
    
    # Проверяем наличие кошельков
    wallets = db.get_user_wallets(user_id)
    
    if not wallets:
        # Нет кошельков - предлагаем добавить
        state = dp.current_state(chat=user_id, user=user_id)
        await state.update_data({'creating_request': True})
        
        await bot.send_message(
            chat_id=user_id,
            text=(
                "<b>💳 НЕТ ПРИВЯЗАННЫХ КОШЕЛЬКОВ</b>\n\n"
                "<i>Для создания заявки необходимо добавить хотя бы один кошелек.</i>\n\n"
                "<b>Введите адрес вашего кошелька TON:</b>"
            ),
            reply_markup=get_cancel_keyboard()
        )
        await UserStates.waiting_for_wallet.set()
    else:
        # Есть кошельки - предлагаем выбрать
        response = "<b>💳 ВЫБЕРИТЕ КОШЕЛЕК ДЛЯ ВЫВОДА:</b>\n\n"
        response += "<i>Выберите кошелек из списка ниже:</i>"
        
        await send_message_with_photo(user_id, response, get_wallets_keyboard(wallets, is_for_request=True))
        await UserStates.waiting_for_wallet_selection.set()

@dp.callback_query_handler(lambda call: call.data == "add_new_wallet")
async def add_new_wallet_during_request(call: types.CallbackQuery):
    user_id = call.from_user.id
    state = dp.current_state(chat=user_id, user=user_id)
    
    await state.update_data({'creating_request': True})
    
    await call.answer()
    await bot.send_message(
        chat_id=user_id,
        text=(
            "<b>💳 ДОБАВЛЕНИЕ КОШЕЛЬКА</b>\n\n"
            "<i>Введите адрес вашего кошелька TON:</i>"
        ),
        reply_markup=get_cancel_keyboard()
    )
    await UserStates.waiting_for_wallet.set()

@dp.callback_query_handler(lambda call: call.data == "cancel_request")
async def cancel_request_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    state = dp.current_state(chat=user_id, user=user_id)
    await state.finish()
    
    await call.answer("❌ Действие отменено")
    await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_main_keyboard(user_id))

@dp.callback_query_handler(lambda call: call.data.startswith("select_wallet_for_request_"), state=UserStates.waiting_for_wallet_selection)
async def process_wallet_selection_for_request(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    
    wallet_id = int(call.data.split("_")[4])
    
    # Получаем информацию о кошельке
    wallets = db.get_user_wallets(user_id)
    selected_wallet = None
    for w_id, address, wallet_type, is_active, created_at in wallets:
        if w_id == wallet_id:
            selected_wallet = (address, wallet_type, wallet_id)
            break
    
    if not selected_wallet:
        await call.answer("❌ Кошелек не найден")
        return
    
    await call.answer()
    
    # Сохраняем выбранный кошелек в состоянии
    await state.update_data({
        'selected_wallet_address': selected_wallet[0],
        'selected_wallet_type': selected_wallet[1],
        'selected_wallet_id': selected_wallet[2]
    })
    
    await bot.send_message(
        chat_id=user_id,
        text=(
            "<b>🎯 ВЫБЕРИТЕ НАПРАВЛЕНИЕ:</b>\n\n"
            "<i>На что вы заскамили мамонта?</i>"
        ),
        reply_markup=get_direction_keyboard()
    )
    await UserStates.waiting_for_direction.set()

@dp.callback_query_handler(state=UserStates.waiting_for_direction)
async def process_direction(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    
    if call.data == "cancel_request":
        await state.finish()
        await call.answer("❌ Действие отменено")
        await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_main_keyboard(user_id))
        return
    
    if not call.data.startswith('direction_'):
        return
    
    direction_types = {
        'direction_drainer': 'Dr@iner',
        'direction_otc': 'OTC Bot',
        'direction_nicegram': 'Nicegram'
    }
    
    direction = direction_types.get(call.data)
    
    # Получаем данные из состояния
    data = await state.get_data()
    wallet_address = data.get('selected_wallet_address')
    wallet_type = data.get('selected_wallet_type')
    
    if not wallet_address or not wallet_type:
        await call.answer("❌ Ошибка: данные кошелька не найдены")
        await state.finish()
        return
    
    # Сохраняем направление в состоянии
    await state.update_data({'selected_direction': direction})
    
    user_data = db.get_user_stats(user_id)
    worker_percent = user_data[5]
    
    instruction = (
        f"<b>📝 СОЗДАНИЕ ЗАЯВКИ НА ВЫВОД</b>\n\n"
        f"<b>📊 Ваш процент:</b> <code>{worker_percent}%</code>\n"
        f"<b>💳 Кошелек:</b> <code>{wallet_address}</code>\n"
        f"<b>🎯 Направление:</b> <code>{direction}</code>\n\n"
        f"<b>🔗 Введите ссылку на гифты:</b>\n"
        f"<i>Ссылка на гифт/гифты, на которые вы заскамили мамонта</i>"
    )
    
    await call.answer()
    await bot.send_message(
        chat_id=user_id,
        text=instruction,
        reply_markup=get_cancel_keyboard()
    )
    await UserStates.waiting_for_gift_url.set()

@dp.message_handler(state=UserStates.waiting_for_gift_url)
async def process_gift_url(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text == "❌ Отмена":
        await state.finish()
        await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_main_keyboard(user_id))
        return
    
    if message.text == "🔙 В главное меню":
        await state.finish()
        await back_to_main_menu_handler(message)
        return
    
    gift_url = message.text.strip()
    
    # Простая проверка на ссылку
    if not gift_url.startswith(('http://', 'https://', 't.me/', '@')):
        await message.answer(
            "<b>❌ Некорректная ссылка!</b>\n\n"
            "<i>Пожалуйста, введите корректную ссылку на гифты.</i>",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    wallet_address = data.get('selected_wallet_address')
    wallet_type = data.get('selected_wallet_type')
    direction = data.get('selected_direction')
    
    if not all([wallet_address, wallet_type, direction]):
        await message.answer("<b>❌ Ошибка: данные заявки неполные</b>")
        await state.finish()
        return
    
    user_data = db.get_user_stats(user_id)
    worker_percent = user_data[5]
    
    # Сохраняем ссылку на гифты
    await state.update_data({
        'gift_url': gift_url,
        'worker_percent': worker_percent,
        'wallet_address': wallet_address,
        'wallet_type': wallet_type,
        'direction': direction
    })
    
    # Запрашиваем пруфы
    proof_text = (
        f"<b>📎 ПРИКРЕПИТЕ ПРУФЫ ПРОФИТА</b>\n\n"
        f"<b>🔗 Ссылка на гифты:</b> <code>{gift_url}</code>\n"
        f"<b>🎯 Направление:</b> <code>{direction}</code>\n\n"
        f"<i>Отправьте пруфы в виде:</i>\n"
        f"• ID мамонта\n"
        f"• Скрины переписки\n"
        f"• Фото/видео передачи подарка\n"
        f"• Другие доказательства профита\n\n"
        f"<b>Можно отправить несколько файлов.</b>\n"
        f"<b>После отправки пруфов нажмите</b> <code>✅ Готово</code>"
    )
    
    # Сохраняем временные данные
    await state.update_data({'proofs': []})
    
    await message.answer(
        proof_text,
        reply_markup=types.ReplyKeyboardMarkup(
            resize_keyboard=True,
            keyboard=[
                [types.KeyboardButton("✅ Готово")],
                [types.KeyboardButton("❌ Отмена"), types.KeyboardButton("🔙 В главное меню")]
            ]
        )
    )
    await UserStates.waiting_for_proofs.set()

@dp.message_handler(state=UserStates.waiting_for_proofs, content_types=types.ContentType.ANY)
async def process_proofs(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text == "❌ Отмена":
        await state.finish()
        await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_main_keyboard(user_id))
        return
    
    if message.text == "🔙 В главное меню":
        await state.finish()
        await back_to_main_menu_handler(message)
        return
    
    if message.text == "✅ Готово":
        # Получаем данные из состояния
        data = await state.get_data()
        proofs = data.get('proofs', [])
        gift_url = data.get('gift_url')
        wallet_address = data.get('wallet_address')
        wallet_type = data.get('wallet_type')
        direction = data.get('direction')
        worker_percent = data.get('worker_percent')
        
        if not proofs:
            await message.answer("<b>❌ Вы не прикрепили ни одного пруфа</b>")
            return
        
        # Создаем заявку в базе данных с суммой 0 (админ установит позже)
        withdrawal_id = db.create_withdrawal_with_url(
            user_id, 0, wallet_address, wallet_type, direction, gift_url, worker_percent
        )
        
        if withdrawal_id:
            logger.info(f"Создана заявка #{withdrawal_id} для пользователя {user_id} с ссылкой на гифты")
            
            # Сохраняем пруфы в базу данных
            for proof in proofs:
                db.add_proof_image(withdrawal_id, proof.get('file_id'), proof.get('file_type'))
            
            worker_text = (
                f"<b>✅ ЗАЯВКА НА ВЫВОД СОЗДАНА!</b>\n\n"
                f"<b>📋 Номер:</b> <code>#{withdrawal_id}</code>\n"
                f"<b>🔗 Ссылка на гифты:</b> <code>{gift_url}</code>\n"
                f"<b>🎯 Направление:</b> <code>{direction}</code>\n"
                f"<b>📊 Ваш процент:</b> <code>{worker_percent}%</code>\n"
                f"<b>💳 Кошелек:</b> <code>{wallet_address}</code>\n"
                f"<b>📎 Пруфов прикреплено:</b> {len(proofs)}\n\n"
                f"<i>⏳ Статус: Ожидание оценки админом</i>\n"
                f"<i>💰 Сумма профита будет установлена админом</i>"
            )
            await send_message_with_photo(user_id, worker_text, get_main_keyboard(user_id))
            
            # Отправляем заявку админам
            admin_text = (
                f"<b>🆕 НОВАЯ ЗАЯВКА НА ВЫВОД #{withdrawal_id}</b>\n\n"
                f"<b>👤 Воркер:</b> @{message.from_user.username or 'нет'}\n"
                f"<b>📛 Имя:</b> {message.from_user.first_name}\n"
                f"<b>🔗 Ссылка на гифты:</b> <code>{gift_url}</code>\n"
                f"<b>🎯 Направление:</b> <code>{direction}</code>\n"
                f"<b>📊 Процент воркера:</b> <code>{worker_percent}%</code>\n"
                f"<b>💳 Кошелек:</b> <code>{wallet_address}</code>\n"
                f"<b>📋 Тип кошелька:</b> <code>{wallet_type}</code>\n"
                f"<b>📎 Пруфов прикреплено:</b> {len(proofs)}\n\n"
                f"<b>⏰ Время:</b> <code>{datetime.now().strftime('%d.%m.%Y %H:%M')}</code>\n\n"
                f"<i>💰 Сумма профита: ожидает оценки</i>"
            )
            
            # Отправляем всем админам
            admins = db.get_all_admins()
            for admin_id in admins:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_text,
                        reply_markup=get_admin_withdrawal_keyboard(withdrawal_id)
                    )
                    
                    # Отправляем пруфы админу
                    for proof in proofs:
                        if proof['type'] == 'photo':
                            await bot.send_photo(admin_id, proof['file_id'], caption="📸 Пруф профита")
                        elif proof['type'] == 'video':
                            await bot.send_video(admin_id, proof['file_id'], caption="🎥 Пруф профита")
                        elif proof['type'] == 'document':
                            await bot.send_document(admin_id, proof['file_id'], caption="📄 Пруф профита")
                        elif proof['type'] == 'text':
                            await bot.send_message(admin_id, f"📝 Текстовый пруф:\n\n{proof['text']}")
                except Exception as e:
                    logger.error(f"Ошибка отправки админу {admin_id}: {e}")
        else:
            await message.answer("<b>❌ Ошибка при создании заявки</b>")
        
        await state.finish()
        return
    
    # Обработка прикрепленных файлов
    proof_data = {'type': 'unknown'}
    
    if message.photo:
        proof_data['type'] = 'photo'
        proof_data['file_id'] = message.photo[-1].file_id
    elif message.video:
        proof_data['type'] = 'video'
        proof_data['file_id'] = message.video.file_id
    elif message.document:
        proof_data['type'] = 'document'
        proof_data['file_id'] = message.document.file_id
    elif message.text:
        proof_data['type'] = 'text'
        proof_data['text'] = message.text
    else:
        await message.answer("<b>❌ Неподдерживаемый тип файла</b>")
        return
    
    # Сохраняем пруф в состоянии
    data = await state.get_data()
    proofs = data.get('proofs', [])
    proofs.append(proof_data)
    await state.update_data({'proofs': proofs})
    
    await message.answer(f"<b>✅ Пруф добавлен ({len(proofs)} шт.)</b>")

# ==================== МОИ ЗАЯВКИ ====================
@dp.message_handler(lambda message: message.text == "📋 Мои заявки")
async def my_withdrawals_handler(message: types.Message):
    user_id = message.from_user.id
    withdrawals = db.get_user_withdrawals(user_id)
    
    if not withdrawals:
        await send_message_with_photo(user_id, "<b>📭 У вас еще нет заявок на вывод</b>")
        return
    
    response = "<b>📋 ВАШИ ЗАЯВКИ:</b>\n\n"
    
    for w_id, amount, direction, wallet_type, status, gift_url, worker_percent, worker_amount, admin_amount, created_at in withdrawals:
        status_emoji = {
            'pending': '⏳',
            'approved': '✅',
            'rejected': '❌',
            'paid': '💰'
        }.get(status, '📝')
        
        # Форматируем сумму в зависимости от статуса
        amount_display = f"{amount:.2f} TON" if amount > 0 else "ожидает оценки"
        
        response += (
            f"<b>🔸 Заявка #{w_id}</b>\n"
            f"<b>💰 Сумма профита:</b> <code>{amount_display}</code>\n"
            f"<b>🎯 Направление:</b> <code>{direction}</code>\n"
            f"<b>🔗 Ссылка на гифты:</b> <code>{gift_url[:50]}...</code>\n"
            f"<b>📊 Ваш процент:</b> <code>{worker_percent}%</code>\n"
        )
        
        if amount > 0:
            response += (
                f"<b>💵 Ваша выплата:</b> <code>{worker_amount:.2f} TON</code> (≈{format_ton_to_usd(worker_amount)})\n"
                f"<b>👨‍💼 Админу:</b> <code>{admin_amount:.2f} TON</code>\n"
            )
        
        response += (
            f"<b>📊 Статус:</b> {status_emoji} <i>{status}</i>\n"
            f"<b>📅 Дата:</b> <code>{created_at}</code>\n\n"
        )
    
    await send_message_with_photo(user_id, response)

# ==================== ИНФОРМАЦИЯ ====================
@dp.message_handler(lambda message: message.text == "ℹ️ Информация")
async def info_handler(message: types.Message):
    info_text = (
        f"<b>ℹ️ ИНФОРМАЦИЯ О ПРОЕКТЕ</b>\n\n"
        f"<i>Мы — команда <b>{TEAM_NAME}</b></i>\n"
        f"<i>Работаем с мамонтами и выплачиваем воркерам</i>\n\n"
        f"<b>📌 Полезные ссылки и информация:</b>"
    )
    
    await send_message_with_photo(message.from_user.id, info_text, get_info_keyboard())

@dp.callback_query_handler(lambda call: call.data == "project_stats")
async def project_stats_callback(call: types.CallbackQuery):
    try:
        # Получаем статистику команды с реальным количеством участников
        team_stats = db.get_real_team_stats_with_members_count()
        
        if team_stats:
            total_amount, total_profits, today_amount, today_profits, \
            most_common_direction, active_workers, team_members_count = team_stats
            
            stats_text = (
                f"<b>📊 СТАТИСТИКА КОМАНДЫ</b>\n\n"
                f"<b>👥 Состав команды:</b>\n"
                f"• <b>Всего в тиме:</b> <code>{team_members_count} чел.</code>\n"
                f"• <b>Активных воркеров:</b> <code>{active_workers} чел.</code>\n\n"
                f"<b>📈 За все время:</b>\n"
                f"• <b>Сумма профитов:</b> <code>{total_amount:.2f} TON</code> (≈{format_ton_to_usd(total_amount)})\n"
                f"• <b>Количество профитов:</b> <code>{total_profits}</code>\n"
                f"• <b>Самое популярное направление:</b> <code>{most_common_direction or 'Нет данных'}</code>\n\n"
                f"<b>📅 За сегодня:</b>\n"
                f"• <b>Сумма профитов:</b> <code>{today_amount:.2f} TON</code> (≈{format_ton_to_usd(today_amount)})\n"
                f"• <b>Количество профитов:</b> <code>{today_profits}</code>"
            )
            
            await call.answer()
            await send_message_with_photo(call.message.chat.id, stats_text)
        else:
            await call.answer("❌ Статистика недоступна")
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await call.answer("❌ Ошибка получения статистики")

@dp.callback_query_handler(lambda call: call.data == "manuals")
async def manuals_callback(call: types.CallbackQuery):
    manuals_text = (
        "<b>📚 МАНУАЛЫ ОТ GODS TEAM</b>\n\n"
        "<b>🔹 Мануал как заводить на гаранта:</b>\n"
        "<code>https://telegra.ph/Manual-kak-zavodit-na-garanta-by-Gods-Team-01-28</code>\n\n"
        "<b>🔹 Мануал как заводить на Плейрок ОТС:</b>\n"
        "<code>https://telegra.ph/test-01-22-385</code>\n\n"
        "<b>🔹 Ссылки на все мануалы:</b>\n"
        "<code>https://telegra.ph/Ssylki-na-vse-manualy-ot-Gods-Team-01-28</code>"
    )
    
    await call.answer()
    await send_message_with_photo(call.message.chat.id, manuals_text)

@dp.callback_query_handler(lambda call: call.data == "administration")
async def administration_callback(call: types.CallbackQuery):
    admin_text = (
        "<b>🤵 АДМИНИСТРАЦИЯ GODS TEAM</b>\n\n"
        "<b>👑 Руководство:</b>\n"
        "• <b>Саппорт плейрок:</b> @RelayerPlayerok\n"
        "• <b>Кодер:</b> @SillStrik\n"
        "• <b>Наставник:</b> @DimaCrimons\n\n"
        "<b>🛠 Техническая поддержка:</b>\n"
        "• <b>По вопросам выплат:</b> @GodsTeamPayout_bot\n"
        "• <b>Для связи с админами:</b> @GodsTeamCvyazbot"
    )
    
    await call.answer()
    await send_message_with_photo(call.message.chat.id, admin_text)

@dp.callback_query_handler(lambda call: call.data == "feedback")
async def feedback_callback(call: types.CallbackQuery):
    feedback_text = (
        "<b>💬 ОБРАТНАЯ СВЯЗЬ</b>\n\n"
        "<i>По всем вопросам обращайтесь:</i>\n\n"
        "<b>🤵 Для связи с админами:</b>\n"
        "@GodsTeamCvyazbot\n\n"
        "<b>🛠 Техническая поддержка:</b>\n"
        "@SillStrik\n\n"
        "<b>💰 По вопросам выплат:</b>\n"
        "@GodsTeamPayout_bot"
    )
    
    await call.answer()
    await send_message_with_photo(call.message.chat.id, feedback_text)

@dp.callback_query_handler(lambda call: call.data == "traffer_bot")
async def traffer_bot_callback(call: types.CallbackQuery):
    await call.answer("🤖 Бот для трафферов: @GodsTeamTraffic_bot")

@dp.callback_query_handler(lambda call: call.data == "news")
async def news_callback(call: types.CallbackQuery):
    await call.answer("📰 Новости: @GodsTeamNews (канал в разработке)")

# ==================== ТОП ВОРКЕРОВ ====================
@dp.message_handler(lambda message: message.text == "🏆 Топ воркеров")
async def top_workers_handler(message: types.Message):
    user_id = message.from_user.id
    
    top_workers = db.get_top_workers(limit=10)
    user_rank = db.get_user_rank(user_id)
    user_data = db.get_user_stats(user_id)
    
    response = "<b>🏆 ТОП 10 ПОЛЬЗОВАТЕЛЕЙ ПО ПРОФИТАМ</b>\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (worker_id, username, first_name, total_earned, profits_count) in enumerate(top_workers):
        medal = medals[i] if i < 3 else " "
        
        # Получаем самое частое направление для этого воркера
        most_common_direction = db.get_most_common_direction(worker_id)
        direction_display = f" | 🎯 {most_common_direction}" if most_common_direction else ""
        
        formatted_name = format_name_for_top(first_name)
        formatted_username = format_username_for_top(username)
        
        response += (
            f"<b>#{i+1} Воркер</b>\n"
            f"{medal} <i>{formatted_name}</i> | Юзернейм: <code>{formatted_username}</code>{direction_display}\n"
            f"<b>Сумма:</b> <code>{total_earned:.2f} TON</code> (≈{format_ton_to_usd(total_earned)}) ({profits_count} профитов)\n\n"
        )
    
    if user_data:
        username = user_data[0]
        first_name = user_data[1]
        total_earned = user_data[3]
        profits_count = user_data[9]
        
        # Получаем самое частое направление для текущего пользователя
        most_common_direction = db.get_most_common_direction(user_id)
        direction_display = f" | 🎯 {most_common_direction}" if most_common_direction else ""
        
        formatted_name = format_name_for_top(first_name)
        formatted_username = format_username_for_top(username)
        
        response += f"<b>👤 ВЫ:</b>\n"
        response += f"<b>Место:</b> #{user_rank}\n"
        response += f"<i>{formatted_name}</i> | Юзернейм: <code>{formatted_username}</code>{direction_display}\n"
        response += f"<b>Сумма:</b> <code>{total_earned:.2f} TON</code> (≈{format_ton_to_usd(total_earned)}) ({profits_count} профитов)"
    
    await send_message_with_photo(user_id, response)

# ==================== АДМИН МЕНЮ ====================
@dp.message_handler(lambda message: message.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
    active_users = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    blocked_users = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT SUM(total_earned) FROM users")
    total_earned = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'")
    pending_withdrawals = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT SUM(worker_amount) FROM withdrawals WHERE status = 'paid'")
    total_worker_paid = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute("SELECT SUM(admin_amount) FROM withdrawals WHERE status = 'paid'")
    total_admin_paid = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute("SELECT AVG(worker_percent) FROM users WHERE is_active = 1")
    avg_percent = db.cursor.fetchone()[0] or DEFAULT_WORKER_PERCENT
    
    # Статистика по направлениям
    db.cursor.execute('''
    SELECT direction, COUNT(*) as count, SUM(amount) as total 
    FROM withdrawals WHERE status = 'paid' 
    GROUP BY direction ORDER BY count DESC
    ''')
    direction_stats = db.cursor.fetchall()
    
    direction_info = ""
    for direction, count, total in direction_stats:
        direction_info += f"• <b>{direction}:</b> {count} заявок, {total:.2f} TON\n"
    
    if not direction_info:
        direction_info = "• Нет данных\n"
    
    # Статистика по админам
    admin_count = len(db.get_all_admins())
    
    stats_text = (
        f"<b>📊 СТАТИСТИКА БОТА</b>\n\n"
        f"<b>👥 ПОЛЬЗОВАТЕЛИ:</b>\n"
        f"• <b>Всего:</b> <code>{total_users}</code>\n"
        f"• <b>Активных:</b> <code>{active_users}</code>\n"
        f"• <b>Заблокированных:</b> <code>{blocked_users}</code>\n"
        f"• <b>Админов:</b> <code>{admin_count}</code>\n"
        f"• <b>Средний процент:</b> <code>{avg_percent:.1f}%</code>\n\n"
        f"<b>💰 ФИНАНСЫ:</b>\n"
        f"• <b>Всего заработано:</b> <code>{total_earned:.2f} TON</code>\n"
        f"• <b>Выплачено воркерам:</b> <code>{total_worker_paid:.2f} TON</code>\n"
        f"• <b>Заработано админом:</b> <code>{total_admin_paid:.2f} TON</code>\n\n"
        f"<b>📊 НАПРАВЛЕНИЯ:</b>\n"
        f"{direction_info}\n"
        f"<b>📋 ЗАЯВКИ:</b>\n"
        f"• <b>Ожидают обработки:</b> <code>{pending_withdrawals}</code>"
    )
    
    await send_message_with_photo(message.from_user.id, stats_text)

@dp.message_handler(lambda message: message.text == "📋 Ожидающие заявки")
async def pending_withdrawals_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    withdrawals = db.get_pending_withdrawals()
    
    if not withdrawals:
        await send_message_with_photo(message.from_user.id, "<b>✅ Нет заявок, ожидающих обработки</b>")
        return
    
    response = "<b>📋 ЗАЯВКИ, ОЖИДАЮЩИЕ ОБРАБОТКИ:</b>\n\n"
    
    for withdrawal in withdrawals[:10]:
        w_id, user_id, amount, wallet, wallet_type, direction, status, _, _, gift_url, worker_percent, admin_amount, worker_amount, created_at, _, username, first_name, w_percent = withdrawal
        
        amount_display = f"{amount:.2f} TON" if amount > 0 else "ожидает оценки"
        
        response += (
            f"<b>🔸 Заявка #{w_id}</b>\n"
            f"<b>👤 Воркер:</b> @{username or 'нет'} (<i>{first_name}</i>)\n"
            f"<b>💰 Сумма:</b> <code>{amount_display}</code>\n"
            f"<b>🔗 Ссылка на гифты:</b> <code>{gift_url[:50]}...</code>\n"
            f"<b>🎯 Направление:</b> <code>{direction}</code>\n"
            f"<b>📊 Процент:</b> <code>{worker_percent}%</code>\n"
            f"<b>💳 Кошелек:</b> <code>{wallet}</code>\n"
            f"<b>📅 Дата:</b> <code>{created_at}</code>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        )
    
    if len(withdrawals) > 10:
        response += f"\n<i>... и еще {len(withdrawals) - 10} заявок</i>"
    
    await send_message_with_photo(message.from_user.id, response)

@dp.message_handler(lambda message: message.text == "👥 Все пользователи")
async def all_users_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    users = db.get_all_users()
    
    if not users:
        await send_message_with_photo(message.from_user.id, "<b>📭 Нет зарегистрированных пользователей</b>")
        return
    
    response = "<b>👥 ВСЕ ПОЛЬЗОВАТЕЛЬ:</b>\n\n"
    
    for user in users[:20]:
        u_id, username, first_name, total_earned, worker_percent, is_active, is_blocked = user
        
        # Получаем самое частое направление пользователя
        most_common_direction = db.get_most_common_direction(u_id)
        direction_info = f"<b>🎯 Направление:</b> <code>{most_common_direction or 'Нет данных'}</code>\n" if most_common_direction else ""
        
        block_status = "🔴 <b>Заблокирован</b>" if is_blocked else "🟢 <b>Активен</b>"
        
        response += (
            f"<b>👤 @{username or 'нет'}</b> (<i>{first_name}</i>)\n"
            f"<b>🆔 ID:</b> <code>{u_id}</code>\n"
            f"<b>🏦 Всего:</b> <code>{total_earned:.2f} TON</code>\n"
            f"<b>📊 Процент:</b> <code>{worker_percent}%</code>\n"
            f"{direction_info}"
            f"<b>📈 Статус:</b> {block_status}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        )
    
    if len(users) > 20:
        response += f"\n<i>... и еще {len(users) - 20} пользователей</i>"
    
    await send_message_with_photo(message.from_user.id, response)

@dp.message_handler(lambda message: message.text == "🔙 В админ меню")
async def back_to_admin_menu(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    await admin_panel_handler(message)

# ==================== ОБРАБОТЧИКИ ДЛЯ ЗАЯВОК ====================
@dp.callback_query_handler(lambda call: call.data.startswith('set_amount_'))
async def set_amount_withdrawal(call: types.CallbackQuery):
    try:
        withdrawal_id = int(call.data.split('_')[2])
        logger.info(f"Попытка установки суммы для выплаты #{withdrawal_id}")
        
        withdrawal = db.get_withdrawal(withdrawal_id)
        
        if withdrawal:
            status = withdrawal[6]
            
            logger.info(f"Найдена заявка #{withdrawal_id}: статус = {status}")
            
            if status == 'pending':
                await call.answer("Введите сумму профита в TON")
                
                # Получаем информацию о пользователе для отображения
                user_data = db.get_user_stats(withdrawal[1])
                username = user_data[0] if user_data else "неизвестно"
                first_name = user_data[1] if user_data else "неизвестно"
                
                await bot.send_message(
                    chat_id=call.from_user.id,
                    text=(
                        f"<b>💰 УСТАНОВКА СУММЫ ПРОФИТА #{withdrawal_id}</b>\n\n"
                        f"<b>👤 Воркер:</b> @{username or 'нет'} (<i>{first_name}</i>)\n"
                        f"<b>🔗 Ссылка на гифты:</b> <code>{withdrawal[9]}</code>\n"
                        f"<b>🎯 Направление:</b> <code>{withdrawal[5]}</code>\n"
                        f"<b>📊 Процент воркера:</b> <code>{withdrawal[10]}%</code>\n"
                        f"<b>💳 Кошелек:</b> <code>{withdrawal[3]}</code>\n\n"
                        f"<i>Введите сумму профита в TON:</i>"
                    ),
                    reply_markup=get_cancel_keyboard()
                )
                
                state = dp.current_state(chat=call.from_user.id, user=call.from_user.id)
                await state.update_data({'withdrawal_id_for_amount': withdrawal_id})
                
                await AdminStates.waiting_for_amount_setting.set()
            else:
                await call.answer(f"❌ Заявка уже обработана (статус: {status})")
        else:
            await call.answer("❌ Заявка не найдена в базе данных")
            logger.error(f"Заявка #{withdrawal_id} не найдена в базе")
            
    except Exception as e:
        await call.answer("❌ Ошибка при обработке заявки")
        logger.error(f"Ошибка в set_amount_withdrawal: {e}")
        logger.error(f"Трассировка: {traceback.format_exc()}")

@dp.message_handler(state=AdminStates.waiting_for_amount_setting)
async def process_amount_setting(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text == "❌ Отмена":
        await state.finish()
        await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_admin_menu_keyboard())
        return
    
    if message.text == "🔙 В главное меню":
        await state.finish()
        await back_to_main_menu_handler(message)
        return
    
    try:
        amount = float(message.text)
        
        if amount <= 0:
            await message.answer("<b>❌ Сумма должна быть больше 0</b>")
            return
        
        if amount > MAX_WITHDRAWAL:
            await message.answer(f"<b>❌ Максимальная сумма вывода: {MAX_WITHDRAWAL} TON</b>")
            return
        
        # Получаем данные из состояния
        data = await state.get_data()
        withdrawal_id = data.get('withdrawal_id_for_amount')
        
        if not withdrawal_id:
            await message.answer("<b>❌ Ошибка: ID заявки не найден</b>")
            await state.finish()
            return
        
        withdrawal = db.get_withdrawal(withdrawal_id)
        
        if withdrawal:
            worker_percent = withdrawal[10]
            
            logger.info(f"Установка суммы для заявки #{withdrawal_id}:")
            logger.info(f"  Общая сумма: {amount} TON")
            logger.info(f"  Процент воркера: {worker_percent}%")
            
            worker_amount = (amount * worker_percent) / 100
            admin_amount = amount - worker_amount
            
            logger.info(f"  Воркеру: {worker_amount:.2f} TON")
            logger.info(f"  Админу: {admin_amount:.2f} TON")
            
            db.update_withdrawal_amount(withdrawal_id, amount, worker_amount, admin_amount)
            
            admin_text = (
                f"<b>✅ СУММА ПРОФИТА УСТАНОВЛЕНА!</b>\n\n"
                f"<b>📋 Заявка #{withdrawal_id}</b>\n"
                f"<b>💰 Сумма профита:</b> <code>{amount:.2f} TON</code>\n"
                f"<b>📊 Процент воркера:</b> <code>{worker_percent}%</code>\n"
                f"<b>💵 Воркеру:</b> <code>{worker_amount:.2f} TON</code> (≈{format_ton_to_usd(worker_amount)})\n"
                f"<b>💼 Админу:</b> <code>{admin_amount:.2f} TON</code> (≈{format_ton_to_usd(admin_amount)})\n\n"
                f"<b>📝 Дальнейшие действия:</b>\n"
                f"• Для подтверждения выплаты отправьте скриншот выплаты\n"
                f"• Для отклонения заявки нажмите ❌ Отклонить"
            )
            
            # Отправляем сообщение с новой клавиатурой для продолжения работы
            await send_message_with_photo(
                user_id, 
                admin_text, 
                get_admin_withdrawal_after_amount_keyboard(withdrawal_id)
            )
            
            # Уведомляем воркера
            worker_text = (
                f"<b>💰 СУММА ПРОФИТА УСТАНОВЛЕНА!</b>\n\n"
                f"<b>✅ Заявка #{withdrawal_id} оценена</b>\n"
                f"<b>💰 Сумма профита:</b> <code>{amount:.2f} TON</code>\n"
                f"<b>📊 Ваш процент:</b> <code>{worker_percent}%</code>\n"
                f"<b>💵 К выплате:</b> <code>{worker_amount:.2f} TON</code> (≈{format_ton_to_usd(worker_amount)})\n"
                f"<b>🎯 Направление:</b> <code>{withdrawal[5]}</code>\n"
                f"<b>💳 Кошелек:</b> <code>{withdrawal[3]}</code>\n\n"
                f"<i>⏳ Ожидайте подтверждения выплаты</i>"
            )
            
            try:
                await send_message_with_photo(withdrawal[1], worker_text)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {withdrawal[1]}: {e}")
        else:
            await message.answer("<b>❌ Заявка не найдена</b>")
        
        await state.finish()
        
    except ValueError:
        await message.answer("<b>❌ Введите корректную сумму (число)</b>")

@dp.callback_query_handler(lambda call: call.data.startswith('reject_'))
async def reject_withdrawal(call: types.CallbackQuery):
    withdrawal_id = int(call.data.split('_')[1])
    
    await call.answer("Введите причину отклонения")
    
    await bot.send_message(
        chat_id=call.from_user.id,
        text=(
            f"<b>❌ ОТКЛОНЕНИЕ ЗАЯВКИ #{withdrawal_id}</b>\n\n"
            f"<i>Введите причину отклонения заявки:</i>"
        ),
        reply_markup=get_cancel_keyboard()
    )
    
    state = dp.current_state(chat=call.from_user.id, user=call.from_user.id)
    await state.update_data({'withdrawal_id': withdrawal_id})
    
    await AdminStates.waiting_for_reject_reason.set()

@dp.message_handler(state=AdminStates.waiting_for_reject_reason)
async def process_reject_reason(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text == "❌ Отмена":
        await state.finish()
        await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_admin_menu_keyboard())
        return
    
    if message.text == "🔙 В главное меню":
        await state.finish()
        await back_to_main_menu_handler(message)
        return
    
    data = await state.get_data()
    withdrawal_id = data.get('withdrawal_id')
    
    if not withdrawal_id:
        await message.answer("<b>❌ Ошибка: ID заявки не найден</b>")
        await state.finish()
        return
    
    withdrawal = db.get_withdrawal(withdrawal_id)
    
    if withdrawal:
        db.update_withdrawal_status(withdrawal_id, 'rejected', message.text)
        
        await bot.send_message(user_id, f"<b>✅ Заявка #{withdrawal_id} отклонена</b>")
        
        worker_text = (
            f"<b>❌ ВАША ЗАЯВКА #{withdrawal_id} ОТКЛОНЕНА</b>\n\n"
            f"<b>📝 Причина:</b> <i>{message.text}</i>\n"
            f"<b>🔗 Ссылка на гифты:</b> <code>{withdrawal[9]}</code>\n"
            f"<b>🎯 Направление:</b> <code>{withdrawal[5]}</code>"
        )
        try:
            await send_message_with_photo(withdrawal[1], worker_text)
        except:
            logger.error(f"Не удалось отправить уведомление пользователю {withdrawal[1]}")
    
    await state.finish()

@dp.callback_query_handler(lambda call: call.data.startswith('approve_'))
async def approve_withdrawal(call: types.CallbackQuery):
    try:
        withdrawal_id = int(call.data.split('_')[1])
        logger.info(f"Попытка подтверждения выплаты #{withdrawal_id}")
        
        withdrawal = db.get_withdrawal(withdrawal_id)
        
        if withdrawal:
            status = withdrawal[6]
            amount = withdrawal[2]
            
            logger.info(f"Найдена заявка #{withdrawal_id}: статус = {status}, сумма = {amount}")
            
            if status == 'pending' and amount > 0:
                await call.answer("Отправьте скриншот выплаты")
                
                user_data = db.get_user_stats(withdrawal[1])
                username = user_data[0] if user_data else "неизвестно"
                first_name = user_data[1] if user_data else "неизвестно"
                
                worker_amount = withdrawal[12]
                
                await bot.send_message(
                    chat_id=call.from_user.id,
                    text=(
                        f"<b>💰 ПОДТВЕРЖДЕНИЕ ВЫПЛАТЫ #{withdrawal_id}</b>\n\n"
                        f"<b>👤 Воркер:</b> @{username or 'нет'} (<i>{first_name}</i>)\n"
                        f"<b>💰 Сумма профита:</b> <code>{amount:.2f} TON</code>\n"
                        f"<b>💵 К выплате:</b> <code>{worker_amount:.2f} TON</code>\n"
                        f"<b>🎯 Направление:</b> <code>{withdrawal[5]}</code>\n"
                        f"<b>💳 Кошелек:</b> <code>{withdrawal[3]}</code>\n\n"
                        f"<i>Отправьте скриншот выплаты для заявки:</i>"
                    ),
                    reply_markup=get_cancel_keyboard()
                )
                
                state = dp.current_state(chat=call.from_user.id, user=call.from_user.id)
                await state.update_data({'withdrawal_id_for_payment': withdrawal_id})
                
                await AdminStates.waiting_for_payment_proof.set()
            elif amount <= 0:
                await call.answer("❌ Сначала установите сумму профита")
            else:
                await call.answer(f"❌ Заявка уже обработана (статус: {status})")
        else:
            await call.answer("❌ Заявка не найдена в базе данных")
            logger.error(f"Заявка #{withdrawal_id} не найдена в базе")
            
    except Exception as e:
        await call.answer("❌ Ошибка при обработке заявки")
        logger.error(f"Ошибка в approve_withdrawal: {e}")
        logger.error(f"Трассировка: {traceback.format_exc()}")

@dp.message_handler(state=AdminStates.waiting_for_payment_proof)
async def handle_payment_proof_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text == "❌ Отмена":
        await state.finish()
        await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_admin_menu_keyboard())
        return
    
    if message.text == "🔙 В главное меню":
        await state.finish()
        await back_to_main_menu_handler(message)
        return
    
    await message.answer("<b>❌ Пожалуйста, отправьте скриншот выплаты (фото)</b>")

@dp.message_handler(content_types=types.ContentType.PHOTO, state=AdminStates.waiting_for_payment_proof)
async def process_payment_proof(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    data = await state.get_data()
    withdrawal_id = data.get('withdrawal_id_for_payment')
    
    if not withdrawal_id:
        await message.answer("<b>❌ Ошибка: ID заявки не найден</b>")
        await state.finish()
        return
    
    withdrawal = db.get_withdrawal(withdrawal_id)
    
    if not withdrawal:
        await message.answer("<b>❌ Заявка не найдена</b>")
        await state.finish()
        return
    
    # Обновляем статус заявки на "paid"
    db.update_withdrawal_status(withdrawal_id, 'paid')
    
    # Обновляем общую сумму заработанного у воркера
    worker_amount = withdrawal[12]
    user_data = db.get_user_stats(withdrawal[1])
    if user_data:
        db.update_total_earned(withdrawal[1], worker_amount)
    
    await send_message_with_photo(user_id, f"<b>✅ Выплата по заявке #{withdrawal_id} подтверждена</b>", get_admin_menu_keyboard())
    
    # Отправляем уведомление воркеру
    worker_text = (
        f"<b>💰 ВЫПЛАТА ПОЛУЧЕНА!</b>\n\n"
        f"<b>✅ Заявка #{withdrawal_id} выплачена</b>\n"
        f"<b>💵 Сумма:</b> <code>{worker_amount:.2f} TON</code>\n"
        f"<b>📊 Ваш процент:</b> <code>{withdrawal[10]}%</code>\n"
        f"<b>🎯 Направление:</b> <code>{withdrawal[5]}</code>\n"
        f"<b>💳 Кошелек:</b> <code>{withdrawal[3]}</code>\n\n"
        f"<i>📈 Общая сумма продажи обновлена</i>\n"
        f"<i>🙏 Спасибо за работу!</i>"
    )
    
    try:
        await send_message_with_photo(withdrawal[1], worker_text)
        
        # Отправляем скриншот выплаты воркеру
        photo = message.photo[-1]
        await bot.send_photo(
            chat_id=withdrawal[1],
            photo=photo.file_id,
            caption="<b>📸 Скриншот выплаты</b>"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление пользователю {withdrawal[1]}: {e}")
    
    await state.finish()

@dp.message_handler(content_types=types.ContentType.ANY, state=AdminStates.waiting_for_payment_proof)
async def handle_other_content_payment_proof(message: types.Message, state: FSMContext):
    if message.text not in ["❌ Отмена", "🔙 В главное меню"]:
        await message.answer("<b>❌ Пожалуйста, отправьте скриншот выплаты (фото)</b>")

# ==================== ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ ====================
@dp.callback_query_handler(lambda call: call.data == "cancel_request")
async def cancel_request_callback_global(call: types.CallbackQuery):
    user_id = call.from_user.id
    state = dp.current_state(chat=user_id, user=user_id)
    await state.finish()
    
    await call.answer("❌ Действие отменено")
    await send_message_with_photo(user_id, "<b>❌ Действие отменено</b>", get_main_keyboard(user_id))

@dp.message_handler(lambda message: message.text == "🔙 В админ меню")
async def back_to_admin_menu_from_anywhere(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    # Завершаем любое активное состояние
    state = dp.current_state(chat=message.from_user.id, user=message.from_user.id)
    await state.finish()
    
    await admin_panel_handler(message)

# ==================== ЗАПУСК БОТА ====================
async def on_startup(dp):
    logger.info("🤖 Бот запускается...")
    logger.info(f"👑 Главный админ ID: {ADMIN_ID}")
    logger.info(f"🏆 Название тимы: {TEAM_NAME}")
    logger.info(f"💼 Процент воркера по умолчанию: {DEFAULT_WORKER_PERCENT}%")
    logger.info(f"📢 URL тимы: {TEAM_CHANNEL_URL}")
    logger.info(f"👥 ID форума для подсчета участников: {TEAM_CHAT_ID}")
    
    # Проверяем наличие токена
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден. Убедитесь, что он указан в .env файле")
        return
    
    # Добавляем главного админа в базу, если его нет
    try:
        main_admin = await bot.get_chat(ADMIN_ID)
        username = main_admin.username or "main_admin"
        first_name = main_admin.first_name or "Главный админ"
        
        if not db.is_admin(ADMIN_ID):
            db.add_admin(ADMIN_ID, username, first_name)
            logger.info(f"✅ Главный админ добавлен в базу: {username}")
        else:
            logger.info("✅ Главный админ уже в базе")
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении главного админа: {e}")
    
    if not os.path.exists(MAIN_MENU_PHOTO_PATH):
        logger.warning(f"⚠️ Файл {MAIN_MENU_PHOTO_PATH} не найден. Главное меню будет без фото.")

async def on_shutdown(dp):
    db.close()
    logger.info("🛑 Бот остановлен")

if __name__ == '__main__':
    try:
        executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown, skip_updates=True)
    except Exception as e:
        logger.error(f"❌ Ошибка при работе бота: {e}")