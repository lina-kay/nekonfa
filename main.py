import os
import logging
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, PicklePersistence
)
from telegram.error import BadRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TOKEN')
TOPICS_CHAT = os.getenv('TOPICS_CHAT')
VOTING_CHAT = os.getenv('VOTING_CHAT')
PERSISTENCE_PATH = os.getenv('PERSISTENCE_PATH', 'bot_data.pkl')

if not TOKEN or not TOPICS_CHAT or not VOTING_CHAT:
    logger.error("Ошибка: не все переменные окружения установлены.")
    exit(1)

persistence = PicklePersistence(filepath=PERSISTENCE_PATH)

ROOM_SELECTION, SLOT_SELECTION = range(2)
ADD_NAME, ADD_CATEGORY, ADD_TOPIC = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    bot_username = (await bot.get_me()).username
    chat = update.effective_chat
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    if chat.type == 'private':
        user_id = chat.id
        if context.args and context.args[0].startswith("vote_"):
            arg = context.args[0][5:]
            if '_' in arg:
                source_chat_id, thread_id = map(int, arg.split('_', 1))
            else:
                source_chat_id = int(arg)
                thread_id = None
            context.user_data['source_chat_id'] = source_chat_id
            context.user_data['source_thread_id'] = thread_id
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
            await bot.send_message(
                chat_id=user_id,
                text="Добро пожаловать!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        chat_id = chat.id
        if message_thread_id:
            arg = f"{chat_id}_{message_thread_id}"
        else:
            arg = f"{chat_id}"
        vote_url = f"https://t.me/{bot_username}?start=vote_{arg}"
        add_topic_url = f"https://t.me/{bot_username}?start=addtopicuser"
        keyboard = [
            [InlineKeyboardButton("Перейти к голосованию", url=vote_url)],
            [InlineKeyboardButton("Добавить тему", url=add_topic_url)]
        ]
        await bot.send_message(
            chat_id=chat_id,
            text="Добро пожаловать!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            message_thread_id=message_thread_id
        )

async def finalize_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    bot_data = context.bot_data
    num_rooms = bot_data.get('num_rooms', 3)
    num_slots = bot_data.get('num_slots', 4)
    room_names = bot_data.get('room_names', [f"Зал {i+1}" for i in range(num_rooms)])
    booked_slots = bot_data.get('booked_slots', {})
    all_votes = []
    for votes in bot_data.get("votes", {}).values():
        all_votes.extend(votes)
    if not all_votes:
        await update.message.reply_text("Нет голосов.", message_thread_id=message_thread_id)
        return
    vote_count = Counter(all_votes)
    sorted_votes = sorted(vote_count.items(), key=lambda x: -x[1])
    total = sum(vote_count.values())
    schedule = {room: [] for room in room_names}
    topic_index = 0
    for room in room_names:
        for slot in range(1, num_slots+1):
            if room in booked_slots and slot in booked_slots[room]:
                schedule[room].append("Забронировано")
            else:
                if topic_index < len(sorted_votes):
                    schedule[room].append(sorted_votes[topic_index][0])
                    topic_index +=1
                else:
                    schedule[room].append("Пусто")
    schedule_text = "<b>Расписание:</b>\n"
    for room, slots in schedule.items():
        schedule_text += f"\n{room}:\n"
        for i, s in enumerate(slots, 1):
            schedule_text += f"Слот {i}: {s}\n"

    unscheduled_topics = sorted_votes[topic_index:]
    if unscheduled_topics:
        unscheduled_text = "\n\n<b>Приоритетные темы вне расписания:</b>\n"
        for topic, count in unscheduled_topics:
            unscheduled_text += f"• {topic} ({count} голосов)\n"
    else:
        unscheduled_text = "\n\nНет тем вне расписания."

    final_message = f"{schedule_text}{unscheduled_text}"
    await update.message.reply_text(final_message, parse_mode='HTML', message_thread_id=message_thread_id)

async def add_topic_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Введите ваше имя:")
    return ADD_NAME

async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("Создать", callback_data='создать')],
        [InlineKeyboardButton("Обсудить", callback_data='обсудить')],
        [InlineKeyboardButton("Объединиться", callback_data='объединиться')]
    ]
    await update.message.reply_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_CATEGORY

async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['category'] = query.data
    await query.edit_message_text("Введите название темы:")
    return ADD_TOPIC

async def receive_topic_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = context.user_data.get('name', 'Аноним')
    category = context.user_data.get('category', 'Не определено')
    topic = f"{name}: {category}. {update.message.text.strip()}"
    context.bot_data["topics"] = context.bot_data.get("topics", []) + [topic]
    await update.message.reply_text(f"Тема добавлена:\n{topic}", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel_add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Добавление отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main() -> None:
    app = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    conv_handlers = [
        ConversationHandler(
            entry_points=[CommandHandler('bookslot', book_slot_start)],
            states={
                ROOM_SELECTION: [CallbackQueryHandler(book_slot_room_selection)],
                SLOT_SELECTION: [CallbackQueryHandler(book_slot_slot_selection)]
            },
            fallbacks=[CommandHandler('cancel', book_slot_cancel)],
            name="book_slot"
        ),
        ConversationHandler(
            entry_points=[CommandHandler('addtopicuser', add_topic_user), MessageHandler(filters.Regex("^/start addtopicuser$"), add_topic_user)],
            states={
                ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
                ADD_CATEGORY: [CallbackQueryHandler(select_category)],
                ADD_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_topic_user)]
            },
            fallbacks=[CommandHandler('cancel', cancel_add_topic)],
            name="add_topic_user"
        )
    ]
    for ch in conv_handlers:
        app.add_handler(ch)

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('admin', admin))
    app.add_handler(CommandHandler('namerooms', name_rooms))
    app.add_handler(CommandHandler('vote', vote))
    app.add_handler(CommandHandler('changevote', vote))
    app.add_handler(CommandHandler('finalize', finalize_votes))
    app.add_handler(CommandHandler('addtopic', add_topic))
    app.add_handler(CommandHandler('done', done_adding_topics))
    app.add_handler(CommandHandler('removetopic', remove_topic))
    app.add_handler(CommandHandler('clearbookings', clear_bookings))
    app.add_handler(CommandHandler('setrooms', set_rooms))
    app.add_handler(CommandHandler('setslots', set_slots))
    app.add_handler(CommandHandler('setvotes', set_votes))
    app.add_handler(CommandHandler('clearvotes', clear_votes))
    app.add_handler(CommandHandler('cleartopics', clear_topics))
    app.add_handler(CommandHandler('countvotes', count_votes))
    app.add_handler(CommandHandler('topiclist', topic_list))
    app.add_handler(CommandHandler('secret', secret))

    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    app.add_error_handler(lambda u,c: logger.error("Ошибка: %s", c.error))

    app.run_polling()

if __name__ == '__main__':
    main()
