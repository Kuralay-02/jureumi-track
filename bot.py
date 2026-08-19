from collections import defaultdict
import asyncio
import html
import json
import os
import time

import gspread
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from gspread.exceptions import APIError


API_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = 635801439

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)


# =========================================================
# НАСТРОЙКИ
# =========================================================

CACHE_SECONDS = 300  # 5 минут

# Таблица с разборами — ссылка берётся из Railway Variables
BOXES_SPREADSHEET_URL = os.environ["TRACK_SPREADSHEET_URL"]

# Таблица пользователей — ссылка берётся из Railway Variables
USERS_SPREADSHEET_URL = os.environ["USERS_SPREADSHEET_URL"]


# =========================================================
# GOOGLE SHEETS
# =========================================================

creds_dict = json.loads(os.environ["CREDS_JSON"])
gc = gspread.service_account_from_dict(creds_dict)

spreadsheet = gc.open_by_url(BOXES_SPREADSHEET_URL)

sheet_kor = spreadsheet.worksheet("Корейские Разборы")
sheet_kit = spreadsheet.worksheet("Китайские Разборы")
sheet_yap = spreadsheet.worksheet("Японские Разборы")

users_spreadsheet = gc.open_by_url(USERS_SPREADSHEET_URL)
users_sheet = users_spreadsheet.worksheet("Пользователи")


# =========================================================
# КЭШ РАЗБОРОВ
# =========================================================

boxes_cache = {
    "kor": [],
    "kit": [],
    "yap": [],
}

boxes_cache_time = 0

# Не даём нескольким пользователям одновременно
# обновлять кэш из Google
boxes_cache_lock = asyncio.Lock()


def read_sheet_records(sheet):
    """
    Читает лист Google Sheets.
    При 429 делает несколько попыток.
    """

    attempts = 3

    for attempt in range(attempts):
        try:
            return sheet.get_all_records()

        except APIError as e:
            print(f"Ошибка Google Sheets: {e}")

            if attempt == attempts - 1:
                raise

            time.sleep(3 * (attempt + 1))

    return []


async def refresh_boxes_cache(force=False):
    """
    Загружает три листа разборов максимум раз в 5 минут.
    """

    global boxes_cache_time

    now = time.monotonic()

    if (
        not force
        and boxes_cache_time
        and now - boxes_cache_time < CACHE_SECONDS
    ):
        return True

    async with boxes_cache_lock:

        now = time.monotonic()

        if (
            not force
            and boxes_cache_time
            and now - boxes_cache_time < CACHE_SECONDS
        ):
            return True

        try:
            kor = await asyncio.to_thread(
                read_sheet_records,
                sheet_kor
            )

            kit = await asyncio.to_thread(
                read_sheet_records,
                sheet_kit
            )

            yap = await asyncio.to_thread(
                read_sheet_records,
                sheet_yap
            )

            boxes_cache["kor"] = kor
            boxes_cache["kit"] = kit
            boxes_cache["yap"] = yap

            boxes_cache_time = time.monotonic()

            print(
                "Кэш разборов обновлён: "
                f"Корея {len(kor)}, "
                f"Китай {len(kit)}, "
                f"Япония {len(yap)}"
            )

            return True

        except Exception as e:
            print(f"Не удалось обновить кэш разборов: {e}")

            return bool(
                boxes_cache["kor"]
                or boxes_cache["kit"]
                or boxes_cache["yap"]
            )


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

users_cache = {}
users_loaded = False
users_lock = asyncio.Lock()


def read_users_from_sheet():
    """
    Читает актуальный список пользователей из таблицы.
    """

    users = {}

    rows = read_sheet_records(users_sheet)

    for row in rows:

        user_id = row.get("Telegram ID")
        username = row.get("Username", "")

        if not user_id:
            continue

        try:
            user_id = int(user_id)

        except (ValueError, TypeError):
            continue

        users[user_id] = str(
            username or ""
        ).strip()

    return users


async def refresh_users():
    """
    ПРИНУДИТЕЛЬНО перечитывает актуальный список
    пользователей из Google Sheets.

    Используется перед рассылкой и перед показом
    списка пользователей.
    """

    global users_cache
    global users_loaded

    async with users_lock:

        try:

            loaded_users = await asyncio.to_thread(
                read_users_from_sheet
            )

            users_cache = loaded_users
            users_loaded = True

            print(
                "Список пользователей обновлён: "
                f"{len(users_cache)}"
            )

            return True

        except Exception as e:

            print(
                "Ошибка обновления списка "
                f"пользователей: {e}"
            )

            return False


async def ensure_users_loaded():
    """
    Для обычной работы загружает пользователей
    только при необходимости.

    Перед рассылкой и просмотром списка используется
    refresh_users(), поэтому там всегда свежие данные.
    """

    global users_loaded
    global users_cache

    if users_loaded:
        return True

    return await refresh_users()


def append_user_to_sheet(user_id, username):

    users_sheet.append_row(
        [str(user_id), username],
        value_input_option="USER_ENTERED"
    )


def update_username_in_sheet(user_id, username):
    """
    Обновляет username существующего Telegram ID.
    """

    values = users_sheet.get_all_values()

    for row_number, row in enumerate(
        values[1:],
        start=2
    ):

        if not row:
            continue

        existing_id = str(
            row[0]
        ).strip()

        if existing_id == str(user_id):

            users_sheet.update_cell(
                row_number,
                2,
                username
            )

            return


async def save_user(user_id, username):
    """
    Сохраняет нового пользователя.

    Если пользователь уже есть — дубль не создаёт.
    Если username изменился — обновляет его.
    """

    username = username or ""

    loaded = await ensure_users_loaded()

    if not loaded:
        return

    existing_username = users_cache.get(
        user_id
    )

    # Пользователь уже есть,
    # username не изменился
    if (
        user_id in users_cache
        and existing_username == username
    ):
        return

    # Новый пользователь
    if user_id not in users_cache:

        try:

            await asyncio.to_thread(
                append_user_to_sheet,
                user_id,
                username
            )

            users_cache[user_id] = username

            print(
                f"Добавлен пользователь: "
                f"{user_id} @{username}"
            )

        except Exception as e:

            print(
                "Ошибка сохранения пользователя "
                f"{user_id}: {e}"
            )

        return

    # Пользователь поменял username
    try:

        await asyncio.to_thread(
            update_username_in_sheet,
            user_id,
            username
        )

        users_cache[user_id] = username

        print(
            "Обновлён username пользователя "
            f"{user_id}: @{username}"
        )

    except Exception as e:

        print(
            "Ошибка обновления username "
            f"{user_id}: {e}"
        )


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def get_keyboard(is_admin=False):

    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.add(
        KeyboardButton(
            "🔍 Где мои разборы?"
        )
    )

    if is_admin:

        keyboard.row(
            KeyboardButton(
                "📢 Разослать обновление"
            ),
            KeyboardButton(
                "👥 Список пользователей"
            )
        )

    return keyboard


check_keyboard = ReplyKeyboardMarkup(
    resize_keyboard=True
)

check_keyboard.add(
    KeyboardButton(
        "📦 Проверить статус"
    )
)


# =========================================================
# ДЛИННЫЕ СООБЩЕНИЯ
# =========================================================

async def send_long_message(
    message,
    blocks,
    keyboard
):

    max_length = 3900

    chunks = []
    current_chunk = ""

    for block in blocks:

        if len(block) > max_length:

            if current_chunk:
                chunks.append(
                    current_chunk
                )
                current_chunk = ""

            lines = block.split("\n")
            temp = ""

            for line in lines:

                line_with_break = (
                    line + "\n"
                )

                if (
                    len(temp)
                    + len(line_with_break)
                    > max_length
                ):

                    if temp:
                        chunks.append(temp)

                    temp = line_with_break

                else:
                    temp += line_with_break

            if temp:
                chunks.append(temp)

            continue

        if (
            len(current_chunk)
            + len(block)
            > max_length
        ):

            if current_chunk:
                chunks.append(
                    current_chunk
                )

            current_chunk = block

        else:
            current_chunk += block

    if current_chunk:
        chunks.append(
            current_chunk
        )

    for i, chunk in enumerate(
        chunks
    ):

        await message.answer(
            chunk,
            parse_mode="HTML",
            reply_markup=(
                keyboard
                if i == len(chunks) - 1
                else None
            )
        )


# =========================================================
# /START
# =========================================================

@dp.message_handler(
    commands=["start"]
)
async def start(message: Message):

    await save_user(
        message.from_user.id,
        message.from_user.username
    )

    is_admin = (
        message.from_user.id
        == ADMIN_ID
    )

    await message.answer(
        "Привет! Я бот для отслеживания "
        "статуса ваших разборов 📦\n\n"
        "Нажми кнопку ниже 👇",
        reply_markup=get_keyboard(
            is_admin
        )
    )


# =========================================================
# РАССЫЛКА
# =========================================================

@dp.message_handler(
    lambda message:
    message.text
    == "📢 Разослать обновление"
)
async def notify_users(
    message: Message
):

    if (
        message.from_user.id
        != ADMIN_ID
    ):
        return

    # ВАЖНО:
    # непосредственно перед каждой рассылкой
    # заново читаем таблицу пользователей.
    loaded = await refresh_users()

    if not loaded:

        await message.answer(
            "⚠️ Сейчас не удалось получить "
            "актуальный список пользователей "
            "из таблицы.",
            reply_markup=get_keyboard(True)
        )

        return

    if not users_cache:

        await message.answer(
            "Пользователей для рассылки "
            "пока нет.",
            reply_markup=get_keyboard(True)
        )

        return

    success = 0
    failed = 0

    for user_id in list(
        users_cache.keys()
    ):

        try:

            await bot.send_message(
                chat_id=user_id,
                text=(
                    "📢 Есть обновления "
                    "в таблице!\n\n"
                    "Проверь статус своих "
                    "разборов 👇"
                ),
                reply_markup=check_keyboard
            )

            success += 1

        except Exception as e:

            failed += 1

            print(
                "Не удалось отправить "
                f"сообщение {user_id}: {e}"
            )

        # Небольшая пауза между сообщениями
        await asyncio.sleep(0.05)

    await message.answer(
        "📊 <b>Рассылка завершена</b>\n\n"
        f"👥 Всего пользователей: "
        f"{len(users_cache)}\n"
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
    message.text
    == "👥 Список пользователей"
)
async def show_users(
    message: Message
):

    if (
        message.from_user.id
        != ADMIN_ID
    ):
        return

    # ВАЖНО:
    # при каждом нажатии читаем таблицу заново.
    loaded = await refresh_users()

    if not loaded:

        await message.answer(
            "⚠️ Сейчас не удалось загрузить "
            "актуальный список пользователей.",
            reply_markup=get_keyboard(True)
        )

        return

    if not users_cache:

        await message.answer(
            "Список пользователей пуст.",
            reply_markup=get_keyboard(True)
        )

        return

    lines = [
        (
            f"👥 <b>Пользователи "
            f"({len(users_cache)}):</b>"
        ),
        ""
    ]

    for i, (
        user_id,
        username
    ) in enumerate(
        users_cache.items(),
        start=1
    ):

        if username:

            safe_username = html.escape(
                username
            )

            lines.append(
                f"{i}. @{safe_username}"
            )

        else:

            lines.append(
                f"{i}. ID: {user_id}"
            )

    chunks = []
    current = ""

    for line in lines:

        new_line = line + "\n"

        if (
            len(current)
            + len(new_line)
            > 3900
        ):

            if current:
                chunks.append(current)

            current = new_line

        else:
            current += new_line

    if current:
        chunks.append(current)

    for i, chunk in enumerate(
        chunks
    ):

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
async def ask_username(
    message: Message
):

    await message.answer(
        "Отправь свой username "
        "(например teplo или @teplo)"
    )


# =========================================================
# ПОИСК
# =========================================================

@dp.message_handler()
async def search_user(
    message: Message
):

    # Если человек ещё не был сохранён —
    # добавляем его в таблицу пользователей.
    await save_user(
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

    # Разборы по-прежнему кэшируются
    # на 5 минут.
    cache_available = (
        await refresh_boxes_cache()
    )

    if not cache_available:

        await message.answer(
            "⚠️ Google Таблицы временно "
            "недоступны.\n\n"
            "Попробуй проверить разборы "
            "чуть позже.",
            reply_markup=get_keyboard(
                message.from_user.id
                == ADMIN_ID
            )
        )

        return

    def get_data(rows):

        result = []

        for row in rows:

            username = str(
                row.get(
                    "Ник в тг",
                    ""
                )
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

    kor_rows = get_data(
        boxes_cache["kor"]
    )

    kit_rows = get_data(
        boxes_cache["kit"]
    )

    yap_rows = get_data(
        boxes_cache["yap"]
    )

    if not (
        kor_rows
        or kit_rows
        or yap_rows
    ):

        await message.answer(
            "😔 Ничего не найдено\n\n"
            "Проверь правильность username",
            reply_markup=get_keyboard(
                message.from_user.id
                == ADMIN_ID
            )
        )

        return

    blocks = [
        "📦 <b>ТВОИ РАЗБОРЫ</b>\n\n"
    ]

    def format_blocks(
        title,
        rows
    ):

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

        for box, items in (
            grouped.items()
        ):

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
            message.from_user.id
            == ADMIN_ID
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
