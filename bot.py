import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore

# ============================================================
# НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

# Firebase
FIREBASE_JSON = os.environ.get("FIREBASE_JSON")
if not FIREBASE_JSON:
    for path in ["firebase-key.json", "/etc/secrets/firebase-key.json"]:
        if os.path.exists(path):
            with open(path, "r") as f:
                FIREBASE_JSON = f.read()
            break

print("=" * 50)
print("🚀 Запуск бота...")
print(f"BOT_TOKEN: {'✅' if BOT_TOKEN else '❌'}")
print(f"ADMIN_ID: {ADMIN_ID}")
print(f"FIREBASE_JSON: {'✅' if FIREBASE_JSON else '❌'}")
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

# Хранилище состояний: {chat_id: {"step": "...", "data": {...}}}
user_states = {}


# ============================================================
# HTTP-СЕРВЕР (для Render)
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write('🤖 Bot is running'.encode('utf-8'))

    def log_message(self, format, *args):
        pass


def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"✅ HTTP-сервер на порту {port}")
    server.serve_forever()


# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def user_keyboard():
    """Клавиатура для пользователя"""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("📤 Отправить фото"))
    kb.add(types.KeyboardButton("📸 Посмотреть архив"))
    return kb


def admin_keyboard():
    """Клавиатура для админа"""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(
        types.KeyboardButton("📸 Все фотографии"),
        types.KeyboardButton("🗑 Удалить пост"),
    )
    return kb


def cancel_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb


# ============================================================
# /start
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    user_states.pop(chat_id, None)

    if chat_id == ADMIN_ID:
        # Это админ
        bot.send_message(
            chat_id,
            "👋 *Привет, администратор!*\n\n"
            "Вы будете получать посты на модерацию.\n"
            "Также можете посмотреть все фото или удалить пост.",
            parse_mode='Markdown',
            reply_markup=admin_keyboard()
        )
    else:
        # Это обычный пользователь
        bot.send_message(
            chat_id,
            "👋 *Добро пожаловать в архив Советского Техникума-Интерната!*\n\n"
            "Здесь вы можете предложить своё фото в архив.\n"
            "После проверки модератором оно появится на сайте.",
            parse_mode='Markdown',
            reply_markup=user_keyboard()
        )


# ============================================================
# ПОЛЬЗОВАТЕЛЬ: 📤 Отправить фото
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📤 Отправить фото")
def user_send_photo_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = {"step": "waiting_title", "data": {"author": message.from_user.username or message.from_user.first_name or "Гость"}}
    bot.send_message(
        chat_id,
        "📌 *Шаг 1 из 4*\n\nВведите *заголовок* для вашего фото:",
        parse_mode='Markdown',
        reply_markup=cancel_keyboard()
    )


# ============================================================
# ПОЛЬЗОВАТЕЛЬ: 📸 Посмотреть архив
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📸 Посмотреть архив")
def user_view_archive(message):
    if not db:
        bot.send_message(message.chat.id, "❌ Firebase не подключён")
        return

    try:
        docs = list(db.collection('posts')
                    .where('status', '==', 'approved')
                    .order_by('createdAt', direction=firestore.Query.DESCENDING)
                    .stream())

        if not docs:
            bot.send_message(message.chat.id, "📭 В архиве пока нет фотографий", reply_markup=user_keyboard())
            return

        bot.send_message(message.chat.id, f"📸 *В архиве {len(docs)} фото*", parse_mode='Markdown')

        for doc in docs[:10]:  # показываем последние 10
            data = doc.to_dict()
            caption = f"*{data.get('title', '')}*\n👤 {data.get('author', 'Гость')}"
            img = data.get('imageUrl', '')
            if img:
                try:
                    bot.send_photo(message.chat.id, img, caption=caption, parse_mode='Markdown')
                except:
                    pass

        bot.send_message(message.chat.id, "🌐 Смотрите все фото на сайте!", reply_markup=user_keyboard())
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


# ============================================================
# АДМИН: 📸 Все фотографии
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📸 Все фотографии")
def admin_all_photos(message):
    if message.from_user.id != ADMIN_ID:
        return
    if not db:
        bot.send_message(message.chat.id, "❌ Firebase не подключён")
        return

    try:
        docs = list(db.collection('posts')
                    .order_by('createdAt', direction=firestore.Query.DESCENDING)
                    .stream())

        if not docs:
            bot.send_message(message.chat.id, "📭 Постов пока нет", reply_markup=admin_keyboard())
            return

        bot.send_message(message.chat.id, f"📸 *Найдено постов: {len(docs)}*", parse_mode='Markdown')

        for doc in docs:
            data = doc.to_dict()
            image_url = data.get('imageUrl', '') or data.get('imageBase64', '')
            status = data.get('status', 'pending')
            status_emoji = {'approved': '✅', 'pending': '⏳', 'rejected': '❌'}.get(status, '❓')

            caption = (
                f"{status_emoji} *{data.get('title', '')}*\n"
                f"📂 {data.get('category', '')}\n"
                f"👤 @{data.get('author', 'Гость')}\n\n"
                f"📝 {data.get('text', '')[:200]}\n\n"
                f"🆔 `{doc.id}`"
            )

            try:
                if image_url and (image_url.startswith('http') or image_url.startswith('data:image')):
                    bot.send_photo(message.chat.id, image_url, caption=caption, parse_mode='Markdown')
                else:
                    bot.send_message(message.chat.id, caption, parse_mode='Markdown')
            except:
                bot.send_message(message.chat.id, caption, parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


# ============================================================
# АДМИН: 🗑 Удалить пост
# ============================================================
@bot.message_handler(func=lambda m: m.text == "🗑 Удалить пост")
def admin_delete_start(message):
    if message.from_user.id != ADMIN_ID:
        return
    user_states[message.chat.id] = {"step": "waiting_delete_id", "data": {}}
    bot.send_message(
        message.chat.id,
        "🗑 Введите *ID поста* (из «Все фотографии»):",
        parse_mode='Markdown',
        reply_markup=cancel_keyboard()
    )


# ============================================================
# ОБРАБОТКА ТЕКСТА
# ============================================================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id)

    if text == "❌ Отмена":
        user_states.pop(chat_id, None)
        kb = admin_keyboard() if chat_id == ADMIN_ID else user_keyboard()
        bot.send_message(chat_id, "Отменено.", reply_markup=kb)
        return

    # === Пользователь заполняет пост ===
    if state and state["step"] == "waiting_title":
        state["data"]["title"] = text
        state["step"] = "waiting_category"
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(
            types.KeyboardButton("😂 Смешные фото"),
            types.KeyboardButton("🌳 Прогулка"),
            types.KeyboardButton("🍲 Еда")
        )
        kb.add(types.KeyboardButton("❌ Отмена"))
        bot.send_message(chat_id, "📌 *Шаг 2 из 4*\n\nВыберите *категорию*:", parse_mode='Markdown', reply_markup=kb)
        return

    if state and state["step"] == "waiting_category":
        category = text.replace("😂 ", "").replace("🌳 ", "").replace("🍲 ", "").strip()
        if category not in ["Смешные фото", "Прогулка", "Еда"]:
            bot.send_message(chat_id, "❌ Выберите категорию из списка")
            return
        state["data"]["category"] = category
        state["step"] = "waiting_text"
        bot.send_message(chat_id, "📌 *Шаг 3 из 4*\n\nВведите *текст* (описание):", parse_mode='Markdown', reply_markup=cancel_keyboard())
        return

    if state and state["step"] == "waiting_text":
        state["data"]["text"] = text
        state["step"] = "waiting_photo"
        bot.send_message(chat_id, "📌 *Шаг 4 из 4*\n\nОтправьте *фотографию*:", parse_mode='Markdown', reply_markup=cancel_keyboard())
        return

    if state and state["step"] == "waiting_photo":
        bot.send_message(chat_id, "📷 Отправьте фото или нажмите «Отмена»")
        return

    # === Админ удаляет ===
    if state and state["step"] == "waiting_delete_id":
        try:
            doc_ref = db.collection('posts').document(text)
            doc = doc_ref.get()
            if not doc.exists:
                bot.send_message(chat_id, f"❌ Пост `{text}` не найден", parse_mode='Markdown')
                return
            doc_ref.delete()
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ Пост удалён", reply_markup=admin_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")
        return

    # Если ничего не подошло
    kb = admin_keyboard() if chat_id == ADMIN_ID else user_keyboard()
    bot.send_message(chat_id, "Выберите действие:", reply_markup=kb)


# ============================================================
# ПОЛЬЗОВАТЕЛЬ ОТПРАВИЛ ФОТО → НА МОДЕРАЦИЮ
# ============================================================
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    # Админ не в процессе — игнорируем
    if chat_id == ADMIN_ID and (not state or state["step"] != "waiting_photo"):
        bot.send_message(chat_id, "Выберите действие:", reply_markup=admin_keyboard())
        return

    # Пользователь не в процессе
    if not state or state["step"] != "waiting_photo":
        bot.send_message(chat_id, "Сначала нажмите «📤 Отправить фото»", reply_markup=user_keyboard())
        return

    file_id = message.photo[-1].file_id

    try:
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        # Создаём пост со статусом pending
        post = {
            "title": state["data"].get("title", ""),
            "category": state["data"].get("category", ""),
            "text": state["data"].get("text", ""),
            "imageUrl": file_url,
            "author": state["data"].get("author", "Гость"),
            "user_id": chat_id,
            "status": "pending",
            "createdAt": firestore.SERVER_TIMESTAMP
        }

        doc_ref = db.collection('posts').add(post)
        post_id = doc_ref[1].id

        # Пользователю — подтверждение
        bot.send_message(
            chat_id,
            "✅ *Ваш пост отправлен на модерацию!*\n\n"
            "Как только модератор его одобрит, он появится на сайте.",
            parse_mode='Markdown',
            reply_markup=user_keyboard()
        )

        user_states.pop(chat_id, None)

        # Админу — уведомление с кнопками
        send_to_admin_for_moderation(post_id, post, file_id)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка: {e}")


# ============================================================
# ОТПРАВКА АДМИНУ НА МОДЕРАЦИЮ
# ============================================================
def send_to_admin_for_moderation(post_id, post, file_id):
    emoji = {'Смешные фото': '😂', 'Прогулка': '🌳', 'Еда': '🍲'}.get(post['category'], '📷')

    caption = (
        f"🆕 *Новый пост на модерации*\n\n"
        f"{emoji} *Категория:* {post['category']}\n"
        f"📌 *Заголовок:* {post['title']}\n"
        f"👤 *Автор:* @{post['author']}\n\n"
        f"📝 *Текст:*\n{post['text']}\n\n"
        f"🆔 `{post_id}`"
    )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{post_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{post_id}")
    )

    try:
        bot.send_photo(ADMIN_ID, file_id, caption=caption, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        bot.send_message(ADMIN_ID, caption, parse_mode='Markdown', reply_markup=keyboard)


# ============================================================
# ОБРАБОТКА КНОПОК "ОДОБРИТЬ" / "ОТКЛОНИТЬ"
# ============================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Нет доступа")
        return

    data = call.data

    # ===== ОДОБРИТЬ =====
    if data.startswith("approve_"):
        post_id = data.replace("approve_", "")
        try:
            doc_ref = db.collection('posts').document(post_id)
            doc = doc_ref.get()
            if not doc.exists:
                bot.answer_callback_query(call.id, "❌ Пост не найден")
                return

            doc_ref.update({"status": "approved"})
            post = doc.to_dict()

            # Обновляем сообщение — убираем кнопки
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )

            bot.answer_callback_query(call.id, "✅ Пост одобрен!")
            bot.send_message(
                ADMIN_ID,
                f"✅ *Опубликовано!*\n\n"
                f"📌 {post.get('title', '')}\n"
                f"👤 @{post.get('author', 'Гость')}\n"
                f"Пост теперь виден на сайте.",
                parse_mode='Markdown'
            )

            # Уведомляем автора
            user_id = post.get('user_id')
            if user_id:
                try:
                    bot.send_message(
                        user_id,
                        f"🎉 *Ваш пост одобрен!*\n\n"
                        f"📌 «{post.get('title', '')}» теперь опубликован на сайте.",
                        parse_mode='Markdown'
                    )
                except:
                    pass

        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка: {e}")

    # ===== ОТКЛОНИТЬ =====
    elif data.startswith("reject_"):
        post_id = data.replace("reject_", "")
        try:
            doc_ref = db.collection('posts').document(post_id)
            doc = doc_ref.get()
            if not doc.exists:
                bot.answer_callback_query(call.id, "❌ Пост не найден")
                return

            post = doc.to_dict()
            doc_ref.delete()  # удаляем полностью

            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )

            bot.answer_callback_query(call.id, "❌ Пост отклонён")
            bot.send_message(
                ADMIN_ID,
                f"❌ *Пост отклонён и удалён*\n\n"
                f"📌 {post.get('title', '')}\n"
                f"👤 @{post.get('author', 'Гость')}",
                parse_mode='Markdown'
            )

            # Уведомляем автора
            user_id = post.get('user_id')
            if user_id:
                try:
                    bot.send_message(
                        user_id,
                        f"😔 *Ваш пост отклонён модератором.*\n\n"
                        f"📌 «{post.get('title', '')}»\n\n"
                        f"Возможно, фото не подходит по тематике или качеству.",
                        parse_mode='Markdown'
                    )
                except:
                    pass

        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка: {e}")


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == '__main__':
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    print("🤖 Бот запущен и слушает Telegram...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
