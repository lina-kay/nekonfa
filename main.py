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

# Состояния для ConversationHandler
ROOM_SELECTION, SLOT_SELECTION = range(2)
ADD_NAME, ADD_CATEGORY, ADD_TOPIC = range(3)

# ... (все остальные функции остаются без изменений) ...

def main() -> None:
    global application  # Инициализация как глобальной переменной
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .persistence(persistence)
        .build()
    )

    # Инициализация всех необходимых ключей в bot_data
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

    # Обработчики диалогов
    book_slot_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('bookslot', book_slot_start)],
        states={
            ROOM_SELECTION: [CallbackQueryHandler(book_slot_room_selection)],
            SLOT_SELECTION: [CallbackQueryHandler(book_slot_slot_selection)],
        },
        fallbacks=[CommandHandler('cancel', book_slot_cancel)],
        per_user=True,
        name="book_slot_conv",
        persistent=True,
    )

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

    # Добавление всех обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin))
    application.add_handler(CommandHandler('namerooms', name_rooms))
    application.add_handler(CommandHandler('vote', vote))
    application.add_handler(CommandHandler('changevote', vote))
    application.add_handler(CommandHandler('finalize', finalize_votes))
    application.add_handler(CommandHandler('addtopic', add_topic))
    application.add_handler(CommandHandler('done', done_adding_topics))
    application.add_handler(CommandHandler('removetopic', remove_topic))
    application.add_handler(CommandHandler('clearbookings', clear_bookings))
    application.add_handler(CommandHandler('setrooms', set_rooms))
    application.add_handler(CommandHandler('setslots', set_slots))
    application.add_handler(CommandHandler('setvotes', set_votes))
    application.add_handler(CommandHandler('clearvotes', clear_votes))
    application.add_handler(CommandHandler('cleartopics', clear_topics))
    application.add_handler(CommandHandler('countvotes', count_votes))
    application.add_handler(CommandHandler('topiclist', topic_list))
    application.add_handler(CommandHandler('secret', secret))

    # Добавление диалоговых обработчиков
    application.add_handler(book_slot_conv_handler)
    application.add_handler(add_topic_conv_handler)

    # Остальные обработчики
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    application.add_error_handler(error_handler)

    logger.info("Запуск бота.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
