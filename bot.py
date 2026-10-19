import asyncio
from datetime import datetime
import logging
import os
import random
import psycopg2
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

TOKEN = "8806921238:AAGfgdhGPQd5Gh0QZM2kYCHYnMOq7jKSf5c"
ALLOWED_USERS = [679531786, 572759802]
START_DATE = datetime(2024, 8, 8)

DATABASE_URL = os.environ.get("DATABASE_URL")

router = Router()


class PhotoStates(StatesGroup):
  waiting_for_location = State()


def init_db():
  if not DATABASE_URL:
    print("❌ Помилка: DATABASE_URL не знайдено в змінних середовища!")
    return
  try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                file_id TEXT,
                location TEXT
            )
        """)
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Базу даних успішно ініціалізовано!")
  except Exception as e:
    print(f"❌ Помилка підключення до бази даних: {e}")


def is_allowed(user_id: int) -> bool:
  return user_id in ALLOWED_USERS


def get_main_keyboard():
  return ReplyKeyboardMarkup(
      keyboard=[
          [
              KeyboardButton(text="🎲 Випадковий спогад"),
              KeyboardButton(text="📊 Статистика"),
          ]
      ],
      resize_keyboard=True,
  )


def get_random_inline_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🔄 Інший спогад", callback_data="next_random"
              )
          ]
      ]
  )


@router.message(Command("start"))
async def cmd_start(message: Message):
  if not is_allowed(message.from_user.id):
    await message.answer("Цей бот є приватним сімейним архівом ❤️")
    return
  await message.answer(
      "Привіт! ❤️ Це ваш спільний фотоальбом.\n\nПросто надішліть сюди одне"
      " або кілька фото, і я збережу їх із локацією!",
      reply_markup=get_main_keyboard(),
  )


@router.message(Command("clear_all"))
async def cmd_clear_all(message: Message):
  if not is_allowed(message.from_user.id) or not DATABASE_URL:
    return

  try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM photos")
    conn.commit()
    cursor.close()
    conn.close()
    await message.answer(
        "🧹 <b>Усі спогади успішно видалено з бази даних!</b> Архів знову"
        " чистий.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard(),
    )
  except Exception as e:
    print(f"Помилка очищення БД: {e}")
    await message.answer("❌ Виникла помилка при спробі очистити архів.")


@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
  if not is_allowed(message.from_user.id):
    return
  photo_file_id = message.photo[-1].file_id
  data = await state.get_data()
  photos_list = data.get("photos_list", [])
  photos_list.append(photo_file_id)
  await state.update_data(photos_list=photos_list)

  current_state = await state.get_state()
  if current_state != PhotoStates.waiting_for_location:
    await state.set_state(PhotoStates.waiting_for_location)
    await asyncio.sleep(1.5)
    await message.answer(
        f"📸 Отримано фотографій: <b>{len(photos_list)}</b>\n\nТепер введи"
        " локацію:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(PhotoStates.waiting_for_location, F.text)
async def handle_location(message: Message, state: FSMContext):
  data = await state.get_data()
  photos_list = data.get("photos_list", [])
  location = message.text

  if not photos_list or not DATABASE_URL:
    await state.clear()
    return

  try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    for file_id in photos_list:
      cursor.execute(
          "INSERT INTO photos (user_id, file_id, location) VALUES (%s, %s,"
          " %s)",
          (message.from_user.id, file_id, location),
      )
    conn.commit()
    cursor.close()
    conn.close()
  except Exception as e:
    print(f"Помилка запису в БД: {e}")

  await state.clear()
  await message.answer(
      f"✅ Збережено в архів: <b>{len(photos_list)} шт.</b>\n📍 Локація:"
      f" <b>{location}</b>",
      parse_mode="HTML",
      reply_markup=get_main_keyboard(),
  )


@router.message(F.text == "🎲 Випадковий спогад")
async def cmd_random_memory(message: Message):
  if not is_allowed(message.from_user.id) or not DATABASE_URL:
    return
  try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, location FROM photos")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
  except Exception as e:
    print(f"Помилка читання з БД: {e}")
    rows = []

  if not rows:
    await message.answer(
        "В архіві ще немає фото!", reply_markup=get_main_keyboard()
    )
    return

  photo = random.choice(rows)
  await message.answer_photo(
      photo=photo[0],
      caption=f"✨ <b>Спогад із архіву!</b>\n📍 Локація: <b>{photo[1]}</b>",
      parse_mode="HTML",
      reply_markup=get_random_inline_keyboard(),
  )


@router.callback_query(F.data == "next_random")
async def callback_random_next(callback: CallbackQuery):
  if not is_allowed(callback.from_user.id) or not DATABASE_URL:
    return
  try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, location FROM photos")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
  except Exception as e:
    print(f"Помилка читання з БД: {e}")
    rows = []

  if not rows:
    await callback.answer("Немає фото!", show_alert=True)
    return

  photo = random.choice(rows)
  await callback.message.edit_media(
      media=InputMediaPhoto(
          media=photo[0],
          caption=f"✨ <b>Спогад із архіву!</b>\n📍 Локація: <b>{photo[1]}</b>",
          parse_mode="HTML",
      ),
      reply_markup=get_random_inline_keyboard(),
  )
  await callback.answer()


@router.message(F.text == "📊 Статистика")
async def cmd_stats(message: Message):
  if not is_allowed(message.from_user.id) or not DATABASE_URL:
    return
  try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT location) FROM photos")
    count, unique_locations = cursor.fetchone()
    cursor.close()
    conn.close()
  except Exception as e:
    print(f"Помилка статистики з БД: {e}")
    count, unique_locations = 0, 0

  await message.answer(
      f"📊 <b>Статистика:</b>\n\n📸 Фото: <b>{count}</b>\n📍 Локацій:"
      f" <b>{unique_locations}</b>",
      parse_mode="HTML",
      reply_markup=get_main_keyboard(),
  )


def calculate_months():
  now = datetime.now()
  months = (now.year - START_DATE.year) * 12 + (
      now.month - START_DATE.month
  )
  return months


async def monthly_announcement_loop(bot: Bot):
  last_sent_month = None
  while True:
    now = datetime.now()
    if now.day == 8 and now.month != last_sent_month:
      total_months = calculate_months()
      for user_id in ALLOWED_USERS:
        try:
          await bot.send_message(
              chat_id=user_id,
              text=(
                  f"❤️ <b>Вітаю, у нас сьогодні річниця — {total_months}"
                  " місяців разом!</b> ❤️\n\nСьогодні 8 число! 🥰 Час"
                  " згадати найліпші моменти, тисніть кнопку нижче або"
                  " «🎲 Випадковий спогад»!"
              ),
              parse_mode="HTML",
          )
        except Exception as e:
          logging.error(f"Помилка надсилання щомісячного сповіщення: {e}")
      last_sent_month = now.month
    await asyncio.sleep(3600)


async def handle_web(request):
  return web.Response(text="Bot is working!")


async def main():
  init_db()
  bot = Bot(