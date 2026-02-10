import asyncio
import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv


# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty. Put it into .env")


# ================== BOT ==================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

LANGS = ["Английский", "Французский", "Китайский", "Испанский", "Итальянский", "Турецкий"]
AUDIENCE = ["Мне есть 18 лет", "Мне нет 18 лет"]


class Lead(StatesGroup):
    audience = State()
    lang = State()
    goal = State()
    name = State()
    phone = State()


# ================== HELPERS ==================
def kb(items, prefix: str, cols: int = 2):
    builder = InlineKeyboardBuilder()
    for it in items:
        builder.button(text=it, callback_data=f"{prefix}:{it}")
    builder.adjust(cols)
    return builder.as_markup()


def normalize_phone(text: str) -> str:
    digits = re.sub(r"\D+", "", text)

    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    if digits.startswith("7") and len(digits) == 11:
        return "+" + digits

    if len(digits) == 10:
        return "+7" + digits

    return text.strip()


def looks_like_phone(text: str) -> bool:
    digits = re.sub(r"\D+", "", text)
    return len(digits) >= 10


# ================== HANDLERS ==================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Это бот записи на пробный урок.\nКому нужны занятия?",
        reply_markup=kb(AUDIENCE, "aud", cols=1),
    )
    await state.set_state(Lead.audience)


@dp.callback_query(F.data.startswith("aud:"), Lead.audience)
async def pick_audience(call: CallbackQuery, state: FSMContext):
    await state.update_data(audience=call.data.split(":", 1)[1])
    await call.message.answer("Выберите язык:", reply_markup=kb(LANGS, "lang", cols=2))
    await state.set_state(Lead.lang)
    await call.answer()


@dp.callback_query(F.data.startswith("lang:"), Lead.lang)
async def pick_lang(call: CallbackQuery, state: FSMContext):
    await state.update_data(lang=call.data.split(":", 1)[1])
    await call.message.answer(
        "Какая цель обучения?\n"
        "Например: работа, переезд, путешествия, школа/вуз, разговорный, экзамен."
    )
    await state.set_state(Lead.goal)
    await call.answer()


@dp.message(Lead.goal)
async def get_goal(message: Message, state: FSMContext):
    await state.update_data(goal=(message.text or "").strip())
    await message.answer("Как вас зовут?")
    await state.set_state(Lead.name)


@dp.message(Lead.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip())
    await message.answer("Напишите телефон для связи (можно +7… или 8…).")
    await state.set_state(Lead.phone)


@dp.message(Lead.phone)
async def get_phone(message: Message, state: FSMContext):
    try:
        raw = (message.text or "").strip()
        if not looks_like_phone(raw):
            await message.answer("Похоже, это не телефон. Напишите номер ещё раз (минимум 10 цифр).")
            return

        phone = normalize_phone(raw)
        data = await state.get_data()

        lead_text = (
            "🟢 Новая заявка\n"
            f"Кто: {data.get('audience', '—')}\n"
            f"Язык: {data.get('lang', '—')}\n"
            f"Цель: {data.get('goal', '—')}\n"
            f"Имя: {data.get('name', '—')}\n"
            f"Телефон: {phone}\n"
            f"ID пользователя: {message.from_user.id}\n"
            f"Время: {datetime.now():%Y-%m-%d %H:%M:%S}"
        )

        await bot.send_message(ADMIN_CHAT_ID, lead_text)
        await message.answer("Спасибо! Заявка отправлена ✅")

        await state.clear()

    except Exception as e:
        print("❌ ERROR:", e)
        await message.answer("Произошла ошибка ❌ Проверь логи Render.")


@dp.message(Command("chatid"))
async def chatid(message: Message):
    await message.answer(f"chat_id этого чата: {message.chat.id}")


# ================== DUMMY SERVER FOR RENDER ==================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()


# ================== MAIN ==================
async def main():
    print("🚀 Bot started. ADMIN_CHAT_ID =", ADMIN_CHAT_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    asyncio.run(main())
