import os
import json
import logging
from html import escape
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MANAGER_CHAT_ID_RAW = os.getenv("MANAGER_CHAT_ID", "").strip()
WEBAPP_URL = os.getenv(
    "WEBAPP_URL", "https://ramalmekhraliev.github.io/venda-bot/"
).strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")

try:
    MANAGER_CHAT_ID = int(MANAGER_CHAT_ID_RAW)
except ValueError as exc:
    raise RuntimeError(
        "MANAGER_CHAT_ID должен быть числовым Telegram chat_id менеджера"
    ) from exc

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://venda-bot.onrender.com")
WEBHOOK_PATH = f"/bot/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    # Telegram.WebApp.sendData() присылает web_app_data только для Mini App,
    # открытой через KeyboardButton в reply-клавиатуре.
    kb = ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="🛍 Открыть каталог и заказать",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]],
        resize_keyboard=True,
        is_persistent=True,
    )
    await message.answer(
        f"Здравствуйте, {escape(message.from_user.first_name)}! 👋\n\n"
        f"Добро пожаловать в магазин косметических отдушек <b>VENDA</b>.\n\n"
        f"Нажмите кнопку ниже, чтобы открыть каталог, выбрать нужные объемы и оформить заказ.",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        user = message.from_user
        client_name = str(data.get("name") or user.full_name).strip()
        client_phone = str(data.get("phone") or "").strip()
        client_comment = str(data.get("comment") or "—").strip()
        items = data.get("items", [])

        if not client_name or not client_phone:
            raise ValueError("Не указаны имя или телефон")
        if not isinstance(items, list) or not items:
            raise ValueError("Корзина пуста")

        normalized_items = []
        calculated_total = 0
        for idx, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise ValueError(f"Некорректный товар №{idx}")
            title = str(item.get("title") or "").strip()
            volume = str(item.get("volume") or "").strip()
            price = int(item.get("price", 0))
            count = int(item.get("count", 0))
            if not title or not volume or price <= 0 or count <= 0:
                raise ValueError(f"Некорректные данные товара №{idx}")
            calculated_total += price * count
            normalized_items.append((title, volume, price, count))

        items_text = ""
        for idx, (title, volume, price, count) in enumerate(normalized_items, 1):
            sum_item = price * count
            items_text += (
                f"{idx}. <b>{escape(title)}</b> ({escape(volume)}) — "
                f"{count} шт. × {price} ₽ = <b>{sum_item} ₽</b>\n"
            )

        username_str = f"@{escape(user.username)}" if user.username else "Username не задан"

        manager_msg = (
            f"🛍 <b>НОВЫЙ ЗАКАЗ VENDA!</b>\n"
            f"──────────────────\n"
            f"👤 <b>Клиент:</b> {escape(client_name)}\n"
            f"📱 <b>Телефон:</b> <code>{escape(client_phone)}</code>\n"
            f"✈️ <b>Профиль ТГ:</b> {username_str}\n"
            f"🆔 <b>Telegram ID:</b> <code>{user.id}</code>\n"
            f"💬 <b>Комментарий:</b> {escape(client_comment)}\n"
            f"──────────────────\n"
            f"📦 <b>Состав заказа:</b>\n\n"
            f"{items_text}\n"
            f"💰 <b>ИТОГО К ОПЛАТЕ: {calculated_total} ₽</b>"
        )

        try:
            await bot.send_message(
                chat_id=MANAGER_CHAT_ID,
                text=manager_msg,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            logger.exception(
                "Telegram отклонил сообщение менеджеру. Проверьте MANAGER_CHAT_ID"
            )
            raise

        await message.answer(
            f"✅ <b>Спасибо, {escape(client_name)}! Ваш заказ принят.</b>\n\n"
            f"Сумма заказа: <b>{calculated_total} ₽</b>\n"
            f"Менеджер свяжется с вами в течение нескольких минут для подтверждения.",
            parse_mode="HTML"
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.exception("Получены некорректные данные заказа")
        await message.answer("⚠️ Проверьте данные заказа и попробуйте ещё раз.")
    except Exception:
        logger.exception("Ошибка при обработке заказа")
        await message.answer("⚠️ Произошла ошибка при отправке заказа. Попробуйте еще раз.")

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Вебхук успешно установлен")

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    json_update = await request.json()
    update = types.Update.model_validate(json_update, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}
