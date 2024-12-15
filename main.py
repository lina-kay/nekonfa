import os
import logging
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, PicklePersistence
)
from telegram.error import BadRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TOKEN', 'YOUR_BOT_TOKEN')  # Ваш токен бота
TOPICS_CHAT = os.getenv('TOPICS_CHAT', 'YOUR_TOPICS_CHAT_LINK')  # Ссылка на чат с темами
VOTING_CHAT = os.getenv('VOTING_CHAT', 'YOUR_VOTING_CHAT_LINK')  # Ссылка на чат для голосования

if not TOKEN or not TOPICS_CHAT or not VOTING_CHAT:
    logger.error("Необходимо установить переменные окружения TOKEN, TOPICS_CHAT и VOTING_CHAT.")
    exit(1)

persistence = PicklePersistence(filepath="bot_data.pkl")

ROOM_SELECTION, SLOT_SELECTION, TOPIC_ENTRY = range(3)

def convert_booked_slots(bot_data):
    booked_slots = bot_data.get('booked_slots', {})

    if not isinstance(booked_slots, dict):
        bot_data['booked_slots'] = {}
        return

    for room, slots in list(booked_slots.items()):
        if isinstance(slots, list):
            new_slots = {}
            for slot_num in slots:
                new_slots[int(slot_num)] = {'topic': 'Забронировано'}
            booked_slots[room] = new_slots
        elif isinstance(slots, dict):
            new_slots = {}
            for slot_num, slot_data in slots.items():
                try:
                    slot_num_int = int(slot_num)
                    new_slots[slot_num_int] = slot_data
                except ValueError:
                    continue
            booked_slots[room] = new_slots
        else:
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
            if isinstance(slots, dict):
                for slot_num, slot_data in slots.items():
                    topic_title = slot_data.get('topic', 'Забронировано')
                    slots_info.append(f"Слот {slot_num}: {topic_title}")
            elif isinstance(slots, list):
                for slot_num in slots:
                    slots_info.append(f"Слот {slot_num}: Забронировано")
            else:
                slots_info.append("Неизвестный формат данных")
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

async def finalize_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_thread_id = update.message.message_thread_id if update.message else None

    num_rooms = context.bot_data.get('num_rooms', 3)
    num_slots = context.bot_data.get('num_slots', 4)
    room_names = context.bot_data.get('room_names', [f"Зал {i + 1}" for i in range(num_rooms)])
    booked_slots = context.bot_data.get('booked_slots', {})

    # Преобразуем ключи слотов в целые числа
    for room_name, room_bookings in booked_slots.items():
        if isinstance(room_bookings, dict):
            new_room_bookings = {}
            for slot_num, slot_data in room_bookings.items():
                try:
                    slot_num_int = int(slot_num)
                    new_room_bookings[slot_num_int] = slot_data
                except ValueError:
                    continue
            booked_slots[room_name] = new_room_bookings

    votes_data = context.bot_data.get("votes", {})
    num_voters = len(votes_data)

    all_votes = []
    for votes in votes_data.values():
        all_votes.extend(votes)
    if not all_votes:
        await context.bot.send_message(
            text="Нет голосов для обработки.",
            message_thread_id=message_thread_id
        )
        return
    vote_count = Counter(all_votes)
    sorted_vote_count = vote_count.most_common()

    vote_stats = f"<b>Статистика голосования:</b>\n"
    vote_stats += f"<b>Проголосовало пользователей:</b> {num_voters}\n"
    vote_stats += "\n".join([f"• {topic} - {count} голос(ов)" for topic, count in sorted_vote_count])
    sorted_topics = [topic for topic, _ in sorted_vote_count]

    schedule = {}
    topic_index = 0
    scheduled_topics = set()
    for room_index in range(num_rooms):
        room_name = room_names[room_index] if room_index < len(room_names) else f"Зал {room_index + 1}"
        schedule[room_name] = []
        for slot_index in range(num_slots):
            slot_number = slot_index + 1
            topic_assigned = False
            if room_name in booked_slots:
                room_bookings = booked_slots[room_name]
                if isinstance(room_bookings, dict):
                    if slot_number in room_bookings or str(slot_number) in room_bookings:
                        booking = room_bookings.get(slot_number) or room_bookings.get(str(slot_number))
                        topic_title = booking.get('topic', 'Забронировано')
                        schedule[room_name].append(topic_title)
                        scheduled_topics.add(topic_title)
                        topic_assigned = True
            if not topic_assigned:
                while topic_index < len(sorted_topics) and sorted_topics[topic_index] in scheduled_topics:
                    topic_index += 1
                if topic_index < len(sorted_topics):
                    topic = sorted_topics[topic_index]
                    schedule[room_name].append(topic)
                    scheduled_topics.add(topic)
                    topic_index += 1
                else:
                    schedule[room_name].append("Пусто")

    schedule_text = "<b>Распределение тем:</b>\n\n"
    for room_name in schedule:
        schedule_text += f"<b><u>{room_name}</u></b>\n"
        topics_in_room = schedule[room_name]
        for slot_num, topic in enumerate(topics_in_room):
            schedule_text += f"<b>Слот {slot_num + 1}:</b> {topic}\n"
        schedule_text += "\n"

    unscheduled_topics = [topic for topic in sorted_topics if topic not in scheduled_topics]
    if unscheduled_topics:
        unscheduled_vote_counts = [(topic, vote_count[topic]) for topic in unscheduled_topics]
        unscheduled_vote_counts.sort(key=lambda x: x[1], reverse=True)
        unscheduled_text = "<b>Темы вне расписания:</b>\n"
        for topic, count in unscheduled_vote_counts:
            unscheduled_text += f"• {topic} - {count} голос(ов)\n"
    else:
        unscheduled_text = ""

    final_message = f"{vote_stats}\n\n{schedule_text}"
    if unscheduled_text:
        final_message += f"\n{unscheduled_text}"

    await context.bot.send_message(
        text=final_message,
        parse_mode='HTML',
        message_thread_id=message_thread_id
    )

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data.get('awaiting_room_names', False):
        await receive_room_names(update, context)
    elif user_data.get('awaiting_rooms', False):
        await set_rooms_text(update, context)
    elif user_data.get('awaiting_slots', False):
        await set_slots_text(update, context)
    elif user_data.get('awaiting_votes', False):
        await set_votes_text(update, context)
    elif user_data.get('adding_topics', False):
        await receive_topic(update, context)
    else:
        await update.message.reply_text("Я не совсем понял. Пожалуйста, используйте доступные команды или следуйте инструкциям.")

async def set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_rooms'] = True
    await update.message.reply_text("Введите количество залов:")

async def set_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_slots'] = True
    await update.message.reply_text("Введите количество слотов в каждом зале:")

async def set_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_votes'] = True
    await update.message.reply_text("Введите максимальное количество голосов для каждого участника:")

async def set_rooms_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    text = update.message.text.strip()
    try:
        num_rooms = int(text)
        context.bot_data['num_rooms'] = num_rooms
        await update.message.reply_text(f"Количество залов установлено на {num_rooms}.")
        logger.info(f"Количество залов установлено на {num_rooms}.")
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
    finally:
        user_data['awaiting_rooms'] = False

async def set_slots_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    text = update.message.text.strip()
    try:
        num_slots = int(text)
        context.bot_data['num_slots'] = num_slots
        await update.message.reply_text(f"Количество слотов в каждом зале установлено на {num_slots}.")
        logger.info(f"Количество слотов в каждом зале установлено на {num_slots}.")
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
    finally:
        user_data['awaiting_slots'] = False

async def set_votes_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    text = update.message.text.strip()
    try:
        max_votes = int(text)
        context.bot_data['max_votes'] = max_votes
        await update.message.reply_text(f"Максимальное количество голосов установлено на {max_votes}.")
        logger.info(f"Максимальное количество голосов установлено на {max_votes}.")
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
    finally:
        user_data['awaiting_votes'] = False

async def add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['adding_topics'] = True
    user_data['new_topics'] = []
    await update.message.reply_text(
        "Пожалуйста, введите темы для добавления, разделяя их точкой с запятой (;).\n"
        "Когда закончите ввод, отправьте команду /done."
    )

async def receive_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data.get('adding_topics', False):
        text = update.message.text.strip()
        if ';' in text:
            topics = [topic.strip() for topic in text.split(';') if topic.strip()]
            user_data['new_topics'].extend(topics)
        else:
            if text:
                user_data['new_topics'].append(text)
        await update.message.reply_text(f"Добавлено тем: {len(user_data['new_topics'])}\nКогда закончите ввод, отправьте команду /done.")
    else:
        await update.message.reply_text("Я не совсем понял. Пожалуйста, используйте доступные команды или следуйте инструкциям.")

async def done_adding_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data.get('adding_topics', False):
        topics = context.bot_data.get('topics', [])
        topics.extend(user_data['new_topics'])
        context.bot_data['topics'] = topics
        await update.message.reply_text(f"Темы успешно добавлены:\n{', '.join(user_data['new_topics'])}")
        user_data['adding_topics'] = False
        user_data['new_topics'] = []
    else:
        await update.message.reply_text("Вы ещё не начали добавлять темы. Используйте команду /addtopic, чтобы начать.")

async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    bot_data = context.bot_data

    topics = bot_data.get("topics", [])
    if not topics:
        await update.message.reply_text("Список тем пуст.")
        return

    user_data.clear()

    keyboard = [
        [InlineKeyboardButton(
            f"{topic}", callback_data=f"rem_{i}"
        )] for i, topic in enumerate(topics)
    ]
    keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_remove")])
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel_remove")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = "Выберите темы для удаления:"
    await update.message.reply_text(text=message_text, reply_markup=reply_markup)

async def clear_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['votes'] = {}
    await update.message.reply_text("Все голоса были очищены.")

async def clear_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['topics'] = []
    await update.message.reply_text("Все темы были удалены.")

async def clear_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['booked_slots'] = {}
    await update.message.reply_text("Все бронирования были очищены.")

async def count_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    votes_data = context.bot_data.get("votes", {})
    num_voters = len(votes_data)
    await update.message.reply_text(f"Количество участников, проголосовавших за темы: {num_voters}")

async def topic_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics = context.bot_data.get("topics", [])
    if topics:
        topics_text = '\n'.join([f"{i+1}. {topic}" for i, topic in enumerate(topics)])
        await update.message.reply_text(f"Список тем для голосования:\n{topics_text}")
    else:
        await update.message.reply_text("Список тем пуст.")

async def secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    votes_data = context.bot_data.get("votes", {})
    if votes_data:
        num_voters = len(votes_data)
        message_lines = [f"Количество проголосовавших: {num_voters}\n"]
        for user_id, votes in votes_data.items():
            try:
                user = await context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=int(user_id))
                username = user.user.username or user.user.full_name or f"ID: {user_id}"
            except Exception as e:
                logger.error(f"Ошибка при получении информации о пользователе {user_id}: {e}")
                username = f"ID: {user_id}"
            message_lines.append(f"Пользователь {username} проголосовал за:\n" +
                                 '\n'.join(f"• {topic}" for topic in votes))
        message_text = '\n\n'.join(message_lines)
        await update.message.reply_text(message_text)
    else:
        await update.message.reply_text("Нет данных о голосах.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Произошла ошибка:", exc_info=context.error)

    if update and hasattr(update, "message") and update.message:
        try:
            await update.message.reply_text("Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте ещё раз.")
        except Exception:
            pass

async def book_slot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    bot_data = context.bot_data

    user_data.clear()

    room_names = bot_data.get('room_names', [f"Зал {i +1}" for i in range(bot_data.get('num_rooms', 3))])

    keyboard = [[InlineKeyboardButton(room, callback_data=f"bookroom_{i}")] for i, room in enumerate(room_names)]
    user_data['room_list'] = room_names
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Выберите зал для бронирования:", reply_markup=reply_markup)
    return ROOM_SELECTION

async def book_slot_room_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected_index = int(query.data.split('_')[1])
    room_names = context.user_data['room_list']
    selected_room = room_names[selected_index]
    context.user_data['selected_room'] = selected_room

    num_slots = context.bot_data.get('num_slots', 4)

    keyboard = [[InlineKeyboardButton(f"Слот {i +1}", callback_data=f"bookslot_{i +1}")] for i in range(num_slots)]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Вы выбрали зал: {selected_room}\nТеперь выберите номер слота для бронирования:", reply_markup=reply_markup)
    return SLOT_SELECTION

async def book_slot_slot_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected_slot = int(query.data.split('_')[1])
    selected_room = context.user_data['selected_room']

    booked_slots = context.bot_data.get('booked_slots', {})
    room_slots = booked_slots.get(selected_room, {})

    if selected_slot not in room_slots:
        context.user_data['selected_slot'] = selected_slot
        await query.edit_message_text(f"Введите название темы для слота {selected_slot} в {selected_room}:")
        return TOPIC_ENTRY
    else:
        await query.edit_message_text(f"Слот {selected_slot} в {selected_room} уже забронирован.")
        return ConversationHandler.END

async def book_slot_topic_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    bot_data = context.bot_data

    topic_title = update.message.text.strip()
    if not topic_title:
        await update.message.reply_text("Название темы не может быть пустым. Пожалуйста, введите название темы:")
        return TOPIC_ENTRY

    selected_room = user_data['selected_room']
    selected_slot = user_data['selected_slot']

    if 'booked_slots' not in bot_data:
        bot_data['booked_slots'] = {}
    if selected_room not in bot_data['booked_slots']:
        bot_data['booked_slots'][selected_room] = {}
    bot_data['booked_slots'][selected_room][selected_slot] = {'topic': topic_title}

    await update.message.reply_text(f"Вы успешно забронировали слот {selected_slot} в {selected_room} с темой: {topic_title}")

    booked_slots = bot_data['booked_slots']
    booked_info = "<b>Забронированные слоты:</b>\n"
    for room, slots in booked_slots.items():
        slots_info = []
        for slot_num, slot_data in slots.items():
            topic = slot_data.get('topic', 'Забронировано')
            slots_info.append(f"Слот {slot_num}: {topic}")
        slots_str = '; '.join(slots_info)
        booked_info += f"<b>{room}:</b> {slots_str}\n"

    await update.message.reply_text(booked_info, parse_mode='HTML')

    return ConversationHandler.END

async def book_slot_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Бронирование отменено.")
    return ConversationHandler.END

async def edit_booking_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    bot_data = context.bot_data

    user_data.clear()

    booked_slots = bot_data.get('booked_slots', {})
    if not booked_slots:
        await update.message.reply_text("Нет забронированных слотов для редактирования.")
        return ConversationHandler.END

    room_names = list(booked_slots.keys())
    keyboard = [[InlineKeyboardButton(room, callback_data=f"editroom_{i}")] for i, room in enumerate(room_names)]
    user_data['room_list'] = room_names
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Выберите зал для редактирования бронирования:", reply_markup=reply_markup)
    return ROOM_SELECTION

async def edit_booking_room_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected_index = int(query.data.split('_')[1])
    room_names = context.user_data['room_list']
    selected_room = room_names[selected_index]
    context.user_data['selected_room'] = selected_room

    booked_slots = context.bot_data.get('booked_slots', {})
    room_slots = booked_slots.get(selected_room, {})

    if not isinstance(room_slots, dict):
        if isinstance(room_slots, list):
            new_room_slots = {}
            for slot_num in room_slots:
                new_room_slots[int(slot_num)] = {'topic': 'Забронировано'}
            room_slots = new_room_slots
            booked_slots[selected_room] = room_slots
        else:
            await query.edit_message_text(f"В зале {selected_room} нет забронированных слотов.")
            return ConversationHandler.END

    if not room_slots:
        await query.edit_message_text(f"В зале {selected_room} нет забронированных слотов.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(
            f"Слот {slot_num}: {slot_data.get('topic', 'Забронировано')}",
            callback_data=f"editslot_{slot_num}"
        )]
        for slot_num, slot_data in room_slots.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Выберите слот для редактирования в {selected_room}:", reply_markup=reply_markup)
    return SLOT_SELECTION

async def edit_booking_slot_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected_slot = int(query.data.split('_')[1])
    selected_room = context.user_data['selected_room']

    context.user_data['selected_slot'] = selected_slot

    await query.edit_message_text(f"Введите новое название темы для слота {selected_slot} в {selected_room}:")

    return TOPIC_ENTRY

async def edit_booking_topic_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    bot_data = context.bot_data

    new_topic_title = update.message.text.strip()
    if not new_topic_title:
        await update.message.reply_text("Название темы не может быть пустым. Пожалуйста, введите новое название темы:")
        return TOPIC_ENTRY

    selected_room = user_data['selected_room']
    selected_slot = user_data['selected_slot']

    booked_slots = bot_data.get('booked_slots', {})
    room_slots = booked_slots.get(selected_room, {})

    if selected_slot in room_slots:
        bot_data['booked_slots'][selected_room][selected_slot]['topic'] = new_topic_title
        await update.message.reply_text(f"Вы успешно обновили тему для слота {selected_slot} в {selected_room}: {new_topic_title}")
    else:
        await update.message.reply_text("Выбранный слот не найден. Возможно, он был удалён или изменён.")
        return ConversationHandler.END

    return ConversationHandler.END

def main() -> None:
    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    convert_booked_slots(application.bot_data)

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

    application.add_handler(CallbackQueryHandler(button, pattern='^(submit_votes|changevote|submit_remove|cancel_remove|rem_.*|^\d+$)'))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))

    application.add_error_handler(error_handler)

    logger.info("Запуск бота.")
    application.run_polling()

if __name__ == '__main__':
    main()
