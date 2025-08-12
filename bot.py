import logging
import sqlite3
import json
import os
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes, CallbackQueryHandler
)
import re
from config import TELEGRAM_TOKEN

# ====== Настройка логирования ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger=logging.getLogger(__name__)

# ====== Константы ======
EMOJI={
    "date": "🗓️",
    "role": "🛠️",
    "program": "📺",
    "time": "⏱️",
    "salary": "💰",
    "cancel": "❌",
    "edit": "✏️",
    "delete": "🗑️",
    "success": "✅",
    "warning": "⚠️",
    "info": "ℹ️"
}

NUM_PAD=[
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    [":", "0", "."],
    ["Пропустить", "Подтвердить"]
]

SKIP_BUTTON=["Пропустить"]
ROLE_BUTTONS=["РЕЖ", "ЭКРАНЫ", "EVS", "VMIX", "ОПЕРАТОР", "ОПЕРПОСТ", "СВЕТ", "ГРИМ"]
PROGRAM_BUTTONS=[
    "ЛЧ", "ЛЕ", "ЛК", "ЛИГА 1", "БУНДЕСЛИГА", "ММА",
    "КУБОГНЯ", "ФИГУРКА", "БИАТЛОН", "РПЛ", "LALIGA", "ТУРДЕФРАНС",
    "СВОЙ ВАРИАНТ"
]

# Состояния диалога
SELECT_DATE, SELECT_ROLE, SELECT_PROGRAM, TYPING_START, TYPING_END, TYPING_SALARY=range(6)


# ====== База данных ======
class ShiftDatabase:
    """Класс для работы с базой данных смен"""

    def __init__(self, db_path: str = "shifts.db"):
        self.db_path=db_path
        self.init_database()

    def init_database(self):
        """Инициализация базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS shifts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        date TEXT,
                        role TEXT,
                        program TEXT,
                        start_time TEXT,
                        end_time TEXT,
                        salary INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
            logger.info("База данных инициализирована")
        except Exception as e:
            logger.error(f"Ошибка при инициализации БД: {e}")
            raise

    def add_shift(self, user_id: str, shift_data: Dict[str, Any]) -> bool:
        """Добавление смены в базу данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO shifts (user_id, date, role, program, start_time, end_time, salary)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    shift_data.get('date').isoformat() if shift_data.get('date') else None,
                    shift_data.get('role'),
                    shift_data.get('program'),
                    shift_data.get('start_time'),
                    shift_data.get('end_time'),
                    shift_data.get('salary')
                ))
                conn.commit()
            logger.info(f"Смена добавлена для пользователя {user_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении смены: {e}")
            return False

    def get_user_shifts(self, user_id: str) -> List[Dict[str, Any]]:
        """Получение всех смен пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor=conn.execute('''
                    SELECT id, date, role, program, start_time, end_time, salary
                    FROM shifts WHERE user_id = ?
                    ORDER BY date DESC, start_time DESC
                ''', (user_id,))

                shifts=[]
                for row in cursor.fetchall():
                    shift={
                        'id': row[0],
                        'date': datetime.fromisoformat(row[1]).date() if row[1] else None,
                        'role': row[2],
                        'program': row[3],
                        'start_time': row[4],
                        'end_time': row[5],
                        'salary': row[6]
                    }
                    shifts.append(shift)
                return shifts
        except Exception as e:
            logger.error(f"Ошибка при получении смен: {e}")
            return []

    def delete_shift(self, user_id: str, shift_id: int) -> bool:
        """Удаление смены"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor=conn.execute('''
                    DELETE FROM shifts WHERE id = ? AND user_id = ?
                ''', (shift_id, user_id))
                conn.commit()
                return cursor.rowcount>0
        except Exception as e:
            logger.error(f"Ошибка при удалении смены: {e}")
            return False

    def update_shift(self, user_id: str, shift_id: int, field: str, value: Any) -> bool:
        """Обновление поля смены"""
        try:
            if field == 'date' and value:
                value=value.isoformat()

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(f'''
                    UPDATE shifts SET {field} = ? WHERE id = ? AND user_id = ?
                ''', (value, shift_id, user_id))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении смены: {e}")
            return False


# Создаем экземпляр базы данных
db=ShiftDatabase()


# ====== Вспомогательные функции ======
def create_keyboard(buttons: List[str], row_width: int = 3, skip_button: bool = True) -> ReplyKeyboardMarkup:
    """Создание клавиатуры из кнопок"""
    keyboard=[buttons[i:i + row_width] for i in range(0, len(buttons), row_width)]
    if skip_button:
        keyboard.append(SKIP_BUTTON)
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def clean_time_input(text: str) -> Optional[str]:
    """Очистка и форматирование времени"""
    if not text:
        return None

    digits=re.sub(r"[^\d]", "", text)
    if len(digits) == 4:
        return f"{digits[:2]}:{digits[2:]}"
    return None


def validate_time(time_str: str) -> bool:
    """Валидация времени"""
    if not time_str:
        return False

    try:
        hours, minutes=map(int, time_str.split(':'))
        return 0<=hours<24 and 0<=minutes<60
    except (ValueError, AttributeError):
        return False


def validate_date(date_obj: date) -> bool:
    """Валидация даты (не слишком далеко в прошлом или будущем)"""
    if not date_obj:
        return True

    today=date.today()
    # Разрешаем даты в диапазоне от 1 года назад до 1 года вперед
    min_date=today - timedelta(days=365)
    max_date=today + timedelta(days=365)

    return min_date<=date_obj<=max_date


def format_shift_display(shift: Dict[str, Any]) -> str:
    """Форматирование смены для отображения"""
    lines=[]

    if shift.get("date"):
        lines.append(f"{EMOJI['date']} {shift['date'].strftime('%d.%m.%Y')}")

    if shift.get("role"):
        lines.append(f"{EMOJI['role']} {shift['role']}")

    if shift.get("program"):
        lines.append(f"{EMOJI['program']} {shift['program']}")

    # Форматирование времени
    if shift.get("start_time") and shift.get("end_time"):
        lines.append(f"{EMOJI['time']} {shift['start_time']}–{shift['end_time']}")
    elif shift.get("start_time"):
        lines.append(f"{EMOJI['time']} с {shift['start_time']}")
    elif shift.get("end_time"):
        lines.append(f"{EMOJI['time']} до {shift['end_time']}")

    if shift.get("salary") is not None:
        lines.append(f"{EMOJI['salary']} {shift['salary']:,} ₽".replace(",", " "))

    return "\n".join(lines)


async def safe_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    """Безопасное удаление сообщения"""
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение {message_id}: {e}")


async def cleanup_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистка сообщений для удаления"""
    if "to_delete" not in context.user_data:
        return

    for msg_id in context.user_data["to_delete"]:
        await safe_delete_message(context, update.effective_chat.id, msg_id)

    context.user_data["to_delete"]=[]


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Получение главного меню"""
    return ReplyKeyboardMarkup([
        ["Начать смену", "Мои смены"],
        ["Экспорт данных", "Помощь"]
    ], resize_keyboard=True)


# ====== Обработчики команд ======
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - показ главного меню"""
    welcome_text=f"""
{EMOJI['success']} *Добро пожаловать в бот учета смен!*

Этот бот поможет тебе вести учет рабочих смен.

*Доступные функции:*
• Добавление новых смен
• Просмотр всех смен
• Редактирование и удаление
• Экспорт данных

Используй кнопки меню для навигации.
"""

    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


async def start_shift_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога добавления смены"""
    try:
        await cleanup_messages(update, context)
        context.user_data.clear()

        date_buttons=[
            ["Сегодня", "Завтра"],
            ["Послезавтра", "Вчера"],
            ["Своя дата", "Пропустить"]
        ]

        msg=await update.message.reply_text(
            f"{EMOJI['date']} Выбери дату смены:",
            reply_markup=ReplyKeyboardMarkup(date_buttons, resize_keyboard=True)
        )

        context.user_data["to_delete"]=[msg.message_id]
        logger.info(f"Пользователь {update.effective_user.id} начал добавление смены")
        return SELECT_DATE

    except Exception as e:
        logger.error(f"Ошибка в start_shift_creation: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка. Попробуйте еще раз.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END


async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора даты"""
    try:
        user_input=update.message.text.lower().strip()
        today=date.today()
        selected_date=None

        if "сегодня" in user_input:
            selected_date=today
        elif "завтра" in user_input:
            selected_date=today + timedelta(days=1)
        elif "послезавтра" in user_input:
            selected_date=today + timedelta(days=2)
        elif "вчера" in user_input:
            selected_date=today - timedelta(days=1)
        elif "пропустить" in user_input:
            selected_date=None
        elif "своя" in user_input:
            await update.message.reply_text(
                f"{EMOJI['info']} Введи дату в формате ДД.ММ или ДДММ\n"
                "Например: 15.03 или 1503"
            )
            return SELECT_DATE
        else:
            # Обработка пользовательского ввода даты
            cleaned=re.sub(r"[^\d]", "", user_input)
            if len(cleaned) == 4:
                try:
                    day, month=int(cleaned[:2]), int(cleaned[2:])
                    current_year=datetime.now().year
                    selected_date=date(current_year, month, day)

                    if not validate_date(selected_date):
                        await update.message.reply_text(
                            f"{EMOJI['warning']} Дата слишком далеко в прошлом или будущем. Попробуй еще раз."
                        )
                        return SELECT_DATE

                except ValueError:
                    await update.message.reply_text(
                        f"{EMOJI['warning']} Неверная дата. Попробуй еще раз.\n"
                        "Пример: 15.03 или 1503"
                    )
                    return SELECT_DATE
            else:
                await update.message.reply_text(
                    f"{EMOJI['warning']} Введи 4 цифры: день и месяц.\n"
                    "Пример: 1503 для 15 марта"
                )
                return SELECT_DATE

        context.user_data["date"]=selected_date

        msg=await update.message.reply_text(
            f"{EMOJI['role']} Выбери роль:",
            reply_markup=create_keyboard(ROLE_BUTTONS)
        )
        context.user_data["to_delete"].append(msg.message_id)
        return SELECT_ROLE

    except Exception as e:
        logger.error(f"Ошибка в select_date: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при обработке даты."
        )
        return SELECT_DATE


async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора роли"""
    try:
        role=update.message.text.strip()
        context.user_data["role"]=None if role.lower() == "пропустить" else role

        msg=await update.message.reply_text(
            f"{EMOJI['program']} Выбери программу:",
            reply_markup=create_keyboard(PROGRAM_BUTTONS)
        )
        context.user_data["to_delete"].append(msg.message_id)
        return SELECT_PROGRAM

    except Exception as e:
        logger.error(f"Ошибка в select_role: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при обработке роли."
        )
        return SELECT_ROLE


async def select_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора программы"""
    try:
        program=update.message.text.strip()

        if program == "СВОЙ ВАРИАНТ":
            await update.message.reply_text(
                f"{EMOJI['program']} Введи название программы:",
                reply_markup=ReplyKeyboardMarkup([SKIP_BUTTON], resize_keyboard=True)
            )
            return SELECT_PROGRAM

        context.user_data["program"]=None if program.lower() == "пропустить" else program

        # Переход к вводу времени начала
        context.user_data["buffer"]=""
        context.user_data["typing"]="start"

        msg=await update.message.reply_text(
            f"{EMOJI['time']} Введи время начала (ЧЧММ или ЧЧ:ММ):\n"
            f"Например: 1830 или 18:30",
            reply_markup=ReplyKeyboardMarkup(NUM_PAD, resize_keyboard=True)
        )
        context.user_data["to_delete"].append(msg.message_id)
        return TYPING_START

    except Exception as e:
        logger.error(f"Ошибка в select_program: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при обработке программы."
        )
        return SELECT_PROGRAM


async def handle_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода времени"""
    try:
        char=update.message.text.strip().lower()
        typing_type=context.user_data.get("typing", "start")

        # Удаляем сообщение пользователя для чистоты интерфейса
        await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

        if char == "пропустить":
            return await skip_time_input(update, context, typing_type)

        if char == "подтвердить":
            return await confirm_time_input(update, context, typing_type)

        # Добавляем символ к буферу
        context.user_data["buffer"]+=char
        clean_buffer=re.sub(r"[^\d]", "", context.user_data["buffer"])

        # Автоматическое подтверждение при достижении 4 цифр
        if len(clean_buffer)>=4:
            return await confirm_time_input(update, context, typing_type)

        return TYPING_START if typing_type == "start" else TYPING_END

    except Exception as e:
        logger.error(f"Ошибка в handle_time_input: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при обработке времени."
        )
        return TYPING_START if context.user_data.get("typing") == "start" else TYPING_END


async def skip_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE, typing_type: str):
    """Пропуск ввода времени"""
    context.user_data[f"{typing_type}_time"]=None
    context.user_data["buffer"]=""

    if typing_type == "start":
        context.user_data["typing"]="end"
        msg=await update.message.reply_text(
            f"{EMOJI['time']} Введи время окончания (ЧЧММ или ЧЧ:ММ):",
            reply_markup=ReplyKeyboardMarkup(NUM_PAD, resize_keyboard=True)
        )
        context.user_data["to_delete"].append(msg.message_id)
        return TYPING_END
    else:
        return await prompt_salary(update, context)


async def confirm_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE, typing_type: str):
    """Подтверждение ввода времени"""
    time_str=clean_time_input(context.user_data.get("buffer", ""))

    if time_str and validate_time(time_str):
        context.user_data[f"{typing_type}_time"]=time_str
        context.user_data["buffer"]=""

        if typing_type == "start":
            context.user_data["typing"]="end"
            msg=await update.message.reply_text(
                f"{EMOJI['time']} Введи время окончания (ЧЧММ или ЧЧ:ММ):",
                reply_markup=ReplyKeyboardMarkup(NUM_PAD, resize_keyboard=True)
            )
            context.user_data["to_delete"].append(msg.message_id)
            return TYPING_END
        else:
            return await prompt_salary(update, context)
    else:
        await update.message.reply_text(
            f"{EMOJI['warning']} Неправильный формат времени.\n"
            "Пример: 1830 или 18:30",
            reply_markup=ReplyKeyboardMarkup(NUM_PAD, resize_keyboard=True)
        )
        context.user_data["buffer"]=""
        return TYPING_START if typing_type == "start" else TYPING_END


async def prompt_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос ввода зарплаты"""
    msg=await update.message.reply_text(
        f"{EMOJI['salary']} Введи гонорар в рублях:\n"
        "Например: 10000 или 7500",
        reply_markup=ReplyKeyboardMarkup([SKIP_BUTTON], resize_keyboard=True)
    )
    context.user_data["to_delete"].append(msg.message_id)
    return TYPING_SALARY


async def enter_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода зарплаты"""
    try:
        text=update.message.text.strip().lower()

        if text == "пропустить":
            context.user_data["salary"]=None
            return await save_shift_data(update, context)

        try:
            # Убираем все кроме цифр и точки/запятой
            cleaned_text=re.sub(r'[^\d.,]', '', update.message.text.strip())
            value=float(cleaned_text.replace(",", "."))

            if value<0:
                await update.message.reply_text(
                    f"{EMOJI['warning']} Гонорар не может быть отрицательным."
                )
                return TYPING_SALARY

            context.user_data["salary"]=int(value)  # Сохраняем как есть в рублях
            return await save_shift_data(update, context)

        except ValueError:
            await update.message.reply_text(
                f"{EMOJI['warning']} Введи число в рублях. Например: 10000 или 7500"
            )
            return TYPING_SALARY

    except Exception as e:
        logger.error(f"Ошибка в enter_salary: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при обработке зарплаты."
        )
        return TYPING_SALARY


async def save_shift_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение смены в базу данных"""
    try:
        user_id=str(update.effective_user.id)
        shift_data={
            "date": context.user_data.get("date"),
            "role": context.user_data.get("role"),
            "program": context.user_data.get("program"),
            "start_time": context.user_data.get("start_time"),
            "end_time": context.user_data.get("end_time"),
            "salary": context.user_data.get("salary"),
        }

        if db.add_shift(user_id, shift_data):
            await display_shift(update, context, shift_data)
            await cleanup_messages(update, context)

            await update.message.reply_text(
                f"{EMOJI['success']} Смена успешно добавлена!",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Ошибка при сохранении смены. Попробуйте еще раз.",
                reply_markup=get_main_menu_keyboard()
            )

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка в save_shift_data: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при сохранении смены.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END


async def display_shift(update: Update, context: ContextTypes.DEFAULT_TYPE, shift: Dict[str, Any]):
    """Отображение информации о смене"""
    try:
        await cleanup_messages(update, context)

        formatted_text=format_shift_display(shift)
        if formatted_text:
            await update.message.reply_text(formatted_text)
        else:
            await update.message.reply_text(f"{EMOJI['info']} Смена без данных")

    except Exception as e:
        logger.error(f"Ошибка в display_shift: {e}")


async def list_shifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню выбора месяца для просмотра смен"""
    try:
        # Создаем кнопки для месяцев
        month_buttons=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Январь", callback_data="month_1"),
                InlineKeyboardButton("Февраль", callback_data="month_2"),
                InlineKeyboardButton("Март", callback_data="month_3")
            ],
            [
                InlineKeyboardButton("Апрель", callback_data="month_4"),
                InlineKeyboardButton("Май", callback_data="month_5"),
                InlineKeyboardButton("Июнь", callback_data="month_6")
            ],
            [
                InlineKeyboardButton("Июль", callback_data="month_7"),
                InlineKeyboardButton("Август", callback_data="month_8"),
                InlineKeyboardButton("Сентябрь", callback_data="month_9")
            ],
            [
                InlineKeyboardButton("Октябрь", callback_data="month_10"),
                InlineKeyboardButton("Ноябрь", callback_data="month_11"),
                InlineKeyboardButton("Декабрь", callback_data="month_12")
            ],
            [
                InlineKeyboardButton("Все смены", callback_data="month_all")
            ]
        ])

        await update.message.reply_text(
            f"{EMOJI['date']} Выбери месяц для просмотра смен:",
            reply_markup=month_buttons
        )

    except Exception as e:
        logger.error(f"Ошибка в list_shifts: {e}")
        await update.message.reply_text(
            "⚠️ Произошла ошибка при загрузке меню.",
            reply_markup=get_main_menu_keyboard()
        )


async def show_shifts_by_month(update: Update, context: ContextTypes.DEFAULT_TYPE, month: int = None):
    """Показать смены за определенный месяц или все смены"""
    try:
        query=update.callback_query
        user_id=str(query.from_user.id)
        shifts=db.get_user_shifts(user_id)

        if not shifts:
            await query.edit_message_text(
                "У тебя пока нет смен.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад к месяцам", callback_data="back_to_months")
                ]])
            )
            return

        # Фильтруем смены по месяцу если нужно
        if month is not None:
            current_year=datetime.now().year
            filtered_shifts=[]
            for shift in shifts:
                if shift.get("date") and shift["date"].month == month and shift["date"].year == current_year:
                    filtered_shifts.append(shift)
            shifts=filtered_shifts

        # Сортируем смены: старые сверху, новые снизу
        if shifts:
            shifts.sort(key=lambda s: (
                s.get("date") or date.min,  # Сначала по дате (старые сверху)
                s.get("start_time") or "00:00"  # Потом по времени (раннее сверху)
            ))

        if not shifts:
            month_names={
                1: "январь", 2: "февраль", 3: "март", 4: "апрель",
                5: "май", 6: "июнь", 7: "июль", 8: "август",
                9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"
            }
            month_name=month_names.get(month, "выбранный месяц")

            await query.edit_message_text(
                f"У тебя нет смен за {month_name}.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад к месяцам", callback_data="back_to_months")
                ]])
            )
            return

        # Показываем заголовок
        if month is not None:
            month_names={
                1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
                5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
                9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
            }
            header=f"📅 Смены за {month_names[month]} {datetime.now().year}\n\n"
        else:
            header="📅 Все твои смены:\n\n"

        # Отправляем заголовок с кнопкой "Назад"
        await query.edit_message_text(
            header.strip(),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад к месяцам", callback_data="back_to_months")
            ]])
        )

        # Показываем смены
        for shift in shifts:
            formatted_text=format_shift_display(shift)

            buttons=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✏ Изменить", callback_data=f"edit_{shift['id']}"),
                    InlineKeyboardButton("❌ Удалить", callback_data=f"delete_{shift['id']}")
                ]
            ])

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=formatted_text if formatted_text else "Смена без данных",
                reply_markup=buttons
            )

    except Exception as e:
        logger.error(f"Ошибка в show_shifts_by_month: {e}")
        await query.edit_message_text(
            "⚠️ Произошла ошибка при загрузке смен.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад к месяцам", callback_data="back_to_months")
            ]])
        )


async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт данных пользователя"""
    try:
        user_id=str(update.effective_user.id)
        shifts=db.get_user_shifts(user_id)

        if not shifts:
            await update.message.reply_text(
                f"{EMOJI['info']} У тебя пока нет смен для экспорта.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Создаем JSON файл
        export_data_dict={
            "user_id": user_id,
            "export_date": datetime.now().isoformat(),
            "shifts": []
        }

        for shift in shifts:
            shift_export={
                "date": shift['date'].isoformat() if shift['date'] else None,
                "role": shift['role'],
                "program": shift['program'],
                "start_time": shift['start_time'],
                "end_time": shift['end_time'],
                "salary": shift['salary']
            }
            export_data_dict["shifts"].append(shift_export)

        # Создаем временный файл
        filename=f"shifts_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data_dict, f, ensure_ascii=False, indent=2)

        # Отправляем файл
        with open(filename, 'rb') as f:
            await update.message.reply_document(
                document=f,
                caption=f"{EMOJI['success']} Экспорт данных о сменах",
                reply_markup=get_main_menu_keyboard()
            )

        # Удаляем временный файл
        os.remove(filename)

    except Exception as e:
        logger.error(f"Ошибка в export_data: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при экспорте данных.",
            reply_markup=get_main_menu_keyboard()
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь по использованию бота"""
    help_text=f"""
{EMOJI['info']} *Помощь по использованию бота*

*Основные команды:*
• Начать смену - добавить новую смену
• Мои смены - посмотреть все смены
• Экспорт данных - скачать данные в JSON
• Помощь - это сообщение

*Как добавить смену:*
1. Выберите дату или введите свою
2. Выберите роль (можно пропустить)
3. Выберите программу
4. Введите время начала и окончания
5. Укажите гонорар

*Форматы ввода:*
• Время: 1830 или 18:30
• Дата: 1503 для 15.03
• Гонорар: 10 или 7.5 (в тысячах рублей)

*Управление сменами:*
• Редактирование - изменить любое поле
• Удаление - удалить смену
• Экспорт - скачать все данные

По вопросам пишите @username
"""

    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на инлайн кнопки"""
    try:
        query=update.callback_query
        await query.answer()

        logger.debug(f"Получен callback_data: {query.data}")

        user_id=str(query.from_user.id)
        data=query.data

        # Обработка выбора месяца
        if data.startswith("month_"):
            if data == "month_all":
                await show_shifts_by_month(update, context, month=None)
            else:
                month=int(data.split("_")[1])
                await show_shifts_by_month(update, context, month=month)
            return

        # Возврат к меню месяцев
        elif data == "back_to_months":
            month_buttons=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Январь", callback_data="month_1"),
                    InlineKeyboardButton("Февраль", callback_data="month_2"),
                    InlineKeyboardButton("Март", callback_data="month_3")
                ],
                [
                    InlineKeyboardButton("Апрель", callback_data="month_4"),
                    InlineKeyboardButton("Май", callback_data="month_5"),
                    InlineKeyboardButton("Июнь", callback_data="month_6")
                ],
                [
                    InlineKeyboardButton("Июль", callback_data="month_7"),
                    InlineKeyboardButton("Август", callback_data="month_8"),
                    InlineKeyboardButton("Сентябрь", callback_data="month_9")
                ],
                [
                    InlineKeyboardButton("Октябрь", callback_data="month_10"),
                    InlineKeyboardButton("Ноябрь", callback_data="month_11"),
                    InlineKeyboardButton("Декабрь", callback_data="month_12")
                ],
                [
                    InlineKeyboardButton("Все смены", callback_data="month_all")
                ]
            ])

            await query.edit_message_text(
                f"{EMOJI['date']} Выбери месяц для просмотра смен:",
                reply_markup=month_buttons
            )
            return

        # Удаление смены
        elif data.startswith("delete_"):
            shift_id=int(data.split("_")[1])

            if db.delete_shift(user_id, shift_id):
                await query.edit_message_text(f"{EMOJI['success']} Смена удалена.")
                logger.info(f"Пользователь {user_id} удалил смену {shift_id}")
            else:
                await query.edit_message_text(f"{EMOJI['warning']} Ошибка при удалении смены.")

        # Редактирование смены (открытие меню редактирования)
        elif re.fullmatch(r"edit_\d+", data):  # Только edit_число
            shift_id=int(data.split("_")[1])

            shifts=db.get_user_shifts(user_id)
            shift=next((s for s in shifts if s['id'] == shift_id), None)

            if not shift:
                await query.edit_message_text(f"{EMOJI['warning']} Смена не найдена.")
                return

            edit_buttons=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Дата", callback_data=f"edit_field_{shift_id}_date")],
                [InlineKeyboardButton("🛠️ Роль", callback_data=f"edit_field_{shift_id}_role")],
                [InlineKeyboardButton("📺 Программа", callback_data=f"edit_field_{shift_id}_program")],
                [InlineKeyboardButton("⏰ Время начала", callback_data=f"edit_field_{shift_id}_start_time")],
                [InlineKeyboardButton("⏱️ Время окончания", callback_data=f"edit_field_{shift_id}_end_time")],
                [InlineKeyboardButton("💰 Гонорар", callback_data=f"edit_field_{shift_id}_salary")],
                [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_edit_{shift_id}")]
            ])

            await query.edit_message_text(
                f"Что хочешь изменить в смене?\n\n{format_shift_display(shift)}",
                reply_markup=edit_buttons
            )

        # Обработка конкретного поля (edit_field_...)
        elif data.startswith("edit_field_"):
            logger.debug(f"Обработка edit_field_: {data}")

            match=re.match(r"edit_field_(\d+)_(\w+)", data)
            if not match:
                await query.edit_message_text("⚠️ Ошибка: не удалось разобрать команду.")
                return

            shift_id=int(match.group(1))
            field=match.group(2)

            logger.debug(f"Редактируем смену ID {shift_id}, поле {field}")

            context.user_data["edit_shift_id"]=shift_id
            context.user_data["edit_field"]=field

            field_names={
                "date": "дату (формат ДДММ, например: 1503)",
                "role": "роль",
                "program": "программу",
                "start_time": "время начала (формат ЧЧММ, например: 1830)",
                "end_time": "время окончания (формат ЧЧММ, например: 2100)",
                "salary": "гонорар в рублях (например: 10000 или 7500)"
            }

            await query.edit_message_text(
                f"Введи новое значение для поля «{field_names.get(field, field)}»:\n\n"
                f"Введи 'пропустить' чтобы очистить поле."
            )

        # Отмена редактирования
        elif data.startswith("cancel_edit_"):
            shift_id=int(data.split("_")[2])
            shifts=db.get_user_shifts(user_id)
            shift=next((s for s in shifts if s['id'] == shift_id), None)

            if shift:
                await query.edit_message_text(format_shift_display(shift))
            else:
                await query.edit_message_text("Смена не найдена.")

    except Exception as e:
        logger.error(f"Ошибка в button_handler: {e}")
        await query.edit_message_text(f"{EMOJI['warning']} Произошла ошибка при обработке кнопки.")


async def handle_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода при редактировании"""
    try:
        if "edit_shift_id" not in context.user_data or "edit_field" not in context.user_data:
            return

        shift_id=context.user_data["edit_shift_id"]
        field=context.user_data["edit_field"]
        user_id=str(update.effective_user.id)
        new_value=update.message.text.strip()

        # Валидация и преобразование значения
        if field == "date":
            if new_value.lower() == "пропустить":
                processed_value=None
            else:
                try:
                    cleaned=re.sub(r"[^\d]", "", new_value)
                    if len(cleaned) == 4:
                        day, month=int(cleaned[:2]), int(cleaned[2:])
                        processed_value=date(datetime.now().year, month, day)

                        if not validate_date(processed_value):
                            await update.message.reply_text(
                                f"{EMOJI['warning']} Дата слишком далеко в прошлом или будущем."
                            )
                            return
                    else:
                        await update.message.reply_text(
                            f"{EMOJI['warning']} Неверный формат даты. Используй ДДММ (например: 1503)."
                        )
                        return
                except ValueError:
                    await update.message.reply_text(
                        f"{EMOJI['warning']} Неверная дата."
                    )
                    return

        elif field in ["start_time", "end_time"]:
            if new_value.lower() == "пропустить":
                processed_value=None
            else:
                processed_value=clean_time_input(new_value)
                if processed_value and not validate_time(processed_value):
                    await update.message.reply_text(
                        f"{EMOJI['warning']} Неверный формат времени. Используй ЧЧММ или ЧЧ:ММ (например: 1830)."
                    )
                    return

        elif field == "salary":
            if new_value.lower() == "пропустить":
                processed_value=None
            else:
                try:
                    # Убираем все кроме цифр и точки/запятой
                    cleaned_text=re.sub(r'[^\d.,]', '', new_value)
                    value=float(cleaned_text.replace(",", "."))
                    if value<0:
                        await update.message.reply_text(
                            f"{EMOJI['warning']} Гонорар не может быть отрицательным."
                        )
                        return
                    processed_value=int(value)  # Сохраняем как есть в рублях
                except ValueError:
                    await update.message.reply_text(
                        f"{EMOJI['warning']} Неверный формат суммы. Введи число в рублях (например: 10000 или 7500)."
                    )
                    return

        else:  # role, program
            processed_value=None if new_value.lower() == "пропустить" else new_value

        # Обновляем в базе данных
        if db.update_shift(user_id, shift_id, field, processed_value):
            # Получаем обновленную смену
            shifts=db.get_user_shifts(user_id)
            updated_shift=next((s for s in shifts if s['id'] == shift_id), None)

            if updated_shift:
                # Показываем обновленную смену с кнопками для дальнейшего редактирования
                formatted_text=format_shift_display(updated_shift)

                edit_buttons=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✏ Изменить еще", callback_data=f"edit_{shift_id}"),
                        InlineKeyboardButton("❌ Удалить", callback_data=f"delete_{shift_id}")
                    ]
                ])

                await update.message.reply_text(
                    f"{EMOJI['success']} Поле обновлено!\n\n{formatted_text}",
                    reply_markup=edit_buttons
                )
            else:
                await update.message.reply_text(
                    f"{EMOJI['success']} Поле обновлено!",
                    reply_markup=get_main_menu_keyboard()
                )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Ошибка при обновлении.",
                reply_markup=get_main_menu_keyboard()
            )

        # Очищаем данные редактирования
        context.user_data.pop("edit_shift_id", None)
        context.user_data.pop("edit_field", None)

    except Exception as e:
        logger.error(f"Ошибка в handle_edit_input: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка при редактировании.",
            reply_markup=get_main_menu_keyboard()
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего диалога"""
    try:
        await cleanup_messages(update, context)
        await update.message.reply_text(
            f"{EMOJI['cancel']} Операция отменена.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в cancel: {e}")
        return ConversationHandler.END


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок главного меню"""
    try:
        text=update.message.text

        if text == "Начать смену":
            return await start_shift_creation(update, context)
        elif text == "Мои смены":
            await list_shifts(update, context)
        elif text == "Экспорт данных":
            await export_data(update, context)
        elif text == "Помощь":
            await help_command(update, context)
        else:
            # Проверяем, не находимся ли мы в режиме редактирования
            if "edit_shift_id" in context.user_data and "edit_field" in context.user_data:
                await handle_edit_input(update, context)
            else:
                await update.message.reply_text(
                    f"{EMOJI['info']} Используй кнопки меню для навигации.",
                    reply_markup=get_main_menu_keyboard()
                )
    except Exception as e:
        logger.error(f"Ошибка в handle_menu_buttons: {e}")
        await update.message.reply_text(
            f"{EMOJI['warning']} Произошла ошибка.",
            reply_markup=get_main_menu_keyboard()
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")

    if update and update.effective_message:
        await update.effective_message.reply_text(
            f"{EMOJI['warning']} Произошла непредвиденная ошибка. Попробуйте еще раз.",
            reply_markup=get_main_menu_keyboard()
        )


def main():
    """Основная функция запуска бота"""
    try:
        # Инициализируем приложение
        application=ApplicationBuilder().token(TELEGRAM_TOKEN).build()

        # Создаем обработчик диалогов для добавления смены
        conv_handler=ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex(r'^Начать смену'), start_shift_creation)
            ],
            states={
                SELECT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_date)],
                SELECT_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_role)],
                SELECT_PROGRAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_program)],
                TYPING_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time_input)],
                TYPING_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time_input)],
                TYPING_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_salary)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )

        # Добавляем обработчики в правильном порядке (от более специфичных к общим)

        # 1. Команды
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel))

        # 2. Обработчик диалогов
        application.add_handler(conv_handler)

        # 3. Обработчик inline кнопок
        application.add_handler(CallbackQueryHandler(button_handler))

        # 4. Обработчик кнопок главного меню и текстовых сообщений
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_menu_buttons
        ))

        # 5. Глобальный обработчик ошибок
        application.add_error_handler(error_handler)

        logger.info("Бот запущен и готов к работе...")
        print(f"{EMOJI['success']} Бот запущен успешно!")

        # Запускаем бота
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        print(f"{EMOJI['warning']} Ошибка при запуске: {e}")


if __name__ == "__main__":
    main()