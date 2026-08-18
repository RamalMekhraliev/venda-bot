import asyncio
import json
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

# 1. Токен бота от @BotFather
BOT_TOKEN = "8997817506:AAHEweQKDjKsFh5UolU0ogG4cRY_DJmRTlQ"

# 2. Ваш ID Telegram от @userinfobot (куда приходят заказы)
MANAGER_CHAT_ID = 123456789 

# 3. Ссылка на опубликованный WebApp (инструкция ниже)
WEBAPP_URL = "https://ramalmekhraliev.github.io/venda-bot/"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    # Кнопка открытия витрины
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Открыть каталог и заказать", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    await message.answer(
        f"Здравствуйте, {message.from_user.first_name}! 👋\n\n"
        f"Добро пожаловать в парфюмерный магазин **VENDA**.\n\n"
        f"Нажмите кнопку ниже, чтобы открыть каталог, выбрать нужные объемы и оформить заказ.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# Обработка полученного заказа из WebApp
@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        
        user = message.from_user
        client_name = data.get("name", user.full_name)
        client_phone = data.get("phone", "Не указан")
        client_delivery = data.get("delivery", "Не указан")
        client_comment = data.get("comment", "—")
        items = data.get("items", [])
        total_sum = data.get("total", 0)

        # Формируем список товаров
        items_text = ""
        for idx, item in enumerate(items, 1):
            sum_item = item['price'] * item['count']
            items_text += f"{idx}. <b>{item['title']}</b> ({item['volume']}) — {item['count']} шт. × {item['price']} ₽ = <b>{sum_item} ₽</b>\n"

        username_str = f"@{user.username}" if user.username else "Username не задан"

        # Формируем сообщение менеджеру
        manager_msg = (
          f"🛍 <b>НОВЫЙ ЗАКАЗ VENDA!</b>\n"
          f"──────────────────\n"
          f"👤 <b>Клиент:</b> {client_name}\n"
          f"📱 <b>Телефон:</b> <code>{client_phone}</code>\n"
          f"✈️ <b>Профиль ТГ:</b> {username_str}\n"
          f"🚚 <b>Связь / Доставка:</b> {client_delivery}\n"
          f"💬 <b>Комментарий:</b> {client_comment}\n"
          f"──────────────────\n"
          f"📦 <b>Состав заказа:</b>\n\n"
          f"{items_text}\n"
          f"💰 <b>ИТОГО К ОПЛАТЕ: {total_sum} ₽</b>"
        )

        # Кнопка для мгновенного перехода в диалог с покупателем
        manager_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать покупателю", url=f"tg://user?id={user.id}")]
        ])

        # 1. Отправка менеджеру
        await bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text=manager_msg,
            parse_mode="HTML",
            reply_markup=manager_kb
        )

        # 2. Подтверждение покупателю
        await message.answer(
            f"✅ <b>Спасибо, {client_name}! Ваш заказ принят.</b>\n\n"
            f"Сумма заказа: <b>{total_sum} ₽</b>\n"
            f"Менеджер свяжется с вами в течение нескольких минут для подтверждения.",
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Ошибка при обработке заказа: {e}")
        await message.answer("⚠️ Произошла ошибка при отправке заказа. Пожалуйста, попробуйте ещё раз.")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
