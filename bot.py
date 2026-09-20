import os
import json
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# ============================================================
# НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
FIREBASE_JSON = os.environ.get("FIREBASE_JSON")

print("=" * 50)
print("🚀 Запуск бота...")
print(f"BOT_TOKEN: {'✅' if BOT_TOKEN else '❌ НЕТ'}")
print(f"ADMIN_ID: {ADMIN_ID}")
print(f"FIREBASE_JSON: {'✅' if FIREBASE_JSON else '❌ НЕТ'}")
print("=" * 50)

# ============================================================
# FIREBASE
# ============================================================
db = None
if FIREBASE_JSON:
    try:
        cred = credentials.Certificate(json.loads(FIREBASE_JSON))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Firebase подключён")
    except Exception as e:
        print(f"❌ Firebase: {e}")

if not BOT_TOKEN:
    print("❌ BOT_TOKEN отсутствует")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# ============================================================
# ХРАНИЛИЩЕ СОСТОЯНИЙ (что сейчас делает пользователь)
# ============================================================
user_states = {}  # {chat_id: {"step": "...", "data": {...}}}

# ============================================================
# КЛАВИАТУРА — 3 КНОПКИ
# ============================================================
def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(
        types.KeyboardButton("📸 Все фотографии"),
        types.KeyboardButton("➕ Добавить пост"),
        types.KeyboardButton("🗑 Удалить пост"),
    )
    return kb


# ============================================================
# /start
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⛔ Нет доступа.")
        return

    user_states.pop(message.chat.id, None)

    bot.send_message(
        message.chat.id,
        "👋 *Привет, администратор!*\n\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=main_keyboard()
    )


# ============================================================
# КНОПКА: 📸 Все фотографии
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📸 Все фотографии")
def show_all_photos(message):
    if message.from_user.id != ADMIN_ID:
        return

    if not db:
        bot.send_message(message.chat.id, "❌ Firebase не подключён")
        return

    try:
        docs = list(db.collection('posts').order_by('createdAt', direction=firestore.Query.DESCENDING).stream())

        if not docs:
            bot.send_message(message.chat.id, "📭 Постов пока нет", reply_markup=main_keyboard())
            return

        bot.send_message(message.chat.id, f"📸 *Найдено постов: {len(docs)}*", parse_mode='Markdown')

        for i, doc in enumerate(docs, 1):
            data = doc.to_dict()
            title = data.get('title', 'Без названия')
            category = data.get('category', '')
            text = data.get('text', '')
            image_url = data.get('imageUrl', '')
            status = data.get('status', 'pending')

            status_emoji = {
                'approved': '✅',
                'pending': '⏳',
                'rejected': '❌'
            }.get(status, '❓')

            caption = (
                f"{status_emoji} *{title}*\n"
                f"📂 {category}\n\n"
                f"{text[:200]}{'...' if len(text) > 200 else ''}\n\n"
                f"🆔 `{doc.id}`"
            )

            try:
                if image_url and image_url.startswith('http'):
                    bot.send_photo(message.chat.id, image_url, caption=caption, parse_mode='Markdown')
                else:
                    bot.send_message(message.chat.id, caption, parse_mode='Markdown')
            except Exception as e:
                bot.send_message(message.chat.id, caption + f"\n\n⚠️ Фото не загрузилось: {e}", parse_mode='Markdown')

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


# ============================================================
# КНОПКА: ➕ Добавить пост
# ============================================================
@bot.message_handler(func=lambda m: m.text == "➕ Добавить пост")
def add_post_start(message):
    if message.from_user.id != ADMIN_ID:
        return

    user_states[message.chat.id] = {"step": "waiting_title", "data": {}}

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))

    bot.send_message(
        message.chat.id,
        "📌 *Шаг 1 из 4*\n\nВведите *заголовок* поста:",
        parse_mode='Markdown',
        reply_markup=kb
    )


# ============================================================
# КНОПКА: 🗑 Удалить пост
# ============================================================
@bot.message_handler(func=lambda m: m.text == "🗑 Удалить пост")
def delete_post_start(message):
    if message.from_user.id != ADMIN_ID:
        return

    if not db:
        bot.send_message(message.chat.id, "❌ Firebase не подключён")
        return

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))

    bot.send_message(
        message.chat.id,
        "🗑 *Удаление поста*\n\nВведите *ID поста* (можно посмотреть в «Все фотографии»):",
        parse_mode='Markdown',
        reply_markup=kb
    )

    user_states[message.chat.id] = {"step": "waiting_delete_id", "data": {}}


# ============================================================
# ОБРАБОТКА ВСЕХ ТЕКСТОВЫХ СООБЩЕНИЙ (пошаговые сценарии)
# ============================================================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    if message.from_user.id != ADMIN_ID:
        return

    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id)

    # Отмена
    if text == "❌ Отмена":
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "Отменено.", reply_markup=main_keyboard())
        return

    # ---- Сценарий: добавление поста ----
    if state and state["step"] == "waiting_title":
        state["data"]["title"] = text
        state["step"] = "waiting_category"

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(
            types.KeyboardButton("😂 Смешные фото"),
            types.KeyboardButton("🌳 Прогулка"),
            types.KeyboardButton("🍲 Еда"),
        )
        kb.add(types.KeyboardButton("❌ Отмена"))

        bot.send_message(
            chat_id,
            "📌 *Шаг 2 из 4*\n\nВыберите *категорию*:",
            parse_mode='Markdown',
            reply_markup=kb
        )
        return

    if state and state["step"] == "waiting_category":
        # Убираем эмодзи из выбора
        category = text.replace("😂 ", "").replace("🌳 ", "").replace("🍲 ", "").strip()
        if category not in ["Смешные фото", "Прогулка", "Еда"]:
            bot.send_message(chat_id, "❌ Выберите категорию из списка")
            return

        state["data"]["category"] = category
        state["step"] = "waiting_text"

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(types.KeyboardButton("❌ Отмена"))

        bot.send_message(
            chat_id,
            "📌 *Шаг 3 из 4*\n\nВведите *текст* поста:",
            parse_mode='Markdown',
            reply_markup=kb
        )
        return

    if state and state["step"] == "waiting_text":
        state["data"]["text"] = text
        state["step"] = "waiting_photo"

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(types.KeyboardButton("Пропустить фото"))
        kb.add(types.KeyboardButton("❌ Отмена"))

        bot.send_message(
            chat_id,
            "📌 *Шаг 4 из 4*\n\nОтправьте *фотографию* (или нажмите «Пропустить фото»):",
            parse_mode='Markdown',
            reply_markup=kb
        )
        return

    if state and state["step"] == "waiting_photo":
        if text == "Пропустить фото":
            save_post(chat_id, state["data"], image_url="")
            user_states.pop(chat_id, None)
            return
        else:
            bot.send_message(chat_id, "📷 Пожалуйста, отправьте фото или нажмите «Пропустить фото»")
            return

    # ---- Сценарий: удаление ----
    if state and state["step"] == "waiting_delete_id":
        post_id = text
        try:
            doc_ref = db.collection('posts').document(post_id)
            doc = doc_ref.get()
            if not doc.exists:
                bot.send_message(chat_id, f"❌ Пост `{post_id}` не найден", parse_mode='Markdown')
                return

            data = doc.to_dict()
            doc_ref.delete()

            user_states.pop(chat_id, None)
            bot.send_message(
                chat_id,
                f"✅ Пост *«{data.get('title', 'Без названия')}»* удалён",
                parse_mode='Markdown',
                reply_markup=main_keyboard()
            )
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")
        return

    # Если ничего не подошло — показываем меню
    bot.send_message(chat_id, "Выберите действие:", reply_markup=main_keyboard())


# ============================================================
# ОБРАБОТКА ФОТО
# ============================================================
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.from_user.id != ADMIN_ID:
        return

    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if not state or state["step"] != "waiting_photo":
        bot.send_message(chat_id, "Выберите действие:", reply_markup=main_keyboard())
        return

    # Получаем file_id самого большого фото
    file_id = message.photo[-1].file_id

    try:
        # Получаем ссылку на файл
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        save_post(chat_id, state["data"], image_url=file_url)
        user_states.pop(chat_id, None)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка загрузки фото: {e}")


# ============================================================
# СОХРАНЕНИЕ ПОСТА В FIREBASE
# ============================================================
def save_post(chat_id, data, image_url=""):
    if not db:
        bot.send_message(chat_id, "❌ Firebase не подключён")
        return

    try:
        post = {
            "title": data.get("title", ""),
            "category": data.get("category", ""),
            "text": data.get("text", ""),
            "imageUrl": image_url,
            "status": "approved",  # публикуем сразу — админ сам добавляет
            "author": "Администратор",
            "createdAt": firestore.SERVER_TIMESTAMP
        }

        doc_ref = db.collection('posts').add(post)
        post_id = doc_ref[1].id

        bot.send_message(
            chat_id,
            f"✅ *Пост добавлен!*\n\n"
            f"📌 {post['title']}\n"
            f"📂 {post['category']}\n"
            f"🆔 `{post_id}`\n\n"
            f"Пост сразу опубликован на сайте.",
            parse_mode='Markdown',
            reply_markup=main_keyboard()
        )
        print(f"✅ Пост {post_id} добавлен")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка сохранения: {e}")


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == '__main__':
    print("🤖 Бот запущен...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
