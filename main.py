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

# Чтение токена бота и ссылок из переменных окружения
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

# Состояния для диалога добавления темы
ADD_NAME, ADD_CATEGORY, ADD_TOPIC = range(3)

# Остальные функции (start, admin, vote и т.д.) остаются без изменений...

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
    topics = context.bot_data.get
