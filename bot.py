import hashlib
import hmac
import json
import logging
import os
import time
from html import escape
from urllib.parse import parse_qsl, urlsplit

from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MANAGER_CHAT_ID_RAW = os.getenv("MANAGER_CHAT_ID", "").strip()
WEBAPP_URL = os.getenv(
    "WEBAPP_URL", "https://venda-catalog.onrender.com/"
).strip()
RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL", "https://venda-bot.onrender.com"
).rstrip("/")
SITE_URL = "https://vendaaroma.ru/"

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")

try:
    MANAGER_CHAT_ID = int(MANAGER_CHAT_ID_RAW)
except ValueError as exc:
    raise RuntimeError(
        "MANAGER_CHAT_ID должен быть числовым Telegram chat_id менеджера"
    ) from exc

webapp_parts = urlsplit(WEBAPP_URL)
WEBAPP_ORIGIN = f"{webapp_parts.scheme}://{webapp_parts.netloc}"
if webapp_parts.scheme != "https" or not webapp_parts.netloc:
    raise RuntimeError("WEBAPP_URL должен быть корректным адресом HTTPS")

WEBHOOK_PATH = f"/bot/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[WEBAPP_ORIGIN],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class OrderItem(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    volume: str = Field(min_length=1, max_length=100)
    price: int = Field(gt=0, le=10_000_000)
    count: int = Field(gt=0, le=10_000)


class OrderPayload(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=100)
    comment: str = Field(default="", max_length=1000)
    items: list[OrderItem] = Field(min_length=1, max_length=100)


def validate_telegram_init_data(init_data: str) -> dict:
    """Проверяет подпись initData по официальному алгоритму Telegram."""
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", None)
    if not received_hash:
        raise ValueError("В initData отсутствует hash")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Неверная подпись initData")

    try:
        auth_date = int(values.get("auth_date", "0"))
    except ValueError as exc:
        raise ValueError("Некорректный auth_date") from exc

    if auth_date <= 0 or abs(time.time() - auth_date) > 24 * 60 * 60:
        raise ValueError("Данные авторизации Telegram устарели")

    try:
        user = json.loads(values["user"])
        user["id"] = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("В initData отсутствуют данные пользователя") from exc

    return user


def build_manager_message(payload: OrderPayload, user: dict) -> tuple[str, int]:
    calculated_total = 0
    item_lines = []
    for idx, item in enumerate(payload.items, 1):
        item_sum = item.price * item.count
        calculated_total += item_sum
        item_lines.append(
            f"{idx}. <b>{escape(item.title)}</b> ({escape(item.volume)}) — "
            f"{item.count} шт. × {item.price} ₽ = <b>{item_sum} ₽</b>"
        )

    username = str(user.get("username") or "").strip()
    username_text = f"@{escape(username)}" if username else "Username не задан"
    comment = payload.comment.strip() or "—"
    items_text = "\n".join(item_lines)

    message = (
        "🛍 <b>НОВЫЙ ЗАКАЗ VENDA!</b>\n"
        "──────────────────\n"
        f"👤 <b>Клиент:</b> {escape(payload.name.strip())}\n"
        f"📱 <b>Телефон:</b> <code>{escape(payload.phone.strip())}</code>\n"
        f"✈️ <b>Профиль ТГ:</b> {username_text}\n"
        f"🆔 <b>Telegram ID:</b> <code>{user['id']}</code>\n"
        f"💬 <b>Комментарий:</b> {escape(comment)}\n"
        "──────────────────\n"
        "📦 <b>Состав заказа:</b>\n\n"
        f"{items_text}\n\n"
        f"💰 <b>ИТОГО К ОПЛАТЕ: {calculated_total} ₽</b>"
    )
    return message, calculated_total


def catalog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🛍 Открыть каталог и заказать",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]]
    )


@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await message.answer(
        "Каталог обновлён. Используйте кнопку под следующим сообщением.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        f"Здравствуйте, {escape(message.from_user.first_name)}! 👋\n\n"
        "Добро пожаловать в магазин косметических отдушек <b>VENDA</b>.\n\n"
        "Откройте каталог, выберите нужные объёмы и оформите заказ.",
        reply_markup=catalog_keyboard(),
        parse_mode="HTML",
    )


@dp.message(Command("catalog"))
async def catalog_cmd(message: types.Message):
    await message.answer(
        "🛍 Каталог",
        reply_markup=catalog_keyboard(),
    )


@dp.message(Command("site"))
async def site_cmd(message: types.Message):
    await message.answer(SITE_URL)


@app.post("/api/order")
async def create_order(payload: OrderPayload):
    try:
        user = validate_telegram_init_data(payload.init_data)
    except ValueError as exc:
        logger.warning("Заказ с некорректной подписью Telegram: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    manager_message, calculated_total = build_manager_message(payload, user)

    try:
        await bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text=manager_message,
            parse_mode="HTML",
        )
    except TelegramForbiddenError as exc:
        logger.exception("Менеджер не запустил бота или заблокировал его")
        raise HTTPException(
            status_code=502,
            detail="Менеджер должен открыть бота и нажать /start",
        ) from exc
    except TelegramBadRequest as exc:
        logger.exception("Telegram отклонил MANAGER_CHAT_ID")
        raise HTTPException(
            status_code=502,
            detail="Telegram не нашёл чат менеджера. Проверьте MANAGER_CHAT_ID",
        ) from exc
    except Exception as exc:
        logger.exception("Не удалось отправить заказ менеджеру")
        raise HTTPException(
            status_code=502,
            detail="Telegram временно не принял заказ. Попробуйте ещё раз",
        ) from exc

    try:
        await bot.send_message(
            chat_id=user["id"],
            text=(
                f"✅ <b>Спасибо, {escape(payload.name.strip())}! "
                "Ваш заказ принят.</b>\n\n"
                f"Сумма заказа: <b>{calculated_total} ₽</b>\n"
                "Менеджер свяжется с вами для подтверждения."
            ),
            parse_mode="HTML",
        )
    except Exception:
        # Менеджер уже получил заказ, поэтому не возвращаем ошибку покупателю.
        logger.exception("Заказ принят, но подтверждение покупателю не отправлено")

    logger.info(
        "Заказ успешно отправлен менеджеру: buyer_id=%s total=%s",
        user["id"],
        calculated_total,
    )
    return {"ok": True, "total": calculated_total}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def on_startup():
    await bot.set_my_commands([
        BotCommand(command="catalog", description="Каталог"),
        BotCommand(command="site", description="Сайт"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Команды меню и вебхук успешно установлены")


@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    json_update = await request.json()
    update = types.Update.model_validate(json_update, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}
