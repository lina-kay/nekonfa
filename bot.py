import nest_asyncio
nest_asyncio.apply()

import os
import logging
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters, PicklePersistence
)
from telegram.error import BadRequest

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TOKEN', 'YOUR_BOT_TOKEN')  # Замените 'YOUR_BOT_TOKEN' на токен вашего бота

if not TOKEN:
    logger.error("Ошибка: переменная окружения TOKEN не установлена.")
    exit(1)

max_votes = 4

persistence = PicklePersistence(filepath="bot_data.pkl")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    bot_username = (await bot.get_me()).username
    chat = update.effective_chat
    chat_type = chat.type
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    if chat_type == 'private':
        user_id = chat.id
        if context.args and context.args[0] == "vote":
            await send_vote_message(user_id, context)
        else:
            vote_url = f"https://t.me/{bot_username}?start=vote"
            keyboard = [[InlineKeyboardButton("Перейти к голосованию", url=vote_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            welcome_message = "Привет! Нажмите кнопку ниже, чтобы перейти к голосованию."
            await bot.send_message(chat_id=user_id, text=welcome_message, reply_markup=reply_markup)
    elif chat_type in ['group', 'supergroup']:
        chat_id = chat.id
        vote_url = f"https://t.me/{bot_username}?start=vote"
        keyboard = [[InlineKeyboardButton("Перейти к голосованию", url=vote_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        welcome_message = "Привет! Нажмите кнопку ниже, чтобы перейти к голосованию."
        await bot.send_message(
            chat_id=chat_id,
            text=welcome_message,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id  # Добавляем message_thread_id
        )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    admin_message = (
        "Администраторские команды:\n"
        "/start - Отправить кнопку \"Перейти к голосованию\"\n"
        "/vote - Голосовать за темы\n"
        "/addtopic - Добавить новые темы\n"
        "/removetopic - Удалить темы\n"
        "/finalize - Завершить голосование и показать результаты\n"
        "/setrooms - Установить количество залов\n"
        "/setslots - Установить количество слотов в залах\n"
        "/clearvotes - Очистить голоса\n"
        "/countvotes - Показать количество участников, проголосовавших за темы\n"
        "/topiclist - Показать список тем для голосования\n"
        "/cleartopics - Очистить все сохранённые темы\n"
        "/secret - Показать подробную статистику голосования\n"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=admin_message,
        message_thread_id=message_thread_id
    )


async def count_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    votes_data = context.bot_data.get("votes", {})

    num_voters = len(votes_data)

    if num_voters == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Никто ещё не проголосовал.",
            message_thread_id=message_thread_id
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Количество участников, проголосовавших за темы: {num_voters}",
            message_thread_id=message_thread_id
        )


async def topic_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    topics = context.bot_data.get("topics", [])
    if not topics:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Список тем пуст.",
            message_thread_id=message_thread_id
        )
        return
    topic_text = "\n".join([f"• {topic}" for topic in topics])
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Список тем для голосования:\n{topic_text}",
        message_thread_id=message_thread_id
    )


async def secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    votes_data = context.bot_data.get("votes", {})
    if not votes_data:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Нет данных о голосах.",
            message_thread_id=message_thread_id
        )
        return

    num_voters = len(votes_data)
    message = f"Количество участников, проголосовавших за темы: {num_voters}\n"
    message += "Список проголосовавших:\n"
    for user_id_str, user_votes in votes_data.items():
        user_id = int(user_id_str)
        try:
            user = await context.bot.get_chat(user_id)
            username = user.full_name
        except Exception:
            username = f"Пользователь {user_id}"
        votes_list = ', '.join(user_votes)
        message += f"<b>{username}</b>: {votes_list}\n"
    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode='HTML',
        message_thread_id=message_thread_id
    )


async def send_vote_message(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    selected_topics = context.bot_data.get("votes", {}).get(str(user_id), [])
    topics = context.bot_data.get("topics", [])
    if not topics:
        await context.bot.send_message(chat_id=user_id, text="Нет доступных тем для голосования.")
        return
    keyboard = [
        [InlineKeyboardButton(f"{'✅ ' if topic in selected_topics else ''}{topic}", callback_data=str(i))]
        for i, topic in enumerate(topics)
    ]
    keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_votes")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    vote_message = (
        f"Выберите темы, которые вам интересны (максимум {max_votes}):\n"
        "Когда закончите, нажмите кнопку \"Отправить\" для подтверждения вашего выбора."
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=vote_message, reply_markup=reply_markup)
    except BadRequest as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")


async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    topics = context.bot_data.get("topics", [])
    if not topics:
        await context.bot.send_message(chat_id=user_id, text="Нет доступных тем для голосования.")
        return
    context.user_data["vote_selection"] = context.bot_data.get("votes", {}).get(str(user_id), []).copy()
    await send_vote_message(user_id, context)


async def add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    context.user_data['adding_topics'] = True
    context.user_data['new_topics'] = []
    await context.bot.send_message(
        chat_id=user_id,
        text="Отправьте темы, разделяя их точкой с запятой (;), или по одному сообщению. "
             "Когда закончите, нажмите кнопку \"Отправить темы\".",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Отправить темы", callback_data="submit_topics")]]
        )
    )


async def receive_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if user_data.get('adding_topics', False):
        text = update.message.text.strip()
        if ';' in text:
            user_data['new_topics'].extend(topic.strip() for topic in text.split(';'))
        else:
            user_data['new_topics'].append(text.strip())


async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    topics = context.bot_data.get("topics", [])
    if not topics:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Нет тем для удаления.",
            message_thread_id=message_thread_id
        )
        return
    keyboard = [[InlineKeyboardButton(topic, callback_data=f"remove_{topic}")] for topic in topics]
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel_remove")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text='Выберите темы, которые хотите удалить:',
        reply_markup=reply_markup,
        message_thread_id=message_thread_id
    )


async def set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    context.user_data['awaiting_rooms'] = True
    await context.bot.send_message(
        chat_id=chat_id,
        text="Введите количество залов (например, отправьте '3'):",
        message_thread_id=message_thread_id
    )


async def set_rooms_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if not user_data.get('awaiting_rooms', False):
        return
    text = update.message.text.strip()
    try:
        num_rooms = int(text)
        context.bot_data['num_rooms'] = num_rooms
        chat_id = update.effective_chat.id
        message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Количество залов установлено на {num_rooms}.",
            message_thread_id=message_thread_id
        )
        logger.info(f"Количество залов установлено на {num_rooms}.")
        logger.info(f"Сохранённое количество залов: {context.bot_data.get('num_rooms')}")
    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Пожалуйста, введите корректное число.",
            message_thread_id=message_thread_id
        )
    finally:
        user_data['awaiting_rooms'] = False


async def set_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    context.user_data['awaiting_slots'] = True
    await context.bot.send_message(
        chat_id=chat_id,
        text="Введите количество слотов в каждом зале (например, отправьте '4'):",
        message_thread_id=message_thread_id
    )


async def set_slots_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    if not user_data.get('awaiting_slots', False):
        return
    text = update.message.text.strip()
    try:
        num_slots = int(text)
        context.bot_data['num_slots'] = num_slots
        chat_id = update.effective_chat.id
        message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Количество слотов в каждом зале установлено на {num_slots}.",
            message_thread_id=message_thread_id
        )
        logger.info(f"Количество слотов в каждом зале установлено на {num_slots}.")
        logger.info(f"Сохранённое количество слотов: {context.bot_data.get('num_slots')}")
    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Пожалуйста, введите корректное число.",
            message_thread_id=message_thread_id
        )
    finally:
        user_data['awaiting_slots'] = False


async def clear_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['votes'] = {}
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    await context.bot.send_message(
        chat_id=chat_id,
        text="Все голоса были очищены.",
        message_thread_id=message_thread_id
    )


async def clear_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['topics'] = []
    context.bot_data['votes'] = {}
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    await context.bot.send_message(
        chat_id=chat_id,
        text="Все темы были удалены, и голоса сброшены.",
        message_thread_id=message_thread_id
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    # Ответить на колбэк как можно раньше
    try:
        await query.answer()
    except BadRequest as e:
        logger.warning(f"Ошибка при ответе на CallbackQuery: {e}")

    user_id = query.from_user.id
    selected_data = query.data
    user_data = context.user_data

    if selected_data == "submit_topics":
        new_topics = user_data.get('new_topics', [])
        if new_topics:
            topics = context.bot_data.get("topics", [])
            context.bot_data["topics"] = list(set(topics + new_topics))
            await query.edit_message_text(text=f"Вы добавили темы: {', '.join(new_topics)}")
            user_data['adding_topics'] = False
            user_data['new_topics'] = []
        else:
            await query.edit_message_text(text="Вы не добавили ни одной темы.")
        return
    elif selected_data == "submit_votes":
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
            bot_username = (await context.bot.get_me()).username
            return_keyboard = [
                [InlineKeyboardButton("Переголосовать", callback_data="changevote")],
                [InlineKeyboardButton("Вернуться в чат", url=f"https://t.me/{bot_username}")]
            ]
            reply_markup = InlineKeyboardMarkup(return_keyboard)
            await query.edit_message_text(
                text=f"Спасибо за голосование! Вы проголосовали за следующие темы:\n{selected_topics_text}",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
        return
    elif selected_data.startswith("remove_"):
        topic_to_remove = selected_data[len("remove_"):]
        topics = context.bot_data.get("topics", [])
        if topic_to_remove in topics:
            topics.remove(topic_to_remove)
            context.bot_data["topics"] = topics
            await query.edit_message_text(text=f"Тема '{topic_to_remove}' была удалена.")
        else:
            await query.edit_message_text(text="Тема не найдена.")
        return
    elif selected_data == "cancel_remove":
        await query.edit_message_text(text="Удаление тем отменено.")
        return
    elif selected_data == "changevote":
        user_data["vote_selection"] = context.bot_data.get("votes", {}).get(str(user_id), []).copy()
        await send_vote_message(user_id, context)
        return

    topics = context.bot_data.get("topics", [])
    try:
        index = int(selected_data)
        selected_topic = topics[index]
    except (ValueError, IndexError):
        await query.answer("Неверный выбор.", show_alert=True)
        return

    if "vote_selection" not in user_data:
        user_data["vote_selection"] = context.bot_data.get("votes", {}).get(str(user_id), []).copy()

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
    keyboard.append([InlineKeyboardButton("Отправить", callback_data="submit_votes")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_reply_markup(reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка при обновлении клавиатуры: {e}")


async def finalize_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None

    num_rooms = context.bot_data.get('num_rooms', 3)  # По умолчанию 3 зала
    num_slots = context.bot_data.get('num_slots', 4)  # По умолчанию 4 слота

    all_votes = []
    votes_data = context.bot_data.get("votes", {})
    for votes in votes_data.values():
        all_votes.extend(votes)
    if not all_votes:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Нет голосов для обработки.",
            message_thread_id=message_thread_id
        )
        return
    vote_count = Counter(all_votes)
    sorted_vote_count = vote_count.most_common()
    vote_stats = "\n".join([f"• {topic} - {count} голос(ов)" for topic, count in sorted_vote_count])
    sorted_topics = [topic for topic, _ in sorted_vote_count]
    schedule = {f"Зал {i + 1}": [None] * num_slots for i in range(num_rooms)}
    topic_index = 0
    for topic in sorted_topics:
        room_number = topic_index % num_rooms
        slot_number = topic_index // num_rooms
        if slot_number >= num_slots:
            break
        room_name = f"Зал {room_number + 1}"
        schedule[room_name][slot_number] = topic
        topic_index += 1
    schedule_text = ""
    for room_num in range(1, num_rooms + 1):
        room_name = f"Зал {room_num}"
        topics_in_room = schedule[room_name]
        schedule_text += f"{room_name}\n"
        for i, topic in enumerate(topics_in_room):
            schedule_text += f"<b>Слот {i + 1}:</b> {topic if topic is not None else 'Пусто'}\n"
        schedule_text += "\n"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Статистика голосов:\n{vote_stats}\n\nРасписание:\n{schedule_text}",
        parse_mode='HTML',
        message_thread_id=message_thread_id
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Произошла ошибка:", exc_info=context.error)


def main() -> None:
    application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin))
    application.add_handler(CommandHandler('vote', vote))
    application.add_handler(CommandHandler('addtopic', add_topic))
    application.add_handler(CommandHandler('removetopic', remove_topic))
    application.add_handler(CommandHandler('finalize', finalize_votes))
    application.add_handler(CommandHandler('setrooms', set_rooms))
    application.add_handler(CommandHandler('setslots', set_slots))
    application.add_handler(CommandHandler('clearvotes', clear_votes))
    application.add_handler(CommandHandler('cleartopics', clear_topics))
    application.add_handler(CommandHandler('countvotes', count_votes))
    application.add_handler(CommandHandler('topiclist', topic_list))
    application.add_handler(CommandHandler('secret', secret))
    application.add_handler(CallbackQueryHandler(button))
    # Обработчики сообщений для функций установки залов/слотов должны быть добавлены ПЕРЕД receive_topic
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^\d+$') & ~filters.COMMAND, set_rooms_text
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^\d+$') & ~filters.COMMAND, set_slots_text
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, receive_topic
    ))
    application.add_error_handler(error_handler)
    logger.info("Запуск бота.")
    application.run_polling()


if __name__ == '__main__':
    main()
