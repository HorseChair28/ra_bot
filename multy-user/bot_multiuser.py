# bot_multiuser.py - Бот с поддержкой множества пользователей
import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes, \
    CallbackQueryHandler
from database import MultiUserDatabase  # Импортируем новую БД
from datetime import datetime, date, timedelta
import json
import os
import re
from config import TELEGRAM_TOKEN

# Инициализация базы данных
DB_PATH=os.getenv("DATABASE_PATH", "shifts.db")
db=MultiUserDatabase(DB_PATH)

# ====== Настройка логирования ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
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
    "info": "ℹ️",
    "user": "👤",
    "link": "🔗"
}

# Состояния диалога
SELECT_DATE, SELECT_ROLE, SELECT_PROGRAM, TYPING_START, TYPING_END, TYPING_SALARY=range(6)

# Константы кнопок
ROLE_BUTTONS=[
    ["РЕЖ", "ЭКРАНЫ", "EVS"],
    ["VMIX", "ОПЕРАТОР", "ОПЕРПОСТ"],
    ["СВЕТ", "ГРИМ", "СВОЙ ВАРИАНТ"],
    ["Пропустить", "❌ Отмена"]
]

PROGRAM_BUTTONS=[
    ["ЛЧ", "ЛЕ", "ЛК"],
    ["ЛИГА 1", "БУНДЕСЛИГА", "ММА"],
    ["КУБОГНЯ", "ФИГУРКА", "БИАТЛОН"],
    ["РПЛ", "LALIGA", "ТУРДЕФРАНС"],
    ["СВОЙ ВАРИАНТ"],
    ["Пропустить", "❌ Отмена"]
]

NUM_PAD=[
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    [":", "0", "."],
    ["Пропустить", "Подтвердить"],
    ["❌ Отмена"]
]

NUM_PAD_SALARY=[
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    [".", "0", "Очистить"],
    ["Пропустить", "Подтвердить"],
    ["❌ Отмена"]
]

SKIP_BUTTON=["Пропустить"]
CANCEL_BUTTON=["❌ Отмена"]
SKIP_AND_CANCEL=["Пропустить", "❌ Отмена"]


# ====== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======

def validate_date(date_obj):
    """Проверка валидности даты"""
    if not date_obj:
        return True  # None допустимо

    today=date.today()
    # Разрешаем даты от 1 года назад до 1 года вперед
    min_date=today - timedelta(days=365)
    max_date=today + timedelta(days=365)

    return min_date<=date_obj<=max_date


def validate_time(time_str):
    """Проверка валидности времени"""
    if not time_str:
        return True

    try:
        # Проверяем формат HH:MM
        if ':' in time_str:
            hours, minutes=map(int, time_str.split(':'))
        else:
            # Формат HHMM
            if len(time_str) == 4:
                hours=int(time_str[:2])
                minutes=int(time_str[2:])
            else:
                return False

        return 0<=hours<=23 and 0<=minutes<=59
    except (ValueError, IndexError):
        return False


def clean_time_input(time_str):
    """Очистка и форматирование времени"""
    if not time_str:
        return None

    # Убираем все кроме цифр
    cleaned=re.sub(r'[^\d]', '', time_str)

    if len(cleaned) == 4:
        hours=cleaned[:2]
        minutes=cleaned[2:]
        return f"{hours}:{minutes}"
    elif len(cleaned) == 3:
        hours=f"0{cleaned[0]}"
        minutes=cleaned[1:]
        return f"{hours}:{minutes}"
    elif len(cleaned) == 2:
        hours=cleaned
        return f"{hours}:00"
    elif len(cleaned) == 1:
        hours=f"0{cleaned}"
        return f"{hours}:00"

    return None


def create_keyboard(buttons):
    """Создание клавиатуры из массива кнопок"""
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def format_shift_display(shift):
    """Форматирование смены для отображения"""
    lines=[]

    if shift.get("date"):
        lines.append(f"{EMOJI['date']} {shift['date'].strftime('%d.%m.%Y')}")

    if shift.get("role"):
        lines.append(f"{EMOJI['role']} {shift['role']}")

    if shift.get("program"):
        lines.append(f"{EMOJI['program']} {shift['program']}")

    if shift.get("start_time") and shift.get("end_time"):
        lines.append(f"{EMOJI['time']} {shift['start_time']}–{shift['end_time']}")
    elif shift.get("start_time"):
        lines.append(f"{EMOJI['time']} с {shift['start_time']}")
    elif shift.get("end_time"):
        lines.append(f"{EMOJI['time']} до {shift['end_time']}")

    if shift.get("salary") is not None:
        lines.append(f"{EMOJI['salary']} {shift['salary']:,} ₽".replace(",", " "))

    return "\n".join(lines)


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню с новой кнопкой профиля"""
    return ReplyKeyboardMarkup([
        ["Начать смену", "Мои смены"],
        ["Экспорт данных", "Статистика"],
        ["👤 Профиль", "Помощь"]
    ], resize_keyboard=True)


# ====== НОВЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ ======

async def ensure_user_exists(update: Update) -> str:
    """Проверка и создание пользователя если его нет"""
    telegram_id=str(update.effective_user.id)
    username=update.effective_user.username
    full_name=update.effective_user.full_name

    # Проверяем существует ли пользователь
    user=db.get_user_by_telegram_id(telegram_id)

    if not user:
        # Создаем нового пользователя
        user_id=db.create_user_from_telegram(telegram_id, username, full_name)
        logger.info(f"Создан новый пользователь: {user_id} ({full_name})")
        return user_id
    else:
        return user['user_id']


# ====== ОСНОВНЫЕ ОБРАБОТЧИКИ ======

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start с регистрацией пользователя"""
    # Автоматически создаем пользователя если его нет
    user_id=await ensure_user_exists(update)

    welcome_text=f"""
{EMOJI['success']} *Добро пожаловать в бот учета смен!*

{EMOJI['user']} Твой ID: `{user_id}`

Этот бот поможет тебе вести учет рабочих смен.

*Доступные функции:*
• Добавление новых смен
• Просмотр всех смен
• Редактирование и удаление
• Экспорт данных
• Статистика заработка
• Доступ к веб-версии

Используй кнопки меню для навигации.
"""

    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать профиль пользователя с токеном для веб-доступа"""
    telegram_id=str(update.effective_user.id)
    user=db.get_user_by_telegram_id(telegram_id)

    if not user:
        user_id=await ensure_user_exists(update)
        user=db.get_user_by_telegram_id(telegram_id)

    # Получаем статистику
    stats=db.get_user_statistics(user['user_id'])

    profile_text=f"""
{EMOJI['user']} *Твой профиль*

*ID:* `{user['user_id']}`
*Имя:* {user['full_name'] or 'Не указано'}
*Username:* @{user['username'] or 'Не указан'}

*Статистика:*
• Всего смен: {stats['total_shifts']}
• Общий заработок: {stats['total_salary']:,} ₽

{EMOJI['link']} *Доступ к веб-версии:*
Твой токен API: 
`{user['api_token']}`

Используй этот токен для входа на сайте.
_Нажми на токен чтобы скопировать_

⚠️ *Не делись токеном с другими!*
"""

    # Кнопки для дополнительных действий
    buttons=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Сгенерировать новый токен", callback_data="regenerate_token")],
        [InlineKeyboardButton("📊 Подробная статистика", callback_data="detailed_stats")]
    ])

    await update.message.reply_text(
        profile_text.replace(",", " "),
        parse_mode='Markdown',
        reply_markup=buttons
    )


async def statistics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя"""
    user_id=await ensure_user_exists(update)
    stats=db.get_user_statistics(user_id)

    # Формируем текст статистики
    stats_text=f"""
📊 *Твоя статистика*

*Общие показатели:*
• Всего смен: {stats['total_shifts']}
• Общий заработок: {stats['total_salary']:,} ₽
• Средний заработок: {stats['total_salary'] // max(stats['total_shifts'], 1):,} ₽

*По месяцам (последние 12):*
"""

    month_names={
        '01': 'Январь', '02': 'Февраль', '03': 'Март',
        '04': 'Апрель', '05': 'Май', '06': 'Июнь',
        '07': 'Июль', '08': 'Август', '09': 'Сентябрь',
        '10': 'Октябрь', '11': 'Ноябрь', '12': 'Декабрь'
    }

    for month_stat in stats['monthly_stats'][:6]:  # Показываем последние 6 месяцев
        year, month=month_stat['month'].split('-')
        month_name=month_names.get(month, month)
        stats_text+=f"\n• {month_name} {year}: {month_stat['count']} смен, {month_stat['salary']:,} ₽"

    await update.message.reply_text(
        stats_text.replace(",", " "),
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


# ====== ОБРАБОТЧИКИ СОЗДАНИЯ СМЕНЫ ======

async def start_shift_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога добавления смены"""
    try:
        await cleanup_messages(update, context)
        context.user_data.clear()

        date_buttons=[
            ["Сегодня", "Завтра"],
            ["Послезавтра", "Вчера"],
            ["Своя дата", "Пропустить"],
            ["❌ Отмена"]
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

        # Проверка на отмену
        if "❌" in user_input or "отмена" in user_input:
            return await cancel(update, context)

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
                "Например: 15.03 или 1503",
                reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
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
                            f"{EMOJI['warning']} Дата слишком далеко в прошлом или будущем. Попробуй еще раз.",
                            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
                        )
                        return SELECT_DATE

                except ValueError:
                    await update.message.reply_text(
                        f"{EMOJI['warning']} Неверная дата. Попробуй еще раз.\n"
                        "Пример: 15.03 или 1503",
                        reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
                    )
                    return SELECT_DATE
            else:
                await update.message.reply_text(
                    f"{EMOJI['warning']} Введи 4 цифры: день и месяц.\n"
                    "Пример: 1503 для 15 марта",
                    reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
                )
                return SELECT_DATE

        context.user_data["date"]=selected_date

        msg=await update.message.reply_text(
            f"{EMOJI['role']} Выбери роль:",
            reply_markup=ReplyKeyboardMarkup(ROLE_BUTTONS, resize_keyboard=True)
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

        # Проверка на отмену
        if "❌" in role or "отмена" in role.lower():
            return await cancel(update, context)

        context.user_data["role"]=None if role.lower() == "пропустить" else role

        msg=await update.message.reply_text(
            f"{EMOJI['program']} Выбери программу:",
            reply_markup=ReplyKeyboardMarkup(PROGRAM_BUTTONS, resize_keyboard=True)
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

        # Проверка на отмену
        if "❌" in program or "отмена" in program.lower():
            return await cancel(update, context)

        if program == "СВОЙ ВАРИАНТ":
            await update.message.reply_text(
                f"{EMOJI['program']} Введи название программы:",
                reply_markup=ReplyKeyboardMarkup([SKIP_AND_CANCEL], resize_keyboard=True)
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

        # Проверка на отмену
        if "❌" in char or "отмена" in char:
            return await cancel(update, context)

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
    context.user_data["salary_buffer"]=""  # Инициализируем буфер для зарплаты

    # Сохраняем ID сообщения с инструкцией, чтобы его обновлять
    msg=await update.message.reply_text(
        f"{EMOJI['salary']} Введи гонорар в рублях:\n"
        "Используй цифровую клавиатуру",
        reply_markup=ReplyKeyboardMarkup(NUM_PAD_SALARY, resize_keyboard=True)
    )
    context.user_data["salary_message_id"]=msg.message_id
    return TYPING_SALARY


async def enter_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода зарплаты"""
    try:
        text=update.message.text.strip().lower()

        # Проверка на отмену
        if "❌" in text or "отмена" in text:
            # Удаляем сообщение пользователя
            await safe_delete_message(context, update.effective_chat.id, update.message.message_id)
            # Удаляем сообщение с инструкцией если есть
            if "salary_message_id" in context.user_data:
                await safe_delete_message(context, update.effective_chat.id, context.user_data["salary_message_id"])
            return await cancel(update, context)

        # НЕ удаляем сообщение пользователя до подтверждения

        if text == "пропустить":
            # Удаляем сообщения при пропуске
            await safe_delete_message(context, update.effective_chat.id, update.message.message_id)
            if "salary_message_id" in context.user_data:
                await safe_delete_message(context, update.effective_chat.id, context.user_data["salary_message_id"])
            context.user_data["salary"]=None
            return await save_shift_data(update, context)

        if text == "очистить":
            # Очищаем буфер
            context.user_data["salary_buffer"]=""
            # Удаляем сообщение с командой очистки
            await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

            # Обновляем основное сообщение
            if "salary_message_id" in context.user_data:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=context.user_data["salary_message_id"],
                        text=f"{EMOJI['salary']} Введи гонорар в рублях:\n"
                             "Используй цифровую клавиатуру"
                    )
                except:
                    pass
            return TYPING_SALARY

        if text == "подтвердить":
            # Обрабатываем накопленный буфер
            buffer_value=context.user_data.get("salary_buffer", "")
            if buffer_value:
                try:
                    value=int(buffer_value)
                    if value<0:
                        # Удаляем сообщение с подтверждением
                        await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

                        # Обновляем сообщение с ошибкой
                        if "salary_message_id" in context.user_data:
                            try:
                                await context.bot.edit_message_text(
                                    chat_id=update.effective_chat.id,
                                    message_id=context.user_data["salary_message_id"],
                                    text=f"{EMOJI['warning']} Гонорар не может быть отрицательным.\n"
                                         "Введите новую сумму:"
                                )
                            except:
                                pass
                        context.user_data["salary_buffer"]=""
                        return TYPING_SALARY

                    # Удаляем все сообщения при успешном подтверждении
                    await safe_delete_message(context, update.effective_chat.id, update.message.message_id)
                    if "salary_message_id" in context.user_data:
                        await safe_delete_message(context, update.effective_chat.id,
                                                  context.user_data["salary_message_id"])

                    context.user_data["salary"]=value
                    return await save_shift_data(update, context)
                except ValueError:
                    # Удаляем сообщение с подтверждением
                    await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

                    # Обновляем сообщение с ошибкой
                    if "salary_message_id" in context.user_data:
                        try:
                            await context.bot.edit_message_text(
                                chat_id=update.effective_chat.id,
                                message_id=context.user_data["salary_message_id"],
                                text=f"{EMOJI['warning']} Неверный формат суммы.\n"
                                     "Введите число:"
                            )
                        except:
                            pass
                    context.user_data["salary_buffer"]=""
                    return TYPING_SALARY
            else:
                # Удаляем сообщение с подтверждением
                await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

                # Обновляем сообщение
                if "salary_message_id" in context.user_data:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=update.effective_chat.id,
                            message_id=context.user_data["salary_message_id"],
                            text=f"{EMOJI['warning']} Введите сумму или нажмите 'Пропустить'."
                        )
                    except:
                        pass
                return TYPING_SALARY

        # Если это цифры или точка - добавляем к буферу
        if text in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "."]:
            if "salary_buffer" not in context.user_data:
                context.user_data["salary_buffer"]=""

            # Удаляем сообщение с цифрой
            await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

            context.user_data["salary_buffer"]+=text

            # Обновляем основное сообщение с текущей суммой
            current_value=context.user_data["salary_buffer"]
            if "salary_message_id" in context.user_data:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=context.user_data["salary_message_id"],
                        text=f"{EMOJI['salary']} Текущая сумма: {current_value} ₽\n"
                             f"Нажмите 'Подтвердить' для сохранения"
                    )
                except:
                    # Если не удалось отредактировать, отправляем новое
                    msg=await update.message.reply_text(
                        f"{EMOJI['salary']} Текущая сумма: {current_value} ₽\n"
                        f"Нажмите 'Подтвердить' для сохранения"
                    )
                    context.user_data["salary_message_id"]=msg.message_id
            return TYPING_SALARY

        # Если это не команда и не цифра, пробуем обработать как обычный ввод
        try:
            # Убираем все кроме цифр и точки/запятой
            cleaned_text=re.sub(r'[^\d.,]', '', text)
            value=float(cleaned_text.replace(",", "."))

            if value<0:
                # Удаляем сообщение пользователя
                await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

                # Обновляем основное сообщение
                if "salary_message_id" in context.user_data:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=update.effective_chat.id,
                            message_id=context.user_data["salary_message_id"],
                            text=f"{EMOJI['warning']} Гонорар не может быть отрицательным.\n"
                                 "Используйте цифровую клавиатуру"
                        )
                    except:
                        pass
                return TYPING_SALARY

            # Удаляем сообщения при успешном вводе
            await safe_delete_message(context, update.effective_chat.id, update.message.message_id)
            if "salary_message_id" in context.user_data:
                await safe_delete_message(context, update.effective_chat.id, context.user_data["salary_message_id"])

            context.user_data["salary"]=int(value)
            return await save_shift_data(update, context)

        except ValueError:
            # Удаляем сообщение пользователя
            await safe_delete_message(context, update.effective_chat.id, update.message.message_id)

            # Обновляем основное сообщение
            if "salary_message_id" in context.user_data:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=context.user_data["salary_message_id"],
                        text=f"{EMOJI['warning']} Используйте цифровую клавиатуру или введите число."
                    )
                except:
                    pass
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
        # Получаем user_id из базы данных
        user_id=await ensure_user_exists(update)

        shift_data={
            "date": context.user_data.get("date"),
            "role": context.user_data.get("role"),
            "program": context.user_data.get("program"),
            "start_time": context.user_data.get("start_time"),
            "end_time": context.user_data.get("end_time"),
            "salary": context.user_data.get("salary"),
        }

        if db.add_shift(user_id, shift_data):
            # Показываем смену
            formatted_text=format_shift_display(shift_data)
            await update.message.reply_text(formatted_text)

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


# ====== ОБРАБОТЧИКИ ПРОСМОТРА СМЕН ======

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
        user_id=await ensure_user_exists(update)
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


# ====== ЭКСПОРТ ДАННЫХ ======

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт данных пользователя"""
    try:
        user_id=await ensure_user_exists(update)
        shifts=db.get_user_shifts(user_id)

        if not shifts:
            await update.message.reply_text(
                f"{EMOJI['info']} У тебя пока нет смен для экспорта.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Получаем информацию о пользователе
        telegram_id=str(update.effective_user.id)
        user=db.get_user_by_telegram_id(telegram_id)

        # Создаем JSON файл
        export_data_dict={
            "user_id": user_id,
            "api_token": user['api_token'],
            "export_date": datetime.now().isoformat(),
            "web_access": f"Используй api_token для доступа к веб-версии",
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
                caption=f"{EMOJI['success']} Экспорт данных о сменах\n"
                        f"{EMOJI['link']} Твой API токен в файле для веб-доступа",
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


# ====== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======

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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь по использованию бота"""
    help_text=f"""
{EMOJI['info']} *Помощь по использованию бота*

*Основные команды:*
• Начать смену - добавить новую смену
• Мои смены - посмотреть все смены
• Экспорт данных - скачать данные в JSON
• Статистика - просмотр статистики
• 👤 Профиль - информация о профиле и API токен
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
• Гонорар: в рублях (10000 или 7500)

*Управление сменами:*
• Редактирование - изменить любое поле
• Удаление - удалить смену
• Экспорт - скачать все данные

❌ *Кнопка "Отмена"* доступна на каждом шаге добавления смены

По вопросам пишите @username
"""

    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


# ====== ОБРАБОТЧИКИ КНОПОК ======

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на инлайн кнопки"""
    try:
        query=update.callback_query
        await query.answer()

        logger.debug(f"Получен callback_data: {query.data}")

        user_id=await ensure_user_exists(update)
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

        # Обработка кнопок профиля
        elif data == "regenerate_token":
            new_token=db.regenerate_api_token(user_id)
            if new_token:
                await query.edit_message_text(
                    f"{EMOJI['success']} Новый API токен сгенерирован:\n\n`{new_token}`\n\n"
                    f"⚠️ Старый токен больше не работает!",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(f"{EMOJI['warning']} Ошибка при генерации токена.")

        elif data == "detailed_stats":
            stats=db.get_user_statistics(user_id)

            stats_text=f"""
📊 *Подробная статистика*

*Общие показатели:*
• Всего смен: {stats['total_shifts']}
• Общий заработок: {stats['total_salary']:,} ₽
• Средний заработок за смену: {stats['total_salary'] // max(stats['total_shifts'], 1):,} ₽

*По месяцам:*
"""

            month_names={
                '01': 'Январь', '02': 'Февраль', '03': 'Март',
                '04': 'Апрель', '05': 'Май', '06': 'Июнь',
                '07': 'Июль', '08': 'Август', '09': 'Сентябрь',
                '10': 'Октябрь', '11': 'Ноябрь', '12': 'Декабрь'
            }

            for month_stat in stats['monthly_stats']:
                year, month=month_stat['month'].split('-')
                month_name=month_names.get(month, month)
                stats_text+=f"\n• {month_name} {year}: {month_stat['count']} смен, {month_stat['salary']:,} ₽"

            await query.edit_message_text(
                stats_text.replace(",", " "),
                parse_mode='Markdown'
            )

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
        user_id=await ensure_user_exists(update)
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
        context.user_data.clear()  # Очищаем все данные пользователя
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
        elif text == "Статистика":
            await statistics_command(update, context)
        elif text in ["👤 Профиль", "Профиль"]:
            await profile_command(update, context)
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
        application.add_handler(CommandHandler("profile", profile_command))

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