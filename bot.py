import asyncio
import os
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))  # сюда чат менеджеров (группа/супергруппа)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty. Put it into .env")

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


def kb(items, prefix: str, cols: int = 2):
    builder = InlineKeyboardBuilder()
    for it in items:
        builder.button(text=it, callback_data=f"{prefix}:{it}")
    builder.adjust(cols)
    return builder.as_markup()


def normalize_phone(text: str) -> str:
    digits = re.sub(r"\D+", "", text)

    # 8XXXXXXXXXX -> 7XXXXXXXXXX
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    # 7XXXXXXXXXX -> +7XXXXXXXXXX
    if digits.startswith("7") and len(digits) == 11:
        return "+" + digits

    # если человек ввёл 10 цифр (без 7/8) — попробуем считать что РФ
    if len(digits) == 10:
        return "+7" + digits

    return text.strip()


def looks_like_phone(text: str) -> bool:
    digits = re.sub(r"\D+", "", text)
    return len(digits) >= 10


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
    audience = call.data.split(":", 1)[1]
    await state.update_data(audience=audience)
    await call.message.answer("Выберите язык:", reply_markup=kb(LANGS, "lang", cols=2))
    await state.set_state(Lead.lang)
    await call.answer()


@dp.callback_query(F.data.startswith("lang:"), Lead.lang)
async def pick_lang(call: CallbackQuery, state: FSMContext):
    lang = call.data.split(":", 1)[1]
    await state.update_data(lang=lang)
    await call.message.answer(
        "Какая цель обучения?\n"
        "Например: работа, переезд, путешествия, школа/вуз, разговорный, экзамен."
    )
    await state.set_state(Lead.goal)
    await call.answer()


@dp.message(Lead.goal)
async def get_goal(message: Message, state: FSMContext):
    goal = (message.text or "").strip()
    await state.update_data(goal=goal)
    await message.answer("Как вас зовут?")
    await state.set_state(Lead.name)


@dp.message(Lead.name)
async def get_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    await state.update_data(name=name)
    await message.answer("Напишите телефон для связи (можно +7… или 8…).")
    await state.set_state(Lead.phone)


@dp.message(Lead.phone)
async def get_phone(message: Message, state: FSMContext):
    try:
        raw = (message.text or "").strip()
        print("📞 got phone raw:", raw)

        if not looks_like_phone(raw):
            await message.answer("Похоже, это не телефон. Напишите номер ещё раз (минимум 10 цифр).")
            return

        phone = normalize_phone(raw)
        data = await state.get_data()
        print("🧾 state data:", data)

        audience = data.get("audience", "—")
        lang = data.get("lang", "—")
        goal = data.get("goal", "—")
        name = data.get("name", "—")

        user = message.from_user
        username = f"@{user.username}" if user and user.username else "—"
        user_id = user.id if user else "—"
        when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lead_text = (
            "🟢 Новая заявка\n"
            f"Кто: {audience}\n"
            f"Язык: {lang}\n"
            f"Цель: {goal}\n"
            f"Имя: {name}\n"
            f"Телефон: {phone}\n"
            f"Пользователь: {username} (id {user_id})\n"
            f"Время: {when}"
        )

        print("➡️ sending to admin chat:", ADMIN_CHAT_ID)

        if ADMIN_CHAT_ID != 0:
            await bot.send_message(ADMIN_CHAT_ID, lead_text)
            await message.answer("Спасибо! Заявка отправлена ✅ Мы свяжемся с вами в ближайшее время.")
        else:
            await message.answer(
                "Заявка собрана ✅\n"
                "Но ADMIN_CHAT_ID ещё не задан.\n"
                "Добавьте бота в чат менеджеров и в этом чате напишите /chatid — бот покажет id.\n"
                "Потом внесите ADMIN_CHAT_ID в .env / Render Variables."
            )

        await state.clear()

    except Exception as e:
        print("❌ ERROR in get_phone:", repr(e))
        await message.answer("Произошла ошибка при обработке заявки ❌. Проверь логи Render.")


# Покажет chat_id чата (в группе/супергруппе тоже)
@dp.message(Command("chatid"))
async def chatid(message: Message):
    await message.answer(f"chat_id этого чата: {message.chat.id}")


# Проверка, что бот реально может писать в админ-чат
@dp.message(Command("pingadmin"))
async def pingadmin(message: Message):
    if ADMIN_CHAT_ID == 0:
        await message.answer("ADMIN_CHAT_ID не задан. Сначала поставь его в переменных окружения.")
        return
    try:
        await bot.send_message(ADMIN_CHAT_ID, "✅ Тест: бот может писать в этот чат")
        await message.answer("Ок, отправил тест в админ-чат ✅")
    except Exception as e:
        print("❌ pingadmin error:", repr(e))
        await message.answer(f"Не смог отправить в админ-чат ❌\n{repr(e)}")


async def main():
    print("🚀 Bot started. ADMIN_CHAT_ID =", ADMIN_CHAT_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
