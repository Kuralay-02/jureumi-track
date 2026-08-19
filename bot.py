from collections import defaultdict
import json
import os
import html

import gspread
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

API_TOKEN = os.environ["BOT_TOKEN"]

ADMIN_ID = 635801439

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# =========================================================
# GOOGLE SHEETS
# =========================================================

creds_dict = json.loads(os.environ["CREDS_JSON"])
gc = gspread.service_account_from_dict(creds_dict)

# Таблица с разборами
spreadsheet = gc.open_by_url(
    "https://docs.google.com/spreadsheets/d/1rOSfytA_8YhPGSYbMCCk8lVTydhwQrRqXMkif3L00x0/edit?usp=sharing"
)

sheet_kor = spreadsheet.worksheet("Корейские Разборы")
sheet_kit = spreadsheet.worksheet("Китайские Разборы")
sheet_yap = spreadsheet.worksheet("Японские Разборы")


# Отдельная таблица пользователей
users_spreadsheet = gc.open_by_url(
    "https://docs.google.com/spreadsheets/d/11WQBVHNEnmfi2_XaFxZrBTr_o5OeDPcC8yYSnPoe6JI/edit?usp=sharing"
)

users_sheet = users_spreadsheet.worksheet("Пользователи")


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

def get_users():
    """
    Получаем всех пользователей из таблицы.
    Возвращает:
    {
        telegram_id: username
    }
    """

    users = {}

    try:
        rows = users_sheet.get_all_records()

        for row in rows:
            user_id = row.get("Telegram ID")
            username = row.get("Username", "")

            if not user_id:
                continue

            try:
                user_id = int(user_id)
            except (ValueError, TypeError):
                continue

            users[user_id] = str(username or "").strip()

    except Exception as e:
        print(f"Ошибка чтения пользователей: {e}")

    return users


def save_user(user_id, username):
    """
    Добавляет нового пользователя.
    Если Telegram ID уже существует —
    обновляет username при необходимости.
    """

    username = username or ""

    try:
        rows = users_sheet.get_all_values()

        # Если таблица вообще пустая
        if not rows:
            users_sheet.append_row(
                ["Telegram ID", "Username"],
                value_input_option="USER_ENTERED"
            )
            rows = [["Telegram ID", "Username"]]

        # Ищем пользователя по Telegram ID
        for row_number, row in enumerate(rows[1:], start=2):

            if not row:
                continue

            existing_id = str(row[0]).strip()

            if existing_id == str(user_id):

                existing_username = ""

                if len(row) > 1:
                    existing_username = str(row[1]).strip()

                # Если username изменился — обновляем
                if existing_username != username:
                    users_sheet.update_cell(
                        row_number,
                        2,
                        username
                    )

                return

        # Если пользователя ещё нет
        users_sheet.append_row(
            [str(user_id), username],
            value_input_option="USER_ENTERED"
        )

    except Exception as e:
        print(f"Ошибка сохранения пользователя {user_id}: {e}")


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def get_keyboard(is_admin=False):
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.add(
        KeyboardButton("🔍 Где мои разборы?")
    )

    if is_admin:
        keyboard.row(
            KeyboardButton("📢 Разослать обновление"),
            KeyboardButton("👥 Список пользователей")
        )

    return keyboard


# Отдельная кнопка после рассылки
check_keyboard = ReplyKeyboardMarkup(
    resize_keyboard=True
)

check_keyboard.add(
    KeyboardButton("📦 Проверить статус")
)


# =========================================================
# БЕЗОПАСНАЯ ОТПРАВКА ДЛИННЫХ СООБЩЕНИЙ
# =========================================================

async def send_long_message(message, blocks, keyboard):
    """
    Отправляет длинный результат несколькими сообщениями,
    не разрывая HTML-теги посередине.
    """

    max_length = 3900

    chunks = []
    current_chunk = ""

    for block in blocks:

        # Если один блок сам по себе слишком большой
        if len(block) > max_length:

            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            lines = block.split("\n")
            temp = ""

            for line in lines:
                line_with_break = line + "\n"

                if len(temp) + len(line_with_break) > max_length:
                    if temp:
                        chunks.append(temp)

                    temp = line_with_break
                else:
                    temp += line_with_break

            if temp:
                chunks.append(temp)

            continue

        if len(current_chunk) + len(block) > max_length:

            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = block

        else:
            current_chunk += block

    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):

        await message.answer(
            chunk,
            parse_mode="HTML",
            reply_markup=keyboard if i == len(chunks) - 1 else None
        )


# =========================================================
# /START
# =========================================================

@dp.message_handler(commands=["start"])
async def start(message: Message):

    # Сохраняем пользователя в таблицу
    save_user(
        message.from_user.id,
        message.from_user.username
    )

    is_admin = message.from_user.id == ADMIN_ID

    # Админ получает то же приветствие,
    # просто с дополнительными кнопками
    await message.answer(
        "Привет! Я бот для отслеживания статуса ваших разборов 📦\n\n"
        "Нажми кнопку ниже 👇",
        reply_markup=get_keyboard(is_admin)
    )


# =========================================================
# РАССЫЛКА
# =========================================================

@dp.message_handler(
    lambda message:
    message.text == "📢 Разослать обновление"
)
async def notify_users(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    users = get_users()

    if not users:
        await message.answer(
            "Пользователей для рассылки пока нет.",
            reply_markup=get_keyboard(True)
        )
        return

    success = 0
    failed = 0

    for user_id in users:

        try:

            await bot.send_message(
                chat_id=user_id,
                text=(
                    "📢 Есть обновления в таблице!\n\n"
                    "Проверь статус своих разборов 👇"
                ),
                reply_markup=check_keyboard
            )

            success += 1

        except Exception as e:

            failed += 1

            print(
                f"Не удалось отправить сообщение "
                f"{user_id}: {e}"
            )

    await message.answer(
        f"📊 <b>Рассылка завершена</b>\n\n"
        f"👥 Всего пользователей: {len(users)}\n"
        f"✅ Получили: {success}\n"
        f"❌ Не получили: {failed}",
        parse_mode="HTML",
        reply_markup=get_keyboard(True)
    )


# =========================================================
# СПИСОК ПОЛЬЗОВАТЕЛЕЙ
# =========================================================

@dp.message_handler(
    lambda message:
    message.text == "👥 Список пользователей"
)
async def show_users(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    users = get_users()

    if not users:

        await message.answer(
            "Список пользователей пуст.",
            reply_markup=get_keyboard(True)
        )

        return

    lines = [
        f"👥 <b>Пользователи ({len(users)}):</b>",
        ""
    ]

    for i, (user_id, username) in enumerate(
        users.items(),
        start=1
    ):

        if username:
            safe_username = html.escape(username)

            lines.append(
                f"{i}. @{safe_username}"
            )

        else:
            lines.append(
                f"{i}. ID: {user_id}"
            )

    # Список тоже может быть длиннее лимита Telegram
    chunks = []
    current = ""

    for line in lines:

        new_line = line + "\n"

        if len(current) + len(new_line) > 3900:

            chunks.append(current)
            current = new_line

        else:
            current += new_line

    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):

        await message.answer(
            chunk,
            parse_mode="HTML",
            reply_markup=(
                get_keyboard(True)
                if i == len(chunks) - 1
                else None
            )
        )


# =========================================================
# КНОПКИ ПОИСКА
# =========================================================

@dp.message_handler(
    lambda message:
    message.text in [
        "📦 Проверить статус",
        "🔍 Где мои разборы?"
    ]
)
async def ask_username(message: Message):

    await message.answer(
        "Отправь свой username "
        "(например teplo или @teplo)"
    )


# =========================================================
# ПОИСК РАЗБОРОВ
# =========================================================

@dp.message_handler()
async def search_user(message: Message):

    # На всякий случай сохраняем человека,
    # даже если он уже был в таблице
    save_user(
        message.from_user.id,
        message.from_user.username
    )

    if not message.text:
        return

    text = (
        message.text
        .replace("@", "")
        .lower()
        .strip()
    )

    def get_data(sheet):

        result = []

        for row in sheet.get_all_records():

            username = str(
                row.get("Ник в тг", "")
            )

            normalized = (
                username
                .replace("@", "")
                .lower()
                .strip()
            )

            if normalized == text:
                result.append(row)

        return result


    kor_rows = get_data(sheet_kor)
    kit_rows = get_data(sheet_kit)
    yap_rows = get_data(sheet_yap)


    if not (
        kor_rows
        or kit_rows
        or yap_rows
    ):

        await message.answer(
            "😔 Ничего не найдено\n\n"
            "Проверь правильность username",
            reply_markup=get_keyboard(
                message.from_user.id == ADMIN_ID
            )
        )

        return


    # Каждый раздел делаем отдельным блоком.
    # Так HTML больше не разорвётся посередине тега.

    blocks = [
        "📦 <b>ТВОИ РАЗБОРЫ</b>\n\n"
    ]


    def format_blocks(title, rows):

        if not rows:
            return []

        grouped = defaultdict(list)

        for row in rows:

            box = str(
                row.get(
                    "Номер разбора",
                    "Без номера"
                )
            )

            grouped[box].append(row)


        result_blocks = [
            f"{title}\n"
            f"────────────\n\n"
        ]


        for box, items in grouped.items():

            safe_box = html.escape(
                str(box)
            )

            text_block = (
                f"📦 <b>{safe_box}</b>\n"
            )


            for item in items:

                name = html.escape(
                    str(
                        item.get(
                            "Название позиции",
                            ""
                        )
                    )
                )

                status = html.escape(
                    str(
                        item.get(
                            "Статус",
                            ""
                        )
                    )
                )

                note = html.escape(
                    str(
                        item.get(
                            "Примечания",
                            ""
                        )
                    )
                )


                text_block += (
                    f"• <b>{name}</b>\n"
                )

                text_block += (
                    f"   └ 📍 {status}\n"
                )


                if note:
                    text_block += (
                        f"   └ 💬 {note}\n"
                    )


                text_block += "\n"


            text_block += (
                "────────────\n\n"
            )


            result_blocks.append(
                text_block
            )


        return result_blocks


    blocks += format_blocks(
        "🇰🇷 <b>Корейские разборы</b>",
        kor_rows
    )

    blocks += format_blocks(
        "🇨🇳 <b>Китайские разборы</b>",
        kit_rows
    )

    blocks += format_blocks(
        "🇯🇵 <b>Японские разборы</b>",
        yap_rows
    )


    await send_long_message(
        message,
        blocks,
        get_keyboard(
            message.from_user.id == ADMIN_ID
        )
    )


# =========================================================
# ЗАПУСК
# =========================================================

if __name__ == "__main__":
    executor.start_polling(
        dp,
        skip_updates=True
    )
