import asyncio, logging, datetime, aiosqlite
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.session.aiohttp import AiohttpSession

import os
API_TOKEN = '9179237160:AAGXOc9BTs9gBr7mOBO0C31bmGlDg7Qo9uk'
ADMIN_ID = 7955876814
PROXY_URL = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = 'applications.db'
application_queue = None
user_message_times = defaultdict(list)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

class ApplicationStates(StatesGroup):
    steam_exp = State()
    steam_count = State()
    age = State()
    time_per_day = State()
    about = State()

def get_main_menu():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Подать заявку")]], resize_keyboard=True)

def get_cancel_menu():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отменить")]], resize_keyboard=True)

def is_rate_limited(user_id: int) -> bool:
    now = datetime.datetime.now()
    times = user_message_times[user_id]
    times[:] = [t for t in times if (now - t).total_seconds() < 10]
    if len(times) >= 5:
        return True
    times.append(now)
    return False

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            full_name TEXT, username TEXT, steam_exp TEXT, steam_count TEXT,
            age TEXT, time_per_day TEXT, about TEXT,
            created_at TEXT, sent_to_admin INTEGER DEFAULT 0)''')
        await db.commit()

async def save_application(user_data: dict, user_info: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''INSERT INTO applications 
            (user_id, full_name, username, steam_exp, steam_count, 
             age, time_per_day, about, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            user_info['user_id'], user_info['full_name'], user_info.get('username', ''),
            user_data.get('steam_exp', ''), user_data.get('steam_count', ''),
            user_data.get('age', ''), user_data.get('time_per_day', ''),
            user_data.get('about', ''), user_info['timestamp']))
        await db.commit()
        return cursor.lastrowid

async def mark_application_sent(app_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE applications SET sent_to_admin = 1 WHERE id = ?', (app_id,))
        await db.commit()

async def send_application_worker(bot: Bot, queue: asyncio.Queue):
    while True:
        try:
            app_id, text = await queue.get()
            try:
                await bot.send_message(chat_id=ADMIN_ID, text=text)
                await mark_application_sent(app_id)
            except Exception as e:
                logger.error(f"Ошибка отправки #{app_id}: {e}")
                await asyncio.sleep(5)
                await queue.put((app_id, text))
            finally:
                queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка воркера: {e}")

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    if is_rate_limited(message.from_user.id): return
    await message.answer("Добро пожаловать в UMBRA PROJECT BOT!\n\nНажмите 'Подать заявку'.", reply_markup=get_main_menu())

@router.message(F.text == "Подать заявку")
async def start_application(message: types.Message, state: FSMContext):
    if is_rate_limited(message.from_user.id): return
    await state.set_state(ApplicationStates.steam_exp)
    await message.answer("Создание заявки\n\n1. Есть ли опыт со Steam (да/нет):", reply_markup=get_cancel_menu())

@router.message(F.text == "Отменить")
async def cancel_application(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Заявка отменена.", reply_markup=get_main_menu())

@router.message(ApplicationStates.steam_exp)
async def process_steam_exp(message: types.Message, state: FSMContext):
    if is_rate_limited(message.from_user.id): return
    await state.update_data(steam_exp=message.text)
    await state.set_state(ApplicationStates.steam_count)
    await message.answer("2. Сколько есть Steam аккаунтов:", reply_markup=get_cancel_menu())

@router.message(ApplicationStates.steam_count)
async def process_steam_count(message: types.Message, state: FSMContext):
    if is_rate_limited(message.from_user.id): return
    await state.update_data(steam_count=message.text)
    await state.set_state(ApplicationStates.age)
    await message.answer("3. Ваш возраст:", reply_markup=get_cancel_menu())

@router.message(ApplicationStates.age)
async def process_age(message: types.Message, state: FSMContext):
    if is_rate_limited(message.from_user.id): return
    await state.update_data(age=message.text)
    await state.set_state(ApplicationStates.time_per_day)
    await message.answer("4. Сколько времени в день готовы уделять:", reply_markup=get_cancel_menu())

@router.message(ApplicationStates.time_per_day)
async def process_time(message: types.Message, state: FSMContext):
    if is_rate_limited(message.from_user.id): return
    await state.update_data(time_per_day=message.text)
    await state.set_state(ApplicationStates.about)
    await message.answer("5. Расскажите о себе:", reply_markup=get_cancel_menu())

@router.message(ApplicationStates.about)
async def process_about(message: types.Message, state: FSMContext):
    if is_rate_limited(message.from_user.id): return
    await state.update_data(about=message.text)
    user_data = await state.get_data()
    user_info = {'user_id': message.from_user.id, 'full_name': message.from_user.full_name,
                 'username': message.from_user.username or 'нет',
                 'timestamp': datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
    try:
        app_id = await save_application(user_data, user_info)
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")
        await message.answer("Ошибка сохранения. Попробуйте позже.", reply_markup=get_main_menu())
        await state.clear()
        return

    # ФОРМА ДЛЯ АДМИНИСТРАТОРА
    text = (
        f"📋 НОВАЯ ЗАЯВКА #{app_id}\n\n"
        f"👤 ID: {user_info['user_id']}\n"
        f"Имя: {user_info['full_name']}\n"
        f"Username: @{user_info['username']}\n\n"
        f"1. Опыт со Steam: {user_data.get('steam_exp', '-')}\n"
        f"2. Steam аккаунтов: {user_data.get('steam_count', '-')}\n"
        f"3. Возраст: {user_data.get('age', '-')}\n"
        f"4. Время/день: {user_data.get('time_per_day', '-')}\n"
        f"5. О себе: {user_data.get('about', '-')}\n\n"
        f"🕒 {user_info['timestamp']}"
    )
    try:
        application_queue.put_nowait((app_id, text))
    except asyncio.QueueFull:
        logger.warning(f"Очередь переполнена #{app_id}")

    await message.answer("Ваша заявка успешно отправлена! Администратор рассмотрит её в ближайшее время.", reply_markup=get_main_menu())
    await state.clear()

@router.message()
async def unknown(message: types.Message):
    if is_rate_limited(message.from_user.id): return
    await message.answer("Используйте 'Подать заявку' или /start", reply_markup=get_main_menu())

async def main():
    global application_queue
    if not API_TOKEN or API_TOKEN == 'ТВОЙ_ТОКЕН_СЮДА':
        print("Вставьте токен в переменную API_TOKEN!")
        return
    application_queue = asyncio.Queue(maxsize=500)
    await init_db()
    session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else AiohttpSession()
    bot = Bot(token=API_TOKEN, session=session)
    workers = [asyncio.create_task(send_application_worker(bot, application_queue)) for _ in range(3)]
    try:
        me = await bot.get_me()
        print(f"Бот подключён: @{me.username}")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), polling_timeout=30)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"Ошибка: {e}")
    finally:
        for w in workers: w.cancel()
        await bot.session.close()
        print("Бот остановлен.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Остановлено")
