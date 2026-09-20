import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore

# ============================================================
# НАСТРОЙКИ (читаются из переменных окружения Render)
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

# Firebase ключ: сначала из переменной, потом из файла
FIREBASE_JSON = os.environ.get("FIREBASE_JSON")
if not FIREBASE_JSON:
    for path in ["firebase-key.json", "/etc/secrets/firebase-key.json"]:
        if os.path.exists(path):
            with open(path, "r") as f:
                FIREBASE_JSON = f.read()
            print(f"✅ Firebase ключ загружен из файла: {path}")
            break

print("=" * 50)
print("🚀 Запуск бота...")
print(f"BOT_TOKEN: {'✅ есть' if BOT_TOKEN else '❌ НЕТ'}")
print(f"ADMIN_ID: {ADMIN_ID}")
print(f"FIREBASE_JSON: {'✅ есть' if FIREBASE_JSON else '❌ НЕТ'}")
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
    print("❌ BOT_TOKEN отсутствует — бот не запустится")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
user_states = {}


# ============================================================
# HTTP-СЕРВЕР (нужен для Render Web Service)
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
    print(f"✅ HTTP-сервер запущен на порту {port}")
    server.serve_forever()


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
# 📸 ВСЕ ФОТОГРАФИИ (с фото, автором и категорией)
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📸 Все фотографии")
def show_all_photos(message):
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
            bot.send_message(message.chat.id, "📭 Постов пока нет", reply_markup=main_keyboard())
            return

        bot.send_message(message.chat.id, f"📸 *Найдено постов: {len(docs)}*", parse_mode='Markdown')

        for doc in docs:
            data = doc.to_dict()

            title = data.get('title', 'Без названия')
            category = data.get('category', 'Не указана')
            text = data.get('text', '')
            image_url = data.get('imageUrl', '') or data.get('imageBase64', '')
            author = data.get('author', 'Неизвестный автор')
            status = data.get('status', 'pending')

            status_emoji = {
                'approved': '✅',
                'pending': '⏳',
                'rejected': '❌'
            }.get(status, '❓')

            caption = (
                f"{status_emoji} *{title}*\n"
                f"📂 Категория: {category}\n"
                f"👤 Автор: {author}\n\n"
                f"📝 {text[:300]}{'...' if len(text) > 300 else ''}\n\n"
                f"🆔 `{doc.id}`"
            )

            try:
                if image_url and (image_url.startswith('http') or image_url.startswith('data:image')):
                    bot.send_photo(
                        message.chat.id,
                        image_url,
                        caption=caption,
                        parse_mode='Markdown'
                    )
                else:
                    bot.send_message(message.chat.id, caption, parse_mode='Markdown')
            except Exception as e:
                bot.send_message(
                    message.chat.id,
                    caption + f"\n\n⚠️ Фото не загрузилось: {e}",
                    parse_mode='Markdown'
                )

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


# ============================================================
# ➕ ДОБАВИТЬ ПОСТ
# ============================================================
@bot.message_handler(func=lambda m: m.text == "➕ Добавить пост")
def add_post_start(message):
    if message.from_user.id != ADMIN_ID:
        return
    author = f"@{message.from_user.username}" if message.from_user.username else "Администратор"
    user_states[message.chat.id] = {"step": "waiting_title", "data": {"author": author}}
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))
    bot.send_message(
        message.chat.id,
        "📌 *Шаг 1 из 4*\n\nВведите *заголовок* поста:",
        parse_mode='Markdown',
        reply_markup=kb
    )


# ============================================================
# 🗑 УДАЛИТЬ ПОСТ
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
        "🗑 *Удаление поста*\n\nВведите *ID поста* (виден в «Все фотографии»):",
        parse_mode='Markdown',
        reply_markup=kb
    )
    user_states[message.chat.id] = {"step": "waiting_delete_id", "data": {}}


# ============================================================
# ОБРАБОТКА ТЕКСТА
# ============================================================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    if message.from_user.id != ADMIN_ID:
        return

    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states.get(chat_id)

    if text == "❌ Отмена":
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "Отменено.", reply_markup=main_keyboard())
        return

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
        bot.send_message(
            chat_id,
            "📌 *Шаг 2 из 4*\n\nВыберите *категорию*:",
            parse_mode='Markdown',
            reply_markup=kb
        )
        return

    if state and state["step"] == "waiting_category":
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
            "📌 *Шаг 4 из 4*\n\nОтправьте *фотографию* (или «Пропустить фото»):",
            parse_mode='Markdown',
            reply_markup=kb
        )
        return

    if state and state["step"] == "waiting_photo":
        if text == "Пропустить фото":
            save_post(chat_id, state["data"], image_url="")
            user_states.pop(chat_id, None)
        else:
            bot.send_message(chat_id, "📷 Отправьте фото или нажмите «Пропустить фото»")
        return

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

    bot.send_message(chat_id, "Выберите действие:", reply_markup=main_keyboard())


# ============================================================
# ОБРАБОТКА ФОТО ОТ АДМИНА
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

    file_id = message.photo[-1].file_id
    try:
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
            "author": data.get("author", "Администратор"),
            "status": "approved",
            "createdAt": firestore.SERVER_TIMESTAMP
        }
        doc_ref = db.collection('posts').add(post)
        post_id = doc_ref[1].id
        bot.send_message(
            chat_id,
            f"✅ *Пост добавлен!*\n\n"
            f"📌 {post['title']}\n"
            f"📂 {post['category']}\n"
            f"👤 {post['author']}\n"
            f"🆔 `{post_id}`",
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
    # Запускаем HTTP-сервер (нужен для Render)
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    print("🤖 Бот запущен и слушает Telegram...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
