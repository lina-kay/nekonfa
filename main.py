№кажется финальная версия но это не факт
import nest_asyncio
nest_asyncio.apply()

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
TOKEN = os.getenv('TOKEN')
TOPICS_CHAT = os.getenv('TOPICS_CHAT')
VOTING_CHAT = os.getenv('VOTING_CHAT')

if not TOKEN:
    logger.error("Ошибка: переменная окружения TOKEN не установлена.")
    exit(1)

if not TOPICS_CHAT:
    logger.error("Ошибка: переменная окружения TOPICS_CHAT не установлена.")
    exit(1)

if not VOTING_CHAT:
    logger.error("Ошибка: переменная окружения VOTING_CHAT не установлена.")
    exit(1)

persistence = PicklePersistence(filepath="bot_data.pkl")

# Состояния для ConversationHandler
ROOM_SELECTION, SLOT_SELECTION, ENTER_BOOKING_NAME = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
     # Функция start без изменений
    bot = context.bot
    bot_username = (await bot.get_me()).username
    chat = update.effective_chat
    chat_type = chat.type
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    if chat_type == 'private':
        user_id = chat.id
        if context.args and context.args[0].startswith("vote_"):
             # Извлекаем chat_id и message_thread_id
            arg = context.args[0][5:]  # Убираем 'vote_'
            if '_' in arg:
                source_chat_id_str, thread_id_str = arg.split('_', 1)
                source_chat_id = int(source_chat_id_str)
                source_thread_id = int(thread_id_str)
            else:
                source_chat_id = int(arg)
                source_thread_id = None
            # Сохраняем информацию о чате и теме
            context.user_data['source_chat_id'] = source_chat_id
            context.user_data['source_thread_id'] = source_thread_id
            await send_vote_message(user_id, context)
        elif context.args and context.args[0] == "vote":
            # Обрабатываем случай без дополнительных аргументов
            await send_vote_message(user_id, context)
        else:
            vote_url = f"https://t.me/{bot_username}?start=vote"
            keyboard = [[InlineKeyboardButton("Перейти к голосованию", url=vote_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            welcome_message = "Привет! Нажмите кнопку ниже, чтобы перейти к голосованию."
            await bot.send_message(chat_id=user_id, text=welcome_message, reply_markup=reply_markup)
    elif chat_type in ['group', 'supergroup']:
        chat_id = chat.id
        chat_username = chat.username
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
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    # Получаем текущие настройки
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

    # Информация о забронированных слотах
    if booked_slots:
        booked_info = "\n<b>Забронированные слоты:</b>\n"
        for room, slots in booked_slots.items():
            slots_str = ', '.join(f"{slot} ({name})" for slot, name in slots.items())
            booked_info += f"{room}: слоты {slots_str}\n"
        admin_message += booked_info

    await update.message.reply_text(
        text=admin_message,
        parse_mode='HTML',
        message_thread_id=message_thread_id
    )

async def name_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Функция name_rooms без изменений
    user_data = context.user_data
    user_data.clear()
    user_data['awaiting_room_names'] = True # Устанавливаем флаг для текущей команды
    await update.message.reply_text(
        text="Введите названия залов, разделяя их точкой с запятой (;). Например:\n'Основной зал; Малая аудитория; Зал для дискуссий'"
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
    await update.message.reply_text(
        text=f"Названия залов установлены: {', '.join(room_names)}"
    )
    user_data['awaiting_room_names'] = False # Сбрасываем флаг

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    command = update.message.text.strip().lower()
    if command == '/vote':
        # Если пользователь уже голосовал, не позволяем голосовать снова
        if str(user_id) in context.bot_data.get("votes", {}):
            await update.message.reply_text(
                "Вы уже проголосовали. Используйте команду /changevote, чтобы изменить свой голос."
            )
            return
    # В обоих случаях (vote и changevote) продолжаем к голосованию
    topics = context.bot_data.get("topics", [])
    if not topics:
        await update.message.reply_text("Нет доступных тем для голосования.")
        return
    # Если пользователь уже голосовал и это changevote, загружаем его предыдущий выбор
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
    # Добавляем кнопку "Отправить" и кнопку с ссылкой на TOPICS_CHAT
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

    # Ответить на колбэк как можно раньше
    try:
        await query.answer()
    except BadRequest as e:
        logger.warning(f"Ошибка при ответе на CallbackQuery: {e}")

    user_id = update.effective_user.id
    selected_data = query.data
    user_data = context.user_data

    if selected_data == "submit_votes":
        # Обработка отправки голосов
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
        # Обработка изменения голоса
        user_data["vote_selection"] = context.bot_data.get("votes", {}).get(str(user_id), []).copy()
        await send_vote_message(user_id, context)
        return
    elif selected_data == "cancel_remove":
        await query.edit_message_text(text="Удаление тем отменено.")
        user_data.pop('remove_selection', None)
        return
    elif selected_data == "submit_remove":
        # Handle submission of topic removal
        if 'remove_selection' not in user_data or not user_data['remove_selection']:
            await query.answer("Вы не выбрали ни одной темы для удаления.", show_alert=True)
            return
        topics = context.bot_data.get("topics", [])
        # Remove selected topics
        for topic in user_data['remove_selection']:
            if topic in topics:
                topics.remove(topic)
        context.bot_data["topics"] = topics
        await query.edit_message_text(text="Выбранные темы были удалены.")
        user_data.pop('remove_selection', None)
        return
    elif selected_data.startswith("rem_"):
        # Handle topic selection for removal
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

        # Update the keyboard to reflect the selection
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
        # Обработка выбора тем для голосования
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
        # Добавляем кнопки "Отправить" и ссылку на TOPICS_CHAT
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
        # Обработка других случаев
        await query.answer("Неверный выбор.", show_alert=True)

async def finalize_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    num_rooms = context.bot_data.get('num_rooms', 3)
    num_slots = context.bot_data.get('num_slots', 4)
    room_names = context.bot_data.get('room_names', [f"Зал {i + 1}" for i in range(num_rooms)])
    booked_slots = context.bot_data.get('booked_slots', {})

    all_votes = []
    votes_data = context.bot_data.get("votes", {})
    for votes in votes_data.values():
        all_votes.extend(votes)
    if not all_votes:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Нет голосов для обработки.",
            message_thread_id=message_thread_id
        )
        return
    vote_count = Counter(all_votes)
    sorted_vote_count = vote_count.most_common()
    total_votes = sum(vote_count.values())
    vote_stats = f"<b>Статистика голосов:</b>\n"
    vote_stats += f"<b>Всего голосов:</b> {total_votes}\n"
    vote_stats += "\n".join([f"• {topic} - {count} голос(ов)" for topic, count in sorted_vote_count])
    sorted_topics = [topic for topic, _ in sorted_vote_count]

    schedule = {}
    topic_index = 0
    scheduled_topics = set()
    for room_index in range(num_rooms):
        room_name = room_names[room_index] if room_index < len(room_names) else f"Зал {room_index + 1}"
        schedule[room_name] = []
        for slot_index in range(num_slots):
            # Проверяем, забронирован ли этот слот
            if room_name in booked_slots and slot_index + 1 in booked_slots[room_name]:
                schedule[room_name].append(booked_slots[room_name][slot_index + 1])
            elif topic_index < len(sorted_topics):
                topic = sorted_topics[topic_index]
                schedule[room_name].append(topic)
                scheduled_topics.add(topic)
                topic_index += 1
            else:
                schedule[room_name].append("Пусто")

    schedule_text = "<b>Расписание:</b>\n\n"
    for room_name in schedule:
        schedule_text += f"<b>{room_name}</b>\n"
        topics_in_room = schedule[room_name]
        for slot_num, topic in enumerate(topics_in_room):
            schedule_text += f"<b>Слот {slot_num + 1}:</b> {topic}\n"
        schedule_text += "\n"

    # Определяем темы, не попавшие в расписание
    unscheduled_topics = [topic for topic in sorted_topics if topic not in scheduled_topics]
    if unscheduled_topics:
        # Сортируем оставшиеся темы по возрастанию количества голосов
        unscheduled_vote_counts = [(topic, vote_count[topic]) for topic in unscheduled_topics]
        unscheduled_vote_counts.sort(key=lambda x: x[1])  # Сортируем по количеству голосов

        unscheduled_text = "<b>Темы вне расписания:</b>\n"
        for topic, count in unscheduled_vote_counts:
            unscheduled_text += f"• {topic} - {count} голос(ов)\n"
    else:
        unscheduled_text = ""

    final_message = f"{vote_stats}\n\n{schedule_text}"
    if unscheduled_text:
        final_message += f"\n{unscheduled_text}"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
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
        # Здесь можно добавить обработку других сообщений или отправить подсказку пользователю
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

    # Создаем клавиатуру для выбора тем с уникальным callback_data
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
                user = await context.bot.get_chat(int(user_id))
                username = user.full_name or user.username or f"ID: {user_id}"
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
    # Можно добавить отправку сообщения пользователю или администратору о возникшей ошибке

# Добавляем функционал /bookslot

async def book_slot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    bot_data = context.bot_data

    # Сбрасываем другие флаги
    user_data.clear()

    # Получаем список залов
    room_names = bot_data.get('room_names', [f"Зал {i +1}" for i in range(bot_data.get('num_rooms', 3))])

    # Отправляем пользователю список залов для выбора
    keyboard = [[InlineKeyboardButton(room, callback_data=room)] for room in room_names]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Выберите зал для бронирования:", reply_markup=reply_markup)
    return ROOM_SELECTION

async def book_slot_room_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected_room = query.data
    context.user_data['selected_room'] = selected_room

    # Получаем количество слотов
    num_slots = context.bot_data.get('num_slots', 4)

    # Предлагаем выбрать номер слота
    keyboard = [[InlineKeyboardButton(f"Слот {i +1}", callback_data=str(i +1))] for i in range(num_slots)]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Вы выбрали зал: {selected_room}\nТеперь выберите номер слота для бронирования:", reply_markup=reply_markup)
    return SLOT_SELECTION

async def book_slot_slot_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected_slot = int(query.data)
    selected_room = context.user_data['selected_room']
    context.user_data['selected_slot'] = selected_slot

    await query.edit_message_text(f"Вы выбрали слот {selected_slot} в {selected_room}. Пожалуйста, введите название темы для бронирования:")
    return ENTER_BOOKING_NAME

async def enter_booking_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    booking_name = update.message.text
    selected_room = context.user_data['selected_room']
    selected_slot = context.user_data['selected_slot']

    booked_slots = context.bot_data.get('booked_slots', {})
    if selected_room not in booked_slots:
        booked_slots[selected_room] = {}
    booked_slots[selected_room][selected_slot] = booking_name
    context.bot_data['booked_slots'] = booked_slots

    await update.message.reply_text(f"Вы успешно забронировали слот {selected_slot} в {selected_room} с темой: {booking_name}.")

    booked_info = "<b>Забронированные слоты:</b>\n"
    for room, slots in booked_slots.items():
        slots_str = ', '.join(f"{slot} ({name})" for slot, name in slots.items())
        booked_info += f"<b>{room}:</b> слоты {slots_str}\n"

    await update.message.reply_text(booked_info, parse_mode='HTML')

    return ConversationHandler.END

async def book_slot_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Бронирование отменено.")
    return ConversationHandler.END

def main() -> None:
    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()

    # Регистрация команд
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

    # Обработчики для /bookslot
    book_slot_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('bookslot', book_slot_start)],
        states={
            ROOM_SELECTION: [CallbackQueryHandler(book_slot_room_selection)],
            SLOT_SELECTION: [CallbackQueryHandler(book_slot_slot_selection)],
            ENTER_BOOKING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_booking_name)],
        },
        fallbacks=[CommandHandler('cancel', book_slot_cancel)],
        name="book_slot_conv",
        persistent=True,
    )
    application.add_handler(book_slot_conv_handler)

    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button))

    # Обработчики сообщений
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, process_message  # Обрабатываем все текстовые сообщения
    ))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    logger.info("Запуск бота.")
    application.run_polling()

if __name__ == '__main__':
    main()
