import asyncio
from datetime import datetime
import logging
import os
import random
import sqlite3
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

# Токен та ID
TOKEN = "8806921238:AAGfgdhGPQd5Gh0QZM2kYCHYnMOq7jKSf5c"
ALLOWED_USERS = [679531786, 572759802]

# Дата початку стосунків (змініть рік на ваш, наприклад 2024 або 2025)
START_DATE = datetime(2026, 8, 8)

router = Router()


class PhotoStates(StatesGroup):
  waiting_for_location = State()


def init_db():
  conn = sqlite3.connect("couple_photos.db")
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_id TEXT,
            location TEXT
        )
    """)
  conn.commit()
  conn.close()


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

  if not photos_list:
    await state.clear()
    return

  conn = sqlite3.connect("couple_photos.db")
  cursor = conn.cursor()
  for file_id in photos_list:
    cursor.execute(
        "INSERT INTO photos (user_id, file_id, location) VALUES (?, ?, ?)",
        (message.from_user.id, file_id, location),
    )
  conn.commit()
  conn.close()
  await state.clear()

  await message.answer(
      f"✅ Збережено в архів: <b>{len(photos_list)} шт.</b>\n📍 Локація:"
      f" <b>{location}</b>",
      parse_mode="HTML",
      reply_markup=get_main_keyboard(),
  )


@router.message(F.text == "🎲 Випадковий спогад")
async def cmd_random_memory(message: Message):
  if not is_allowed(message.from_user.id):
    return
  conn = sqlite3.connect("couple_photos.db")
  cursor = conn.cursor()
  cursor.execute("SELECT file_id, location FROM photos")
  rows = cursor.fetchall()
  conn.close()

  if not rows:
    await message.answer("В архіві ще немає фото!", reply_markup=get_main_keyboard())
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
  if not is_allowed(callback.from_user.id):
    return
  conn = sqlite3.connect("couple_photos.db")
  cursor = conn.cursor()
  cursor.execute("SELECT file_id, location FROM photos")
  rows = cursor.fetchall()
  conn.close()

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
  if not is_allowed(message.from_user.id):
    return
  conn = sqlite3.connect("couple_photos.db")
  cursor = conn.cursor()
  cursor.execute("SELECT COUNT(*), COUNT(DISTINCT location) FROM photos")
  count, unique_locations = cursor.fetchone()
  conn.close()
  await message.answer(
      f"📊 <b>Статистика:</b>\n\n📸 Фото: <b>{count}</b>\n📍 Локацій:"
      f" <b>{unique_locations}</b>",
      parse_mode="HTML",
      reply_markup=get_main_keyboard(),
  )


# Функція для підрахунку точної кількості місяців разом
def calculate_months():
  now = datetime.now()
  months = (now.year - START_DATE.year) * 12 + (now.month - START_DATE.month)
  return months


# Фонова задача для щомісячного нагадування 8-го числа
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
                  " місяців разом!</b> ❤️\n\nСьогодні 8 число! 🥰 Час згадати"
                  " найліпші моменти, тисніть кнопку нижче або «🎲 Випадковий"
                  " спогад»!"
              ),
              parse_mode="HTML",
          )
        except Exception as e:
          logging.error(f"Помилка надсилання щомісячного сповіщення: {e}")
      last_sent_month = now.month
    await asyncio.sleep(3600)


async def handle_web(request):
  return web.Response(text="Bot is running!")


async def main():
  init_db()
  bot = Bot(token=TOKEN)
  dp = Dispatcher(storage=MemoryStorage())
  dp.include_router(router)

  # Запуск фонового сповіщення
  asyncio.create_task(monthly_announcement_loop(bot))

  app = web.Application()
  app.router.add_get("/", handle_web)
  runner = web.AppRunner(app)
  await runner.setup()
  port = int(os.environ.get("PORT", 8080))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()

  print(f"Бот і веб-сервер запущено на порті {port}!")
  await dp.start_polling(bot)


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  asyncio.run(main())