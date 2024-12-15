import os
import logging
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, PicklePersistence
)
from telegram.error import BadRequest

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чтение токена бота и ссылок из переменных окружения
TOKEN = os.getenv('TOKEN')  # Ваш токен бота
TOPICS_CHAT = os.getenv('TOPICS_CHAT')  # Ссылка на чат с темами
VOTING_CHAT = os.getenv('VOTING_CHAT')  # Ссылка на чат для голосования

if not TOKEN or not TOPICS_CHAT or not VOTING_CHAT:
    logger.error("Необходимо установить переменные окружения TOKEN, TOPICS_CHAT и VOTING_CHAT.")
    exit(1)

persistence = PicklePersistence(filepath="bot_data.pkl")

# Состояния для ConversationHandler
ROOM_SELECTION, SLOT_SELECTION, TOPIC_ENTRY = range(3)  # Значения: 0, 1, 2

def convert_booked_slots(bot_data):
    booked_slots = bot_data.get('booked_slots', {})

    if not isinstance(booked_slots, dict):
        bot_data['booked_slots'] = {}
        return

    for room, slots in list(booked_slots.items()):
        if isinstance(slots, list):
            # Если слоты представлены списком, преобразуем их в словарь
            new_slots = {}
            for slot_num in slots:
                new_slots[int(slot_num)] = {'topic': 'Забронировано'}
            booked_slots[room] = new_slots
        elif isinstance(slots, dict):
            # Убеждаемся, что ключи слотов — целые числа
            new_slots = {}
            for slot_num, slot_data in slots.items():
                new_slots[int(slot_num)] = slot_data
            booked_slots[room] = new_slots
        else:
            # Если формат неизвестен, удаляем записи для этой комнаты
            del booked_slots[room]
    bot_data['booked_slots'] = booked_slots

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    bot_username = (await bot.get_me()).username
    chat = update.effective_chat
    chat_type = chat.type
    message_thread_id = update.message.message_thread_id if update.message else None

    if chat_type == 'private':
        user_id = chat.id
        if context.args and context.args[0].startswith("vote_"):
            arg = context.args[0][5:]  # Убираем 'vote_'
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
        else:
            vote_url = f"https://t.me/{bot_username}?start=vote"
            keyboard = [[InlineKeyboardButton("Перейти к голосованию", url=vote_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            welcome_message = "Привет! Нажмите кнопку ниже, чтобы перейти к голосованию."
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
    message_thread_id = update.message.message_thread_id if update.message else None

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
        "/bookslot - Забронировать слот в зале\n"
        "/editbooking - Редактировать название темы в забронированном слоте\n\n"
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
            slots_info = []
            for slot_num, slot_data in slots.items():
                topic_title = slot_data.get('topic', 'Забронировано')
                slots_info.append(f"Слот {slot_num}: {topic_title}")
            slots_str = '; '.join(slots_info)
            booked_info += f"{room}: {slots_str}\n"
        admin_message += booked_info

    await update.message.reply_text(
        text=admin_message,
        parse_mode='HTML',
        message_thread_id=message_thread_id
    )

async def name_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_room_names'] = True
    await update.message.reply_text(
        "Введите названия залов, разделяя их точкой с запятой (;). Например:\n"
        "'Основной зал; Малая аудитория; Зал для дискуссий'"
    )

async def receive_room_names(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if not user_data.get('awaiting_room_names', False):
        return
    text = update.message.text.strip()
    room_names = [name.strip() for name in text.split(';') if name.strip()]
    if not room_names:
        await update.message.reply_text("Вы не ввели ни одного названия. Пожалуйста, повторите ввод.")
        return
    context.bot_data['room_names'] = room_names
    await update.message.reply_text(f"Названия залов установлены: {', '.join(room_names)}")
    user_data['awaiting_room_names'] = False

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    command = update.message.text.strip().lower()
    if command == '/vote':
        if str(user_id) in context.bot_data.get("votes", {}):
            await update.message.reply_text(
                "Вы уже проголосовали. Используйте команду /changevote, чтобы изменить свой голос."
            )
            return
    topics = context.bot_data.get("topics", [])
    if not topics:
        await update.message.reply_text("Нет доступных тем для голосования.")
        return
    if str(user_id) in context.bot_data.get("votes", {}):
        context.user_data["vote_selection"] = context.bot_data.get("votes", {}).get(str(user_id), []).copy()
    else:
        context.user_data["vote_selection"] = []
    await send_vote_message(user_id, context)

async def send_vote_message(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    selected_topics = context.user_data.get("vote_selection", [])
    topics = context.bot_data.get("topics", [])
    if not topics:
        await context.bot.send_message(chat_id=user_id, text="Нет доступных тем для голосования.")
        return
    max_votes = context.bot_data.get('max_votes', 4)
    keyboard = [
        [InlineKeyboardButton(f"{'✅ ' if topic in selected_topics else ''}{topic}", callback_data=str(i))]
        for i, topic in enumerate(topics)
    ]
    keyboard.append([
        InlineKeyboardButton("Отправить", callback_data="submit_votes"),
    ])
    keyboard.append([
        InlineKeyboardButton("Спикеры и Темы", url=TOPICS_CHAT)
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    vote_message = (
        f"Выберите темы, которые вам интересны (максимум {max_votes}):\n"
        "Когда закончите, нажмите кнопку \"Отправить\" для подтверждения вашего выбора."
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=vote_message, reply_markup=reply_markup)
    except BadRequest as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    try:
        await query.answer()
    except BadRequest as e:
        logger.warning(f"Ошибка при ответе на CallbackQuery: {e}")

    user_id = query.from_user.id
    selected_data = query.data
    user_data = context.user_data
    bot = context.bot

    if selected_data == "submit_votes":
        if "vote_selection" not in user_data:
            await query.answer("Вы не выбрали ни одной темы.", show_alert=True)
            return
        selected_topics = user_data["vote_selection"]
        if len(selected_topics) == 0:
            await query.answer("Вы не выбрали ни одной темы.", show_alert=True)
            return
        votes = context.bot_data.get("votes", {})
        votes[str(user_id)] = selected_topics.copy()
        context.bot_data["votes"] = votes
        try:
            selected_topics_text = "\n".join([f"• {topic}" for topic in selected_topics])
            return_keyboard = [
                [InlineKeyboardButton("Переголосовать", callback_data="changevote")],
                [InlineKeyboardButton("Вернуться в чат", url=VOTING_CHAT)]
            ]
            reply_markup = InlineKeyboardMarkup(return_keyboard)
            await query.edit_message_text(
                text=f"Спасибо за голосование! Вы проголосовали за следующие темы:\n{selected_topics_text}",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            return
    elif selected_data == "changevote":
        user_data["vote_selection"] = context.bot_data.get("votes", {}).get(str(user_id), []).copy()
        await send_vote_message(user_id, context)
        return
    elif selected_data == "cancel_remove":
        await query.edit_message_text(text="Удаление тем отменено.")
        user_data.pop('remove_selection', None)
        return
    elif selected_data == "submit_remove":
        if 'remove_selection' not in user_data or not user_data['remove_selection']:
            await query.answer("Вы не выбрали ни одной темы для удаления.", show_alert=True)
            return
        topics = context.bot_data.get("topics", [])
        # Удаляем выбранные темы
        for topic in user_data['remove_selection']:
            if topic in topics:
                topics.remove(topic)
        context.bot_data["topics"] = topics
        await query.edit_message_text(text="Выбранные темы были удалены.")
        user_data.pop('remove_selection', None)
        return
    elif selected_data.startswith("rem_"):
        index = int(selected_data[4:])
        topics = context.bot_data.get("topics", [])
        if index < 0 or index >= len(topics):
            await query.answer("Неверный выбор.", show_alert=True)
            return
        selected_topic = topics[index]

        if 'remove_selection' not in user_data:
            user_data['remove_selection'] = []

        if selected_topic in user_data['remove_selection']:
            user_data['remove_selection'].remove(selected_topic)
        else:
            user_data['remove_selection'].append(selected_topic)

        keyboard = [
            [InlineKeyboardButton(
                f"{'✅ ' if topic in user_data['remove_selection'] else ''}{topic}",
                callback_data=f"rem_{i}"
            )] for i, topic in enumerate(topics)
        ]
        keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_remove")])
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel_remove")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка при обновлении клавиатуры: {e}")
    elif selected_data.isdigit():
        topics = context.bot_data.get("topics", [])
        try:
            index = int(selected_data)
            if index < 0 or index >= len(topics):
                raise ValueError()
            selected_topic = topics[index]
        except (ValueError, IndexError):
            await query.answer("Неверный выбор.", show_alert=True)
            return

        if "vote_selection" not in user_data:
            user_data["vote_selection"] = context.bot_data.get("votes", {}).get(str(user_id), []).copy()

        max_votes = context.bot_data.get('max_votes', 4)

        if selected_topic in user_data["vote_selection"]:
            user_data["vote_selection"].remove(selected_topic)
        else:
            if len(user_data["vote_selection"]) < max_votes:
                user_data["vote_selection"].append(selected_topic)
            else:
                await query.answer("Вы достигли лимита голосов. Снимите отметку с одной из тем, чтобы выбрать новую.", show_alert=True)
                return

        keyboard = [
            [InlineKeyboardButton(f"{'✅ ' if topic in user_data['vote_selection'] else ''}{topic}", callback_data=str(i))]
            for i, topic in enumerate(topics)
        ]
        keyboard.append([
            InlineKeyboardButton("Отправить", callback_data="submit_votes"),
        ])
        keyboard.append([
            InlineKeyboardButton("Спикеры и Темы", url=TOPICS_CHAT)
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка при обновлении клавиатуры: {e}")
    else:
        await query.answer("Неверный выбор.", show_alert=True)

# Здесь идет исправленная функция finalize_votes

async def finalize_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.message.message_thread_id if update.message else None

    num_rooms = context.bot_data.get('num_rooms', 3)
    num_slots = context.bot_data.get('num_slots', 4)
    room_names = context.bot_data.get('room_names', [f"Зал {i + 1}" for i in range(num_rooms)])
    booked_slots = context.bot_data.get('booked_slots', {})

    # Убеждаемся, что ключи в booked_slots и room_bookings являются целыми числами
    for room_name in booked_slots:
        booked_slots[room_name] = {int(k): v for k, v in booked_slots[room_name].items()}

    votes_data = context.bot_data.get("votes", {})
    num_voters = len(votes_data)

    # Собираем все голоса
    all_votes = []
    for votes in votes_data.values():
        all_votes.extend(votes)

    # Если нет голосов и нет забронированных слотов, сообщаем об этом
    if not all_votes and not booked_slots:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Нет голосов для обработки и нет забронированных слотов.",
            message_thread_id=message_thread_id
        )
        return

    vote_count = Counter(all_votes)
    sorted_vote_count = vote_count.most_common()

    # Получаем список всех тем из голосования
    topics = context.bot_data.get("topics", [])

    # Собираем список тем из забронированных слотов
    booked_topics = []
    for room_bookings in booked_slots.values():
        for booking in room_bookings.values():
            topic_title = booking.get('topic', 'Забронировано')
            booked_topics.append(topic_title)

    # Объединяем темы из голосования и темы из забронированных слотов
    all_topics = set(topics + booked_topics)

    # Формируем статистику голосования
    vote_stats = f"<b>Статистика голосования:</b>\n"
    vote_stats += f"<b>Проголосовало пользователей:</b> {num_voters}\n"
    if sorted_vote_count:
        vote_stats += "\n".join([f"• {topic} - {count} голос(ов)" for topic, count in sorted_vote_count])
    else:
        vote_stats += "Нет голосов."

    # Начинаем составление расписания
    schedule = {}
    topic_index = 0
    scheduled_topics = set(booked_topics)  # Начинаем с забронированных тем

    # Получаем отсортированный список тем для распределения (исключая забронированные темы)
    sorted_topics = [topic for topic, _ in sorted_vote_count if topic not in scheduled_topics]

    for room_index in range(num_rooms):
        room_name = room_names[room_index] if room_index < len(room_names) else f"Зал {room_index + 1}"
        schedule[room_name] = []
        for slot_index in range(num_slots):
            slot_number = slot_index + 1
            topic_assigned = False

            if room_name in booked_slots:
                room_bookings = booked_slots[room_name]
                if isinstance(room_bookings, dict):
                    if slot_number in room_bookings:
                        booking = room_bookings[slot_number]
                        topic_title = booking.get('topic', 'Забронировано')
                        schedule[room_name].append(topic_title)
                        topic_assigned = True

            if not topic_assigned:
                # Пропускаем уже расписанные темы
                while topic_index < len(sorted_topics) and sorted_topics[topic_index] in scheduled_topics:
                    topic_index += 1
                if topic_index < len(sorted_topics):
                    topic = sorted_topics[topic_index]
                    schedule[room_name].append(topic)
                    scheduled_topics.add(topic)
                    topic_index += 1
                else:
                    schedule[room_name].append("Пусто")

    # Формируем текст расписания
    schedule_text = "<b>Распределение тем:</b>\n\n"
    for room_name in schedule:
        schedule_text += f"<b><u>{room_name}</u></b>\n"
        topics_in_room = schedule[room_name]
        for slot_num, topic in enumerate(topics_in_room):
            schedule_text += f"<b>Слот {slot_num + 1}:</b> {topic}\n"
        schedule_text += "\n"

    # Определяем темы, не попавшие в расписание
    unscheduled_topics = all_topics - scheduled_topics
    if unscheduled_topics:
        unscheduled_text = "<b>Темы вне расписания:</b>\n"
        for topic in unscheduled_topics:
            count = vote_count.get(topic, 0)
            unscheduled_text += f"• {topic} - {count} голос(ов)\n"
    else:
        unscheduled_text = ""

    final_message = f"{vote_stats}\n\n{schedule_text}"
    if unscheduled_text:
        final_message += f"\n{unscheduled_text}"

    await context.bot.send_message(
        chat_id=chat_id,
        text=final_message,
        parse_mode='HTML',
        message_thread_id=message_thread_id
    )

# Остальные функции остаются без изменений
# Включите все функции, которые были ранее, без изменений

# Регистрация обработчиков и запуск бота

def main() -> None:
    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    convert_booked_slots(application.bot_data)

    # Регистрация обработчиков команд
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

    # Регистрация ConversationHandler до общего CallbackQueryHandler
    book_slot_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('bookslot', book_slot_start)],
        states={
            ROOM_SELECTION: [CallbackQueryHandler(book_slot_room_selection, pattern='^bookroom_')],
            SLOT_SELECTION: [CallbackQueryHandler(book_slot_slot_selection, pattern='^bookslot_')],
            TOPIC_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, book_slot_topic_entry)],
        },
        fallbacks=[CommandHandler('cancel', book_slot_cancel)],
        name="book_slot_conv",
        persistent=True,
    )
    application.add_handler(book_slot_conv_handler)

    edit_booking_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('editbooking', edit_booking_start)],
        states={
            ROOM_SELECTION: [CallbackQueryHandler(edit_booking_room_selection, pattern='^editroom_')],
            SLOT_SELECTION: [CallbackQueryHandler(edit_booking_slot_selection, pattern='^editslot_')],
            TOPIC_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_booking_topic_entry)],
        },
        fallbacks=[CommandHandler('cancel', book_slot_cancel)],
        name="edit_booking_conv",
        persistent=True,
    )
    application.add_handler(edit_booking_conv_handler)

    # Общий CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(button, pattern='^(submit_votes|changevote|submit_remove|cancel_remove|rem_.*|^\d+$)'))

    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    logger.info("Запуск бота.")
    application.run_polling()

if __name__ == '__main__':
    main()
