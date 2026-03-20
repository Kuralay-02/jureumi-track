from collections import defaultdict
import json
import os

import gspread
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

API_TOKEN = "8620495714:AAGO07coxFdIQ8YbCrAEbBMw-KBp0FaHlRM"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# 🔥 подключение к Google Sheets через Railway
creds_dict = json.loads(os.environ["CREDS_JSON"])
gc = gspread.service_account_from_dict(creds_dict)

spreadsheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1rOSfytA_8YhPGSYbMCCk8lVTydhwQrRqXMkif3L00x0/edit?usp=sharing")

sheet_kor = spreadsheet.worksheet("Корейские Разборы")
sheet_kit = spreadsheet.worksheet("Китайские Разборы")
sheet_yap = spreadsheet.worksheet("Японские Разборы")

# кнопка
keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
keyboard.add(KeyboardButton("🔍 Где мои разборы?"))

# старт
@dp.message_handler(commands=['start'])
async def start(message: Message):
    await message.answer(
        "Привет! Я бот для отслеживания статуса ваших разборов 📦\n\n"
        "Могу помочь тебе легко отслеживать свои разборы.\n\n"
        "Для этого тебе необходимо нажать на кнопку «Где мои разборы?» 🔎",
        reply_markup=keyboard
    )

# кнопка
@dp.message_handler(lambda message: message.text == "🔍 Где мои разборы?")
async def ask_username(message: Message):
    await message.answer("Отправь свой @username (например: @teplo)")

# поиск
@dp.message_handler()
async def search_user(message: Message):
    text = message.text.strip().lower()

    if not text.startswith("@"):
        await message.answer("Пожалуйста, отправь username в формате @username")
        return

    def get_data(sheet):
        return [
            row for row in sheet.get_all_records()
            if row["Ник в тг"].lower().strip() == text
        ]

    kor_rows = get_data(sheet_kor)
    kit_rows = get_data(sheet_kit)
    yap_rows = get_data(sheet_yap)

    if not (kor_rows or kit_rows or yap_rows):
        await message.answer("Ничего не найдено 😢")
        return

    result = "📦 Твои разборы:\n\n"

    def format_block(title, rows):
        if not rows:
            return ""

        grouped = defaultdict(list)

        for row in rows:
            grouped[row["Номер разбора"]].append(row)

        text_block = f"{title}\n"

        for box, items in grouped.items():
            text_block += f"{box}\n"

            for item in items:
                text_block += f"— {item['Название позиции']}\n"
                text_block += f"Статус: {item['Статус']}\n"

                if item["Примечания"]:
                    text_block += f"Примечание: {item['Примечания']}\n"

                text_block += "\n"

        return text_block

    result += format_block("🇰🇷 Корейские разборы\n", kor_rows)
    result += format_block("🇨🇳 Китайские разборы\n", kit_rows)
    result += format_block("🇯🇵 Японские разборы\n", yap_rows)

    await message.answer(result)


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
