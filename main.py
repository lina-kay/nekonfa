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

# Остальной код (настройки переменных, обработчики команд и функции) остаётся без изменений...

# --- Исправленный диалог для /addtopicuser ---

# Состояния для диалога добавления темы
ADD_NAME, ADD_CATEGORY, ADD_TOPIC = range(3)

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
    
    # Формируем клавиатуру для выбора категории
    keyboard = [
        [InlineKeyboardButton("Создать", callback_data='создать')],
        [InlineKeyboardButton("Обсудить", callback_data='обсудить')],
        [InlineKeyboardButton("Объединиться", callback_data='объединиться')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем сообщение с клавиатурой
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
    
    # Отправляем запрос на ввод темы
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

# --- Обработчик диалога ---
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

# --- Остальные обработчики ---
application.add_handler(add_topic_conv_handler)

# --- Функция process_message с исключением для текущего диалога ---
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    current_conv = user_data.get('current_conversation')
    
    if current_conv == 'add_topic_user_conv':
        return  # Если диалог активен, не перехватываем сообщения
    
    # Остальной код обработки сообщений...
