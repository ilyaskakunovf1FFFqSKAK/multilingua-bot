import asyncio
import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv


# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))  # chat id группы менеджеров (может быть отрицательным)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty. Put it into .env / Render env vars")


# ================== BOT ==================
bot = Bot(BOT_TOKEN)  # parse_mode не задаём
dp = Dispatcher()

LANGS = ["Английский", "Французский", "Китайский", "Испанский", "Итальянский", "Турецкий"]
AUDIENCE = ["Мне есть 18 лет", "Мне нет 18 лет"]


class Lead(StatesGroup):
    audience = State()
    lang = State()
    goal = State()
    name = State()
    phone = State()


# ================== UI (постоянная кнопка) ==================
def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Записаться на пробный урок")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


WELCOME_TEXT = (
    "👋 Добро пожаловать в *MultiLingua School*!\n\n"
    "🌍 Подберём занятия под вашу цель и уровень.\n"
    "🎁 *Пробный урок* — чтобы познакомиться и выбрать формат.\n\n"
    "Нажмите кнопку ниже, чтобы записаться 👇"
)


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


async def safe_send_to_admin(text: str) -> tuple[bool, str]:
    """
    Пытается отправить в админ-чат.
    Возвращает (ok, message_for_user)
    """
    if ADMIN_CHAT_ID == 0:
        return False, (
            "ADMIN_CHAT_ID не задан.\n"
            "1) Добавь бота в чат менеджеров\n"
            "2) В этом чате напиши /chatid\n"
            "3) Поставь ADMIN_CHAT_ID в Render → Environment\n"
        )

    try:
        await bot.send_message(ADMIN_CHAT_ID, text)
        return True, "✅ Спасибо! Заявка отправлена. Мы свяжемся с вами в ближайшее время."
    except TelegramBadRequest as e:
        return False, (
            "Не смог отправить заявку в чат менеджеров ❌\n"
            f"Ошибка: {e}\n\n"
            "Проверь:\n"
            "• правильный ли ADMIN_CHAT_ID (у групп обычно отрицательный)\n"
            "• добавлен ли бот в чат менеджеров\n"
            "• есть ли у бота право отправлять сообщения"
        )
    except Exception as e:
        return False, f"Произошла ошибка отправки ❌ Проверь логи.\n{repr(e)}"


# ================== FLOW START ==================
async def start_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Кому нужны занятия?",
        reply_markup=kb(AUDIENCE, "aud", cols=1),
    )
    await state.set_state(Lead.audience)


# ================== HANDLERS ==================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    # Приветствие + постоянная кнопка
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu(), parse_mode="Markdown")


@dp.message(F.text == "🚀 Записаться на пробный урок")
async def register_button(message: Message, state: FSMContext):
    await start_flow(message, state)


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
    raw = (message.text or "").strip()

    if not looks_like_phone(raw):
        await message.answer("Похоже, это не телефон. Напишите номер ещё раз (минимум 10 цифр).")
        return

    phone = normalize_phone(raw)
    data = await state.get_data()

    user = message.from_user
    username = f"@{user.username}" if user and user.username else "—"
    user_id = user.id if user else "—"

    lead_text = (
        "🟢 Новая заявка\n"
        f"Кто: {data.get('audience', '—')}\n"
        f"Язык: {data.get('lang', '—')}\n"
        f"Цель: {data.get('goal', '—')}\n"
        f"Имя: {data.get('name', '—')}\n"
        f"Телефон: {phone}\n"
        f"Пользователь: {username} (id {user_id})\n"
        f"Время: {datetime.now():%Y-%m-%d %H:%M:%S}"
    )

    ok, msg = await safe_send_to_admin(lead_text)
    await message.answer(msg, reply_markup=main_menu())

    # очищаем стейт только если успешно обработали заявку
    if ok:
        await state.clear()


@dp.message(Command("chatid"))
async def chatid(message: Message):
    await message.answer(f"chat_id этого чата: {message.chat.id}")


@dp.message(Command("pingadmin"))
async def pingadmin(message: Message):
    ok, msg = await safe_send_to_admin("✅ Тест: бот может писать в этот чат")
    await message.answer("Ок ✅" if ok else msg, reply_markup=main_menu())


# ================== DUMMY SERVER FOR RENDER ==================
class DummyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


def run_dummy_server():
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()


# ================== MAIN ==================
async def main():
    print("🚀 Bot started. ADMIN_CHAT_ID =", ADMIN_CHAT_ID)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    asyncio.run(main())
