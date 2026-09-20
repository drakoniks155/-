import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
SITE_URL = "https://drakoniks155.github.io/-/"

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
user_states = {}


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


def user_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("📤 Отправить фото"))
    kb.add(types.KeyboardButton("🌐 Открыть сайт"))
    return kb


def admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("📸 Все фотографии"), types.KeyboardButton("🗑 Удалить пост"))
    kb.add(types.KeyboardButton("🌐 Открыть сайт"))
    return kb


def cancel_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb


def category_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("😂 Смешные фото"), types.KeyboardButton("🌳 Прогулка"), types.KeyboardButton("🍲 Еда"))
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb


@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    user_states.pop(chat_id, None)

    # Проверяем, пришёл ли пользователь по ссылке с сайта (?start=submit)
    args = message.text.split()
    from_site = len(args) > 1 and args[1] == "submit"

    if chat_id == ADMIN_ID:
        bot.send_message(
            chat_id,
            "👋 *Привет, администратор!*\n\nВсе новые фото будут приходить сюда на модерацию.",
            parse_mode='Markdown',
            reply_markup=admin_keyboard()
        )
        return

    if from_site:
        # Пользователь пришёл с сайта — сразу начинаем приём фото
        username = message.from_user.username
        first_name = message.from_user.first_name or "Гость"
        author = f"@{username}" if username else first_name
        user_states[chat_id] = {
            "step": "waiting_title",
            "data": {"author": author, "user_id": chat_id}
        }
        bot.send_message(
            chat_id,
            "👋 *Добро пожаловать!*\n\n"
            "Вы пришли с сайта архива. Давайте добавим ваше фото!\n\n"
            "📌 *Шаг 1 из 3*\n\nВведите *заголовок* для фото:",
            parse_mode='Markdown',
            reply_markup=cancel_keyboard()
        )
        return

    bot.send_message(
        chat_id,
        "👋 *Добро пожаловать в архив Советского Техникума-Интерната!*\n\n"
        "Здесь вы можете отправить своё фото в архив.\n"
        "После проверки модератором оно появится на сайте.",
        parse_mode='Markdown',
        reply_markup=user_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == "🌐 Открыть сайт")
def open_site(message):
    bot.send_message(message.chat.id, f"🌐 Наш архив:\n\n{SITE_URL}", disable_web_page_preview=False)


@bot.message_handler(func=lambda m: m.text == "📤 Отправить фото")
def user_send_photo_start(message):
    chat_id = message.chat.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "Гость"
    author = f"@{username}" if username else first_name
    user_states[chat_id] = {"step": "waiting_title", "data": {"author": author, "user_id": chat_id}}
    bot.send_message(chat_id, "📌 *Шаг 1 из 3*\n\nВведите *заголовок* для фото:", parse_mode='Markdown', reply_markup=cancel_keyboard())


@bot.message_handler(func=lambda m: m.text == "📸 Все фотографии")
def admin_all_photos(message):
    if message.from_user.id != ADMIN_ID:
        return
    if not db:
        bot.send_message(message.chat.id, "❌ Firebase не подключён")
        return
    try:
        docs = list(db.collection('posts').order_by('createdAt', direction=firestore.Query.DESCENDING).stream())
        if not docs:
            bot.send_message(message.chat.id, "📭 Постов пока нет", reply_markup=admin_keyboard())
            return
        bot.send_message(message.chat.id, f"📸 *Найдено постов: {len(docs)}*", parse_mode='Markdown')
        for doc in docs:
            data = doc.to_dict()
            image_url = data.get('imageUrl', '') or data.get('imageBase64', '')
            status = data.get('status', 'pending')
            status_emoji = {'approved': '✅', 'pending': '⏳', 'rejected': '❌'}.get(status, '❓')
            caption = f"{status_emoji} *{data.get('title', '')}*\n📂 {data.get('category', '')}\n👤 {data.get('author', 'Гость')}\n\n🆔 `{doc.id}`"
            try:
                if image_url:
                    bot.send_photo(message.chat.id, image_url, caption=caption, parse_mode='Markdown')
                else:
                    bot.send_message(message.chat.id, caption, parse_mode='Markdown')
            except:
                bot.send_message(message.chat.id, caption, parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


@bot.message_handler(func=lambda m: m.text == "🗑 Удалить пост")
def admin_delete_start(message):
    if message.from_user.id != ADMIN_ID:
        return
    user_states[message.chat.id] = {"step": "waiting_delete_id", "data": {}}
    bot.send_message(message.chat.id, "🗑 Введите *ID поста* (из «Все фотографии»):", parse_mode='Markdown', reply_markup=cancel_keyboard())


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

    if state and state["step"] == "waiting_title":
        state["data"]["title"] = text
        state["step"] = "waiting_category"
        bot.send_message(chat_id, "📌 *Шаг 2 из 3*\n\nВыберите *категорию*:", parse_mode='Markdown', reply_markup=category_keyboard())
        return

    if state and state["step"] == "waiting_category":
        category = text.replace("😂 ", "").replace("🌳 ", "").replace("🍲 ", "").strip()
        if category not in ["Смешные фото", "Прогулка", "Еда"]:
            bot.send_message(chat_id, "❌ Выберите категорию из списка")
            return
        state["data"]["category"] = category
        state["step"] = "waiting_photo"
        bot.send_message(chat_id, "📌 *Шаг 3 из 3*\n\nОтправьте *фотографию* 📷", parse_mode='Markdown', reply_markup=cancel_keyboard())
        return

    if state and state["step"] == "waiting_photo":
        bot.send_message(chat_id, "📷 Отправьте фото или нажмите «Отмена»")
        return

    if state and state["step"] == "waiting_delete_id":
        try:
            doc_ref = db.collection('posts').document(text)
            doc = doc_ref.get()
            if not doc.exists:
                bot.send_message(chat_id, f"❌ Пост `{text}` не найден", parse_mode='Markdown')
                return
            doc_ref.delete()
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "✅ Пост удалён", reply_markup=admin_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")
        return

    kb = admin_keyboard() if chat_id == ADMIN_ID else user_keyboard()
    bot.send_message(chat_id, "Выберите действие:", reply_markup=kb)


@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if not state or state["step"] != "waiting_photo":
        kb = admin_keyboard() if chat_id == ADMIN_ID else user_keyboard()
        bot.send_message(chat_id, "Сначала нажмите «📤 Отправить фото»", reply_markup=kb)
        return

    file_id = message.photo[-1].file_id

    try:
        post = {
            "title": state["data"].get("title", ""),
            "category": state["data"].get("category", ""),
            "text": state["data"].get("text", ""),
            "author": state["data"].get("author", "Гость"),
            "user_id": state["data"].get("user_id", chat_id),
            "imageFileId": file_id,
            "imageUrl": "",
            "status": "pending",
            "createdAt": firestore.SERVER_TIMESTAMP
        }

        doc_ref = db.collection('posts').add(post)
        post_id = doc_ref[1].id

        bot.send_message(
            chat_id,
            "✅ *Ваше фото отправлено на модерацию!*\n\nКак только модератор проверит его — оно появится на сайте.",
            parse_mode='Markdown',
            reply_markup=user_keyboard()
        )

        user_states.pop(chat_id, None)
        send_to_admin_with_buttons(post_id, post, file_id)

    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        bot.send_message(chat_id, f"❌ Ошибка: {e}")


def send_to_admin_with_buttons(post_id, post, file_id):
    emoji = {'Смешные фото': '😂', 'Прогулка': '🌳', 'Еда': '🍲'}.get(post['category'], '📷')

    caption = (
        f"🆕 *НОВЫЙ ПОСТ НА МОДЕРАЦИИ*\n\n"
        f"{emoji} *Категория:* {post['category']}\n"
        f"📌 *Заголовок:* {post['title']}\n"
        f"👤 *Автор:* {post['author']}\n\n"
        f"🆔 `{post_id}`\n\n"
        f"👇 Выберите действие:"
    )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{post_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{post_id}")
    )

    try:
        bot.send_photo(ADMIN_ID, file_id, caption=caption, parse_mode='Markdown', reply_markup=keyboard)
        print(f"✅ Пост {post_id} отправлен админу")
    except Exception as e:
        print(f"❌ Ошибка отправки админу: {e}")
        bot.send_message(ADMIN_ID, caption, parse_mode='Markdown', reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Нет доступа")
        return

    data = call.data

    if data.startswith("approve_"):
        post_id = data.replace("approve_", "")
        try:
            doc_ref = db.collection('posts').document(post_id)
            doc = doc_ref.get()
            if not doc.exists:
                bot.answer_callback_query(call.id, "❌ Пост не найден")
                return

            post = doc.to_dict()
            file_id = post.get("imageFileId")
            image_url = ""
            if file_id:
                try:
                    file_info = bot.get_file(file_id)
                    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
                except Exception as e:
                    print(f"Ошибка URL фото: {e}")

            doc_ref.update({"status": "approved", "imageUrl": image_url})

            bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            bot.answer_callback_query(call.id, "✅ Пост одобрен!")

            bot.send_message(
                ADMIN_ID,
                f"✅ *Пост опубликован на сайте!*\n\n📌 {post.get('title', '')}\n👤 {post.get('author', 'Гость')}\n\n🔗 {SITE_URL}",
                parse_mode='Markdown',
                disable_web_page_preview=True
            )

            user_id = post.get('user_id')
            if user_id:
                try:
                    bot.send_message(
                        user_id,
                        f"🎉 *Ваш пост одобрен и опубликован!*\n\n📌 «{post.get('title', '')}»\n\n🔗 Посмотреть: {SITE_URL}",
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                except:
                    pass
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            bot.answer_callback_query(call.id, f"Ошибка: {e}")

    elif data.startswith("reject_"):
        post_id = data.replace("reject_", "")
        try:
            doc_ref = db.collection('posts').document(post_id)
            doc = doc_ref.get()
            if not doc.exists:
                bot.answer_callback_query(call.id, "❌ Пост не найден")
                return

            post = doc.to_dict()
            doc_ref.delete()

            bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            bot.answer_callback_query(call.id, "❌ Пост отклонён")

            bot.send_message(
                ADMIN_ID,
                f"❌ *Пост отклонён и удалён*\n\n📌 {post.get('title', '')}\n👤 {post.get('author', 'Гость')}",
                parse_mode='Markdown'
            )

            user_id = post.get('user_id')
            if user_id:
                try:
                    bot.send_message(user_id, f"😔 *Ваш пост отклонён модератором.*\n\n📌 «{post.get('title', '')}»\n\nПопробуйте отправить другое фото 💜", parse_mode='Markdown')
                except:
                    pass
        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка: {e}")


if __name__ == '__main__':
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    print("🤖 Бот запущен и слушает Telegram...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
