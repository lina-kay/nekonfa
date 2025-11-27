import os
import logging
from collections import Counter
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, PicklePersistence
)
from telegram.error import BadRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()
TOKEN = os.getenv('TOKEN')
TOPICS_CHAT = os.getenv('TOPICS_CHAT')
VOTING_CHAT = os.getenv('VOTING_CHAT')
PERSISTENCE_PATH = os.getenv('PERSISTENCE_PATH', 'bot_data.pkl')
print("TOKEN:", TOKEN, "TOPICS_CHAT:", TOPICS_CHAT, "VOTING_CHAT:", VOTING_CHAT)
if not TOKEN or not TOPICS_CHAT or not VOTING_CHAT:
    logger.error("Ошибка: не все переменные окружения установлены.")
    exit(1)

persistence = PicklePersistence(filepath=PERSISTENCE_PATH)

ROOM_SELECTION, SLOT_SELECTION, NAME_ROOM_SELECTION, NAME_SLOT_SELECTION, NAME_INPUT = range(5)
ADD_NAME, ADD_CATEGORY, ADD_TOPIC = range(5, 8)

def normalize_booked_slots(bot_data: dict) -> dict:
    """
    Store booked slots as {room: {slot_number: custom_name}} for easier processing.
    Legacy data might keep plain lists, so convert them on the fly.
    """
    booked_slots = bot_data.get('booked_slots', {})
    for room, slots in list(booked_slots.items()):
        if isinstance(slots, list):
            booked_slots[room] = {slot_num: "Забронировано" for slot_num in slots}
    bot_data['booked_slots'] = booked_slots
    return booked_slots

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
            topics_chat_url = f"https://t.me/{TOPICS_CHAT}"
            voting_chat_url = f"https://t.me/{VOTING_CHAT}"
            
            keyboard = [
                [InlineKeyboardButton("Перейти к голосованию", url=vote_url)],
                [InlineKeyboardButton("Добавить тему", url=add_topic_url)],
                [InlineKeyboardButton("Спикеры и темы", url=topics_chat_url)],
                [InlineKeyboardButton("Расписание", url=voting_chat_url)]
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
        topics_chat_url = f"https://t.me/{TOPICS_CHAT}"
        voting_chat_url = f"https://t.me/{VOTING_CHAT}"
        
        keyboard = [
            [InlineKeyboardButton("Перейти к голосованию", url=vote_url)],
            [InlineKeyboardButton("Добавить тему", url=add_topic_url)],
            [InlineKeyboardButton("Спикеры и темы", url=topics_chat_url)],
            [InlineKeyboardButton("Расписание", url=voting_chat_url)]
        ]
        
        await bot.send_message(
            chat_id=chat_id,
            text="Добро пожаловать!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            message_thread_id=message_thread_id
        )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    bot_data = context.bot_data
    num_rooms = bot_data.get('num_rooms', 3)
    num_slots = bot_data.get('num_slots', 4)
    max_votes = bot_data.get('max_votes', 4)
    room_names = bot_data.get('room_names', [])
    votes = bot_data.get("votes", {})
    num_voters = len(votes)
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
            slot_descriptions = ", ".join(
                f"{slot}: {name or 'Забронировано'}" for slot, name in sorted(slots.items())
            )
            booked_info += f"<b>{room}:</b> {slot_descriptions}\n"
        admin_message += booked_info
    await update.message.reply_text(text=admin_message, parse_mode='HTML', message_thread_id=message_thread_id)

async def finalize_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    bot_data = context.bot_data
    num_rooms = bot_data.get('num_rooms', 3)
    num_slots = bot_data.get('num_slots', 4)
    room_names = bot_data.get('room_names', [f"Зал {i+1}" for i in range(num_rooms)])
    booked_slots = normalize_booked_slots(bot_data)
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
    for slot in range(1, num_slots + 1):
        for room in room_names:
            room_bookings = booked_slots.get(room, {})
            if slot in room_bookings:
                schedule[room].append(room_bookings[slot] or "Забронировано")
            else:
                if topic_index < len(sorted_votes):
                    schedule[room].append(sorted_votes[topic_index][0])
                    topic_index += 1
                else:
                    schedule[room].append("Пусто")
    schedule_text = "<b>Расписание:</b>\n"
    for room, slots in schedule.items():
        schedule_text += f"\n{room}:\n"
        room_bookings = booked_slots.get(room, {})
        for i, s in enumerate(slots, 1):
            if i in room_bookings:
                display_name = room_bookings[i] or "Забронировано"
                schedule_text += f"Слот {i}: {display_name} - забронирован\n"
            else:
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

async def name_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_room_names'] = True
    await update.message.reply_text("Введите названия залов через точку с запятой: 'Зал1; Зал2'")

async def receive_room_names(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if not user_data.get('awaiting_room_names'):
        return
    room_names = [n.strip() for n in update.message.text.split(';') if n.strip()]
    if not room_names:
        await update.message.reply_text("Нет названий. Повторите ввод.")
        return
    context.bot_data['room_names'] = room_names
    await update.message.reply_text(f"Названия залов: {', '.join(room_names)}")
    user_data.pop('awaiting_room_names')

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    command = update.message.text.strip().lower()
    if command == '/vote':
        if str(user_id) in context.bot_data.get("votes", {}):
            await update.message.reply_text("Вы уже проголосовали. Используйте /changevote для изменения.")
            return
    elif command == '/changevote':
        if str(user_id) not in context.bot_data.get("votes", {}):
            await update.message.reply_text("Вы не голосовали. Используйте /vote для голосования.")
            return
    topics = context.bot_data.get("topics", [])
    if not topics:
        await update.message.reply_text("Нет доступных тем.")
        return
    max_votes = context.bot_data.get('max_votes', 4)
    current_votes = len(context.user_data.get("vote_selection", []))
    if current_votes >= max_votes:
        await update.message.reply_text(f"Вы уже выбрали максимальное количество тем ({max_votes})")
        return
    context.user_data["vote_selection"] = context.bot_data["votes"].get(str(user_id), []).copy()
    await send_vote_message(user_id, context)

async def send_vote_message(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    selected = context.user_data.get("vote_selection", [])
    topics = context.bot_data.get("topics", [])
    if not topics:
        await context.bot.send_message(chat_id=user_id, text="Нет доступных тем для голосования")
        return
    max_votes = context.bot_data.get('max_votes', 4)
    keyboard = []
    for i, t in enumerate(topics):
        keyboard.append([InlineKeyboardButton(f"{'✅ ' if t in selected else ''}{t}", callback_data=str(i))])
    keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_votes")])
    keyboard.append([InlineKeyboardButton("Спикеры и Темы", url=TOPICS_CHAT)])
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Выберите темы (максимум {max_votes}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    user_data = context.user_data
    bot_data = context.bot_data

    if data == "submit_votes":
        selected = user_data.get("vote_selection", [])
        if not selected:
            await query.answer("Нет выбранных тем.", show_alert=True)
            return
        bot_data["votes"][str(user_id)] = selected.copy()
        selected_text = "\n".join(f"• {t}" for t in selected)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Переголосовать", callback_data="changevote")],
            [InlineKeyboardButton("Вернуться в чат", url=VOTING_CHAT)]
        ])
        await query.edit_message_text(f"Спасибо! Вы проголосовали за:\n{selected_text}", reply_markup=reply_markup)
    elif data == "changevote":
        user_data["vote_selection"] = bot_data["votes"].get(str(user_id), []).copy()
        await send_vote_message(user_id, context)
    elif data.startswith("rem_"):
        idx = int(data[4:])
        topics = bot_data.get("topics", [])
        if idx < 0 or idx >= len(topics):
            return
        selected_topic = topics[idx]
        if 'remove_selection' not in user_data:
            user_data['remove_selection'] = []
        if selected_topic in user_data['remove_selection']:
            user_data['remove_selection'].remove(selected_topic)
        else:
            user_data['remove_selection'].append(selected_topic)
        keyboard = []
        for i, t in enumerate(topics):
            checked = '✅ ' if t in user_data['remove_selection'] else ''
            keyboard.append([InlineKeyboardButton(f"{checked}{t}", callback_data=f"rem_{i}")])
        keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_remove")])
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel_remove")])
        try:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))
        except BadRequest as e:
            if str(e) != "Message is not modified":
                raise
    elif data == "submit_remove":
        if 'remove_selection' in user_data:
            topics = bot_data.get("topics", [])
            new_topics = [t for t in topics if t not in user_data['remove_selection']]
            bot_data["topics"] = new_topics
            await query.edit_message_text("Темы удалены.")
            user_data.pop('remove_selection')
    elif data == "cancel_remove":
        await query.edit_message_text("Удаление отменено.")
        user_data.pop('remove_selection', None)
    elif data.isdigit():
        idx = int(data)
        topics = bot_data.get("topics", [])
        if idx < 0 or idx >= len(topics):
            return
        topic = topics[idx]
        max_votes = bot_data.get('max_votes', 4)
        if "vote_selection" not in user_data:
            user_data["vote_selection"] = []
        if topic in user_data["vote_selection"]:
            user_data["vote_selection"].remove(topic)
        else:
            if len(user_data["vote_selection"]) < max_votes:
                user_data["vote_selection"].append(topic)
            else:
                await query.answer("Превышен лимит.", show_alert=True)
        keyboard = []
        for i, t in enumerate(topics):
            checked = '✅ ' if t in user_data["vote_selection"] else ''
            keyboard.append([InlineKeyboardButton(f"{checked}{t}", callback_data=str(i))])
        keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_votes")])
        keyboard.append([InlineKeyboardButton("Спикеры и Темы", url=TOPICS_CHAT)])
        try:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))
        except BadRequest as e:
            if str(e) != "Message is not modified":
                raise

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data.get('awaiting_room_names'):
        await receive_room_names(update, context)
    elif user_data.get('awaiting_rooms'):
        await set_rooms_text(update, context)
    elif user_data.get('awaiting_slots'):
        await set_slots_text(update, context)
    elif user_data.get('awaiting_votes'):
        await set_votes_text(update, context)
    elif user_data.get('adding_topics'):
        await receive_topic(update, context)
    else:
        await update.message.reply_text("Используйте команды из меню.")

async def set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_rooms'] = True
    await update.message.reply_text("Введите количество залов:")

async def set_rooms_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    try:
        num = int(update.message.text)
        context.bot_data['num_rooms'] = num
        await update.message.reply_text(f"Количество залов: {num}")
    except:
        await update.message.reply_text("Ошибка ввода. Введите число.")
    finally:
        user_data.pop('awaiting_rooms', None)

async def set_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_slots'] = True
    await update.message.reply_text("Введите количество слотов в залах:")

async def set_slots_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    try:
        num = int(update.message.text)
        context.bot_data['num_slots'] = num
        await update.message.reply_text(f"Слотов в залах: {num}")
    except:
        await update.message.reply_text("Ошибка ввода. Введите число.")
    finally:
        user_data.pop('awaiting_slots', None)

async def set_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_votes'] = True
    await update.message.reply_text("Максимальное количество голосов на пользователя:")

async def set_votes_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    try:
        num = int(update.message.text)
        context.bot_data['max_votes'] = num
        await update.message.reply_text(f"Лимит голосов: {num}")
    except:
        await update.message.reply_text("Ошибка ввода. Введите число.")
    finally:
        user_data.pop('awaiting_votes', None)

async def add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    user_data.clear()
    user_data['adding_topics'] = True
    user_data['new_topics'] = []
    await update.message.reply_text("Введите темы через точку с запятой. Для завершения отправьте /done")

async def receive_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data.get('adding_topics'):
        text = update.message.text.strip()
        if ';' in text:
            topics = [t.strip() for t in text.split(';') if t.strip()]
            user_data['new_topics'].extend(topics)
        else:
            user_data['new_topics'].append(text)
        await update.message.reply_text(f"Добавлено тем: {len(user_data['new_topics'])}")

async def done_adding_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data.get('adding_topics'):
        new_topics = user_data.pop('new_topics')
        current_topics = context.bot_data.get('topics', [])
        context.bot_data['topics'] = current_topics + new_topics
        await update.message.reply_text(f"Добавлено тем: {len(new_topics)}")
        user_data.pop('adding_topics')

async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics = context.bot_data.get("topics", [])
    keyboard = []
    for i, t in enumerate(topics):
        keyboard.append([InlineKeyboardButton(t, callback_data=f"rem_{i}")])
    keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_remove")])
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel_remove")])
    await update.message.reply_text("Выберите темы для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

async def clear_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['votes'] = {}
    await update.message.reply_text("Все голоса очищены.")

async def clear_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['topics'] = []
    await update.message.reply_text("Все темы удалены.")

async def clear_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['booked_slots'] = {}
    await update.message.reply_text("Бронирования очищены.")

async def count_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    num = len(context.bot_data.get("votes", {}))
    await update.message.reply_text(f"Проголосовало: {num} человек")

async def topic_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics = context.bot_data.get("topics", [])
    if topics:
        await update.message.reply_text("\n".join(f"{i+1}. {t}" for i, t in enumerate(topics)))
    else:
        await update.message.reply_text("Темы отсутствуют.")

async def secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    votes = context.bot_data.get("votes", {})
    if votes:
        text = []
        for user_id, topics in votes.items():
            try:
                user = await context.bot.get_chat(int(user_id))
                name = user.full_name or user.username or f"ID{user_id}"
            except:
                name = f"ID{user_id}"
            text.append(f"{name} выбрал:\n" + "\n".join(f"• {t}" for t in topics))
        await update.message.reply_text("\n\n".join(text))
    else:
        await update.message.reply_text("Нет данных.")

async def book_slot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    user_data.clear()
    room_names = context.bot_data.get('room_names', [f"Зал {i+1}" for i in range(context.bot_data.get('num_rooms', 3))])
    keyboard = []
    for room in room_names:
        keyboard.append([InlineKeyboardButton(room, callback_data=room)])
    await update.message.reply_text("Выберите зал:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ROOM_SELECTION

async def book_slot_room_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['selected_room'] = query.data
    num_slots = context.bot_data.get('num_slots', 4)
    keyboard = []
    for slot in range(1, num_slots+1):
        keyboard.append([InlineKeyboardButton(f"Слот {slot}", callback_data=str(slot))])
    await query.edit_message_text("Выберите слот:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SLOT_SELECTION

async def book_slot_slot_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected_slot = int(query.data)
    room = context.user_data['selected_room']
    booked_slots = normalize_booked_slots(context.bot_data)
    room_bookings = booked_slots.setdefault(room, {})
    if selected_slot not in room_bookings:
        room_bookings[selected_slot] = "Забронировано"
        context.bot_data['booked_slots'] = booked_slots
        await query.edit_message_text(f"Слот {selected_slot} в {room} забронирован.")
    else:
        await query.edit_message_text(f"Слот {selected_slot} уже занят.")
    return ConversationHandler.END

async def book_slot_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Бронирование отменено.")
    return ConversationHandler.END

async def name_slot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    booked_slots = normalize_booked_slots(context.bot_data)
    if not booked_slots:
        await update.message.reply_text("Нет забронированных слотов.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(room, callback_data=room)]
        for room in booked_slots.keys()
    ]
    await update.message.reply_text(
        "Выберите зал с забронированными слотами:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return NAME_ROOM_SELECTION

async def name_slot_room_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    room = query.data
    booked_slots = normalize_booked_slots(context.bot_data)
    room_bookings = booked_slots.get(room)
    if not room_bookings:
        await query.edit_message_text("В этом зале нет забронированных слотов.")
        return ConversationHandler.END
    context.user_data['naming_room'] = room
    keyboard = []
    for slot, name in sorted(room_bookings.items()):
        display_name = name or "Забронировано"
        keyboard.append([InlineKeyboardButton(f"Слот {slot}: {display_name}", callback_data=str(slot))])
    await query.edit_message_text(
        "Выберите слот для переименования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return NAME_SLOT_SELECTION

async def name_slot_slot_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['naming_slot'] = int(query.data)
    room = context.user_data.get('naming_room', '')
    await query.edit_message_text(f"Введите новое название для {room}, слот {query.data}:")
    return NAME_INPUT

async def set_slot_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    room = context.user_data.get('naming_room')
    slot = context.user_data.get('naming_slot')
    if room is None or slot is None:
        await update.message.reply_text("Слот не выбран. Начните заново с /nameslot.")
        return ConversationHandler.END
    new_name = update.message.text.strip()
    if not new_name:
        await update.message.reply_text("Название не может быть пустым. Введите другое значение.")
        return NAME_INPUT
    booked_slots = normalize_booked_slots(context.bot_data)
    room_bookings = booked_slots.get(room, {})
    if slot not in room_bookings:
        await update.message.reply_text("Этот слот больше не забронирован.")
        return ConversationHandler.END
    room_bookings[slot] = new_name
    context.bot_data['booked_slots'] = booked_slots
    await update.message.reply_text(f"Слот {slot} в {room} теперь называется: {new_name}")
    context.user_data.pop('naming_room', None)
    context.user_data.pop('naming_slot', None)
    return ConversationHandler.END

async def name_slot_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop('naming_room', None)
    context.user_data.pop('naming_slot', None)
    await update.message.reply_text("Переименование отменено.")
    return ConversationHandler.END

async def add_topic_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Введите ваше имя:")
    return ADD_NAME

async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("Поделиться", callback_data='поделиться')],
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
    
    bot_username = (await context.bot.get_me()).username
    vote_url = f"https://t.me/{bot_username}?start=vote"
    add_topic_url = f"https://t.me/{bot_username}?start=addtopicuser"
    
    keyboard = [
        [InlineKeyboardButton("Перейти к голосованию", url=vote_url)],
        [InlineKeyboardButton("Добавить еще тему", url=add_topic_url)]
    ]
    
    await update.message.reply_text(
        f"Тема добавлена:\n<code>{topic}</code>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
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
            entry_points=[CommandHandler('nameslot', name_slot_start)],
            states={
                NAME_ROOM_SELECTION: [CallbackQueryHandler(name_slot_room_selection)],
                NAME_SLOT_SELECTION: [CallbackQueryHandler(name_slot_slot_selection)],
                NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_slot_name)]
            },
            fallbacks=[CommandHandler('cancel', name_slot_cancel)],
            name="name_slot"
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
