import os
import logging
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, PicklePersistence
)
from telegram.error import BadRequest

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чтение переменных окружения
TOKEN = os.getenv('TOKEN')
TOPICS_CHAT = os.getenv('TOPICS_CHAT')
VOTING_CHAT = os.getenv('VOTING_CHAT')
PERSISTENCE_PATH = os.getenv('PERSISTENCE_PATH', 'bot_data.pkl')

if not TOKEN:
    logger.error("Ошибка: переменная окружения TOKEN не установлена.")
    exit(1)

if not TOPICS_CHAT:
    logger.error("Ошибка: переменная окружения TOPICS_CHAT не установлена.")
    exit(1)

if not VOTING_CHAT:
    logger.error("Ошибка: переменная окружения VOTING_CHAT не установлена.")
    exit(1)

persistence = PicklePersistence(
    filepath=PERSISTENCE_PATH
)

# Состояния для диалогов
ROOM_SELECTION, SLOT_SELECTION = range(2)
ADD_NAME, ADD_CATEGORY, ADD_TOPIC = range(3)

### Основные функции бота ###

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команды /start."""
    bot = context.bot
    bot_username = (await bot.get_me()).username
    chat = update.effective_chat
    chat_type = chat.type
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    if chat_type == 'private':
        user_id = chat.id
        if context.args and context.args[0].startswith("vote_"):
            arg = context.args[0][5:]
            if '_' in arg:
                source_chat_id_str, thread_id_str = arg.split('_', 1)
                source_chat_id = int(source_chat_id_str)
                source_thread_id = int(thread_id_str)
            else:
                source_chat_id = int(arg)
                source_thread_id = None
            context.user_data['source_chat_id'] = source_chat_id
            context.user_data['source_thread_id'] = source_thread_id
            await send_vote_message(user_id, context)
        elif context.args and context.args[0] == "vote":
            await send_vote_message(user_id, context)
        elif context.args and context.args[0] == "addtopicuser":
            await add_topic_user(update, context)
        else:
            vote_url = f"https://t.me/{bot_username}?start=vote"
            add_topic_url = f"https://t.me/{bot_username}?start=addtopicuser"
            keyboard = [
                [InlineKeyboardButton("Перейти к голосованию", url=vote_url)],
                [InlineKeyboardButton("Добавить тему", url=add_topic_url)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            welcome_message = "Привет! Выберите действие:"
            await bot.send_message(chat_id=user_id, text=welcome_message, reply_markup=reply_markup)
    elif chat_type in ['group', 'supergroup']:
        chat_id = chat.id
        if message_thread_id:
            arg = f"{chat_id}_{message_thread_id}"
        else:
            arg = f"{chat_id}"
        vote_url = f"https://t.me/{bot_username}?start=vote_{arg}"
        keyboard = [[InlineKeyboardButton("Перейти к голосованию", url=vote_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        welcome_message = "Привет! Нажмите кнопку ниже, чтобы перейти к голосованию."
        await bot.send_message(
            chat_id=chat_id,
            text=welcome_message,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id
        )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ-панель для управления ботом."""
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    bot_data = context.bot_data
    num_rooms = bot_data.get('num_rooms', 3)
    num_slots = bot_data.get('num_slots', 4)
    max_votes = bot_data.get('max_votes', 4)
    room_names = bot_data.get('room_names', [])
    votes_data = bot_data.get("votes", {})
    num_voters = len(votes_data)
    booked_slots = bot_data.get('booked_slots', {})

    admin_message = (
        "<b>Команды для организаторов:</b>\n\n"
        "<b>Общие команды</b>\n"
        "/start - Отправить кнопку \"Перейти к голосованию\"\n"
        "/vote - Голосовать за темы\n"
        "/changevote - Изменить голос\n\n"
        "<b>Установка параметров</b>\n"
        "/setrooms - Установить количество залов\n"
        "/setslots - Установить количество слотов в залах\n"
        "/setvotes - Установить количество доступных голосов\n"
        "/namerooms - Установить названия залов\n\n"
        "<b>Бронирование слотов</b>\n"
        "/bookslot - Забронировать слот в зале\n\n"
        "<b>Очистка данных</b>\n"
        "/clearvotes - Очистить голоса\n"
        "/cleartopics - Очистить все сохранённые темы\n"
        "/clearbookings - Очистить все бронирования\n\n"
        "<b>Работа с темами</b>\n"
        "/addtopic - Добавить новые темы\n"
        "/removetopic - Удалить темы\n"
        "/topiclist - Показать список тем для голосования\n\n"
        "<b>Составление расписания</b>\n"
        "/finalize - Завершить голосование и показать результаты\n"
        "/countvotes - Показать количество участников, проголосовавших за темы\n"
        "/secret - Показать подробную статистику голосования\n\n"
        "<b>Текущие настройки:</b>\n"
        f"Количество залов: {num_rooms}\n"
        f"Количество слотов в зале: {num_slots}\n"
        f"Максимальное количество голосов: {max_votes}\n"
        f"Число проголосовавших: {num_voters}\n"
    )
    if room_names:
        admin_message += f"Названия залов: {', '.join(room_names)}\n"

    if booked_slots:
        booked_info = "\n<b>Забронированные слоты:</b>\n"
        for room, slots in booked_slots.items():
            slots_str = ', '.join(str(s) for s in slots)
            booked_info += f"<b>{room}:</b> слоты {slots_str}\n"
        admin_message += booked_info

    await update.message.reply_text(
        text=admin_message,
        parse_mode='HTML',
        message_thread_id=message_thread_id
    )

### Диалог добавления темы пользователем ###

async def add_topic_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запуск диалога для добавления темы пользователем."""
    logger.info("add_topic_user: Диалог запущен")
    context.user_data.clear()
    context.user_data['current_conversation'] = 'add_topic_user_conv'
    await update.message.reply_text("Введите ваше имя:")
    return ADD_NAME

async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода имени."""
    logger.info("receive_name: Начало обработки")
    user_message = update.message.text.strip()
    if not user_message:
        await update.message.reply_text("Пожалуйста, введите ваше имя:")
        logger.info("receive_name: Пользователь не ввёл имя")
        return ADD_NAME
    context.user_data['name'] = user_message
    logger.info(f"receive_name: Имя сохранено: {user_message}")
    
    keyboard = [
        [InlineKeyboardButton("Создать", callback_data='создать')],
        [InlineKeyboardButton("Обсудить", callback_data='обсудить')],
        [InlineKeyboardButton("Объединиться", callback_data='объединиться')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите категорию:", reply_markup=reply_markup)
    logger.info("receive_name: Сообщение с категориями отправлено")
    return ADD_CATEGORY

async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора категории через InlineKeyboard."""
    logger.info("select_category: Начало обработки")
    query = update.callback_query
    await query.answer()
    
    selected_category = query.data
    context.user_data['category'] = selected_category
    logger.info(f"select_category: Выбрана категория: {selected_category}")
    
    await query.message.reply_text("Теперь введите название темы:")
    logger.info("select_category: Запрос ввода темы отправлен")
    return ADD_TOPIC

async def receive_topic_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода темы и сохранение в базе."""
    logger.info("receive_topic_user: Начало обработки")
    user_message = update.message.text.strip()
    if not user_message:
        await update.message.reply_text("Пожалуйста, введите название темы:")
        logger.info("receive_topic_user: Пользователь не ввёл тему")
        return ADD_TOPIC
    
    name = context.user_data.get('name', 'Аноним')
    category = context.user_data.get('category', 'Не определено')
    logger.info(f"receive_topic_user: Данные из context: name={name}, category={category}")
    
    formatted_topic = f"{name}: {category}. {user_message}"
    topics = context.bot_data.get("topics", [])
    topics.append(formatted_topic)
    context.bot_data["topics"] = topics
    await update.message.reply_text(f"Тема добавлена:\n{formatted_topic}", reply_markup=ReplyKeyboardRemove())
    context.user_data.pop('current_conversation', None)
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога."""
    context.user_data.pop('current_conversation', None)
    await update.message.reply_text("Добавление темы отменено.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

### Обработчики и инициализация ###

def main() -> None:
    """Основная функция для запуска бота."""
    global application
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .persistence(persistence)
        .build()
    )

    # Инициализация bot_data
    required_keys = {
        "votes": {},
        "topics": [],
        "num_rooms": 3,
        "num_slots": 4,
        "max_votes": 4,
        "room_names": [],
        "booked_slots": {}
    }
    for key, default in required_keys.items():
        if key not in application.bot_data:
            application.bot_data[key] = default

    # Добавление обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin))
    
    # Диалог добавления темы пользователем
    add_topic_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('addtopicuser', add_topic_user)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            ADD_CATEGORY: [CallbackQueryHandler(select_category)],
            ADD_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_topic_user)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_add_topic),
            MessageHandler(filters.COMMAND, cancel_add_topic),
        ],
        per_user=True,
        name="add_topic_user_conv",
        persistent=True,
    )
    application.add_handler(add_topic_conv_handler)
    
    # Добавьте остальные обработчики (vote, finalize, bookslot и т.д.)
    # Пример:
    # application.add_handler(CommandHandler('vote', vote))
    # application.add_handler(CallbackQueryHandler(button))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)

    logger.info("Запуск бота.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
