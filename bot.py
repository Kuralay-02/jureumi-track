from collections import defaultdict
import json
import os

import gspread
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

API_TOKEN = os.environ["BOT_TOKEN"]

# 👉 ВСТАВЬ СВОЙ USERNAME БЕЗ @
ADMIN_ID = 635801439

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Google Sheets
creds_dict = json.loads(os.environ["CREDS_JSON"])
gc = gspread.service_account_from_dict(creds_dict)

spreadsheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1rOSfytA_8YhPGSYbMCCk8lVTydhwQrRqXMkif3L00x0/edit?usp=sharing")

sheet_kor = spreadsheet.worksheet("Корейские Разборы")
sheet_kit = spreadsheet.worksheet("Китайские Разборы")
sheet_yap = spreadsheet.worksheet("Японские Разборы")

# 📦 база пользователей (кто писал боту)
users = {}

# кнопки
main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(KeyboardButton("🔍 Где мои разборы?"))

admin_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
admin_keyboard.add(KeyboardButton("📢 Разослать обновление"))
admin_keyboard.add(KeyboardButton("👥 Список пользователей"))

check_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
check_keyboard.add(KeyboardButton("📦 Проверить статус"))

# старт
@dp.message_handler(commands=['start'])
async def start(message: Message):
    username = message.from_user.username

    users[message.from_user.id] = message.from_user.username

    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "Ты админ 👑",
            reply_markup=admin_keyboard
        )
    else:
        await message.answer(
            "Привет! Я бот для отслеживания статуса ваших разборов 📦\n\n"
            "Нажми кнопку ниже 👇",
            reply_markup=main_keyboard
        )

# админ кнопка
@dp.message_handler(lambda message: message.text == "📢 Разослать обновление")
async def notify_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    success = 0
    failed = 0

    for user_id in users:
        try:
            await bot.send_message(
                chat_id=user_id,
                text="📢 Есть обновления в таблице!\n\nПроверь статус своих разборов 👇",
                reply_markup=check_keyboard
            )
        except:
            pass

    await message.answer(
        f"📊 <b>Рассылка завершена</b>\n\n"
        f"✅ Отправлено: {success}\n"
        f"❌ Ошибки: {failed}",
        parse_mode="HTML"
    )
    
@dp.message_handler(lambda message: message.text == "👥 Список пользователей")
async def show_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    if not users:
        await message.answer("Список пуст")
        return

    text = f"👥 <b>Пользователи ({len(users)}):</b>\n\n"

    for i, (user_id, username) in enumerate(users.items(), 1):
        if username:
            text += f"{i}. @{username}\n"
        else:
            text += f"{i}. ID: {user_id}\n"

    await message.answer(text, parse_mode="HTML")

# кнопка проверки
@dp.message_handler(lambda message: message.text == "📦 Проверить статус")
async def ask_username(message: Message):
    await message.answer("Отправь свой username (например teplo или @teplo)")

# старая кнопка
@dp.message_handler(lambda message: message.text == "🔍 Где мои разборы?")
async def ask_username2(message: Message):
    await message.answer("Отправь свой username (например teplo или @teplo)")

# поиск
@dp.message_handler()
async def search_user(message: Message):
    text = message.text.replace("@", "").lower().strip()

    def get_data(sheet):
        return [
            row for row in sheet.get_all_records()
            if row["Ник в тг"].replace("@", "").lower().strip() == text
        ]

    kor_rows = get_data(sheet_kor)
    kit_rows = get_data(sheet_kit)
    yap_rows = get_data(sheet_yap)

    if not (kor_rows or kit_rows or yap_rows):
        await message.answer("😔 Ничего не найдено\n\nПроверь правильность username")
        return

    result = "📦 <b>ТВОИ РАЗБОРЫ</b>\n\n"

    def format_block(title, rows):
        if not rows:
            return ""

        grouped = defaultdict(list)

        for row in rows:
            grouped[row["Номер разбора"]].append(row)

        text_block = f"{title}\n────────────\n\n"

        for box, items in grouped.items():
            text_block += f"📦 <b>{box}</b>\n"

            for item in items:
                text_block += f"• <b>{item['Название позиции']}</b>\n"
                text_block += f"   └ 📍 {item['Статус']}\n"

                if item["Примечания"]:
                    text_block += f"   └ 💬 {item['Примечания']}\n"

                text_block += "\n"

            text_block += "────────────\n\n"

        return text_block

    result += format_block("🇰🇷 Корейские разборы\n", kor_rows)
    result += format_block("🇨🇳 Китайские разборы\n", kit_rows)
    result += format_block("🇯🇵 Японские разборы\n", yap_rows)

    await message.answer(result, parse_mode="HTML")


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
