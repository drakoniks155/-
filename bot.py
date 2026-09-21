import os
import json
import threading
import base64
import io
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore
from PIL import Image

# ============================================================
# НАСТРОЙКИ
# ============================================================
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
user_states = {}

MAX_PHOTO_SIZE_KB = 800  # сжимаем до 800 KB (лимит Firestore — 1 MB на документ)


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
# СКАЧИВАНИЕ И СЖАТИЕ ФОТО → BASE64
# ============================================================
def download_and_compress_photo(file_id, max_size_kb=MAX_PHOTO_SIZE_KB):
    """Скачивает фото из Telegram, сжимает и возвращает data URL (base64)."""
    try:
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        response = requests.get(file_url, timeout=30)
        if response.status_code != 200:
            print(f"❌ Не удалось скачать фото: {response.status_code}")
            return None

        img = Image.open(io.BytesIO(response.content))

        # Конвертируем в RGB
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                rgb_img.paste(img, mask=img.split()[-1])
            else:
                rgb_img.paste(img)
            img = rgb_img
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Уменьшаем если слишком большое
        max_dimension = 1600
        if max(img.size) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        # Подбираем качество
        final_buffer = None
        for q in [85, 75, 65, 55, 45, 35, 25]:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=q, optimize=True)
            size_kb = len(buffer.getvalue()) / 1024

            if size_kb <= max_size_kb:
                final_buffer = buffer.getvalue()
                print(f"✅ Фото сжато до {size_kb:.1f} KB (качество {q})")
                break

        if final_buffer is None:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=25, optimize=True)
            final_buffer = buffer.getvalue()
            print(f"⚠️ Фото сжато до {len(final_buffer)/1024:.1f} KB (минимум)")

        img_base64 = base64.b64encode(final_buffer).decode('utf-8')
        data_url = f"data:image/jpeg;base64,{img_base64}"

        return data_url

    except Exception as e:
        print(f"❌ Ошибка обработки фото: {e}")
        return None


# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def user_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("📤 Отправить фото"))
    kb.add(types.KeyboardButton("🌐 Открыть сайт"))
    return kb


def admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("📸 Все фотографии"))
    kb.add(types.KeyboardButton("🌐 Открыть сайт"))
    return kb


def cancel_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb


def category_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(
        types.KeyboardButton("😂 Смешные фото"),
        types.KeyboardButton("🌳 Прогулка"),
        types.KeyboardButton("🍲 Еда"),
        types.KeyboardButton("✏️ Другое")
    )
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb


# ============================================================
# /start
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    user_states.pop(chat_id, None)

    args = message.text.split()
    from_site = len(args) > 1 and args[1] == "submit"

    if chat_id == ADMIN_ID:
        bot.send_message(
            chat_id,
            "👋 *Привет, администратор!*\n\n"
            "Все новые фото будут приходить сюда на модерацию.\n"
            "В разделе «📸 Все фотографии» можно удалить любой пост одной кнопкой.",
            parse_mode='Markdown',
            reply_markup=admin_keyboard()
        )
        return

    if from_site:
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
            "Давайте добавим ваше фото в архив!\n\n"
            "📌 *Шаг 1 из 3*\n\nВведите *заголовок*:",
            parse_mode='Markdown',
            reply_markup=cancel_keyboard()
        )
        return

    bot.send_message(
        chat_id,
        "👋 *Добро пожаловать в архив Советского Техникума-Интерната!*\n\n"
        "Здесь вы можете отправить своё фото.\n"
        "После проверки модератором оно появится на сайте.",
        parse_mode='Markdown',
        reply_markup=user_keyboard()
    )


# ============================================================
# 🌐 Открыть сайт
# ============================================================
@bot.message_handler(func=lambda m: m.text == "🌐 Открыть сайт")
def open_site(message):
    bot.send_message(
        message.chat.id,
        f"🌐 Наш архив:\n\n{SITE_URL}",
        disable_web_page_preview=False
    )


# ============================================================
# 📤 Отправить фото
# ============================================================
@bot.message_handler(func=lambda m: m.text == "📤 Отправить фото")
def user_send_photo_start(message):
    chat_id = message.chat.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "Гость"
    author = f"@{username}" if username else first_name

    user_states[chat_id] = {
        "step": "waiting_title",
        "data": {"author": author, "user_id": chat_id}
    }
    bot.send_message(
        chat_id,
        "📌 *Шаг 1 из 3*\n\nВведите *заголовок* для фото:",
        parse_mode='Markdown',
        reply_markup=cancel_keyboard()
    )


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

        bot.send_message(message.chat.id, f"📸 *Всего постов: {len(docs)}*", parse_mode='Markdown')

        for doc in docs:
            data = doc.to_dict()

            title = data.get('title', 'Без названия')
            category = data.get('category', 'Без категории')
            author = data.get('author', 'Гость')
            status = data.get('status', 'pending')

            status_emoji = {
                'approved': '✅ Опубликован',
                'pending': '⏳ На модерации',
                'rejected': '❌ Отклонён'
            }.get(status, '❓')

            caption = (
                f"📌 *{title}*\n\n"
                f"📂 {category}\n"
                f"👤 Автор: {author}\n"
                f"📊 Статус: {status_emoji}\n\n"
                f"🆔 `{doc.id}`"
            )

            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("🗑 Удалить этот пост", callback_data=f"del_{doc.id}")
            )

            # Отправляем фото (по file_id — быстро)
            file_id = data.get('imageFileId', '')
            sent = False

            if file_id:
                try:
                    bot.send_photo(message.chat.id, file_id, caption=caption,
                                   parse_mode='Markdown', reply_markup=keyboard)
                    sent = True
                except Exception as e:
                    print(f"file_id не работает: {e}")

            # Или по base64
            if not sent:
                img_b64 = data.get('imageBase64', '')
                if img_b64:
                    try:
                        bot.send_photo(message.chat.id, img_b64, caption=caption,
                                       parse_mode='Markdown', reply_markup=keyboard)
                        sent = True
                    except Exception as e:
                        print(f"base64 не работает: {e}")

            if not sent:
                bot.send_message(message.chat.id, caption + "\n\n⚠️ Фото недоступно",
                                 parse_mode='Markdown', reply_markup=keyboard)

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


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

    # Шаг 1: заголовок
    if state and state["step"] == "waiting_title":
        state["data"]["title"] = text
        state["step"] = "waiting_category"
        bot.send_message(
            chat_id,
            "📌 *Шаг 2 из 3*\n\nВыберите *категорию*:",
            parse_mode='Markdown',
            reply_markup=category_keyboard()
        )
        return

    # Шаг 2: категория
    if state and state["step"] == "waiting_category":
        if text == "✏️ Другое":
            state["step"] = "waiting_custom_category"
            bot.send_message(
                chat_id,
                "✏️ *Введите свою категорию*\n\n"
                "Например: «Спорт», «Учёба», «Праздники»",
                parse_mode='Markdown',
                reply_markup=cancel_keyboard()
            )
            return

        category = text.replace("😂 ", "").replace("🌳 ", "").replace("🍲 ", "").strip()
        if category not in ["Смешные фото", "Прогулка", "Еда"]:
            bot.send_message(chat_id, "❌ Выберите категорию из списка или нажмите «✏️ Другое»")
            return

        state["data"]["category"] = category
        state["step"] = "waiting_photo"
        bot.send_message(
            chat_id,
            "📌 *Шаг 3 из 3*\n\nОтправьте *фотографию* 📷",
            parse_mode='Markdown',
            reply_markup=cancel_keyboard()
        )
        return

    # Пользовательская категория
    if state and state["step"] == "waiting_custom_category":
        custom_cat = text.strip()
        if len(custom_cat) < 2:
            bot.send_message(chat_id, "❌ Слишком короткое название. Введите хотя бы 2 символа")
            return
        if len(custom_cat) > 30:
            bot.send_message(chat_id, "❌ Слишком длинное название. Максимум 30 символов")
            return

        state["data"]["category"] = custom_cat
        state["step"] = "waiting_photo"
        bot.send_message(
            chat_id,
            f"✅ Категория: *{custom_cat}*\n\n"
            f"📌 *Шаг 3 из 3*\n\nОтправьте *фотографию* 📷",
            parse_mode='Markdown',
            reply_markup=cancel_keyboard()
        )
        return

    if state and state["step"] == "waiting_photo":
        bot.send_message(chat_id, "📷 Отправьте фото или нажмите «Отмена»")
        return

    kb = admin_keyboard() if chat_id == ADMIN_ID else user_keyboard()
    bot.send_message(chat_id, "Выберите действие:", reply_markup=kb)


# ============================================================
# ПОЛЬЗОВАТЕЛЬ ОТПРАВИЛ ФОТО → НА МОДЕРАЦИЮ
# ============================================================
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if not state or state["step"] != "waiting_photo":
        kb = admin_keyboard() if chat_id == ADMIN_ID else user_keyboard()
        bot.send_message(chat_id, "Сначала нажмите «📤 Отправить фото»", reply_markup=kb)
        return

    file_id = message.photo[-1].file_id

    # Показываем прогресс
    progress = bot.send_message(chat_id, "⏳ Обрабатываем фото...")

    try:
        # Скачиваем и сжимаем в base64
        data_url = download_and_compress_photo(file_id)

        if not data_url:
            bot.edit_message_text(
                "❌ Не удалось обработать фото. Попробуйте ещё раз.",
                chat_id=chat_id,
                message_id=progress.message_id
            )
            return

        # Сохраняем в Firebase
        post = {
            "title": state["data"].get("title", ""),
            "category": state["data"].get("category", ""),
            "text": state["data"].get("text", ""),
            "author": state["data"].get("author", "Гость"),
            "user_id": state["data"].get("user_id", chat_id),
            "imageFileId": file_id,
            "imageBase64": data_url,     # ← постоянное хранение
            "status": "pending",
            "createdAt": firestore.SERVER_TIMESTAMP
        }

        doc_ref = db.collection('posts').add(post)
        post_id = doc_ref[1].id

        # Удаляем прогресс
        try:
            bot.delete_message(chat_id, progress.message_id)
        except:
            pass

        bot.send_message(
            chat_id,
            "✅ *Ваше фото отправлено на модерацию!*\n\n"
            "Как только модератор проверит его — оно появится на сайте.",
            parse_mode='Markdown',
            reply_markup=user_keyboard()
        )

        user_states.pop(chat_id, None)

        # Отправляем админу
        send_to_admin_with_buttons(post_id, post, file_id)

    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        try:
            bot.edit_message_text(
                f"❌ Ошибка: {e}",
                chat_id=chat_id,
                message_id=progress.message_id
            )
        except:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")


# ============================================================
# ОТПРАВКА АДМИНУ НА МОДЕРАЦИЮ
# ============================================================
def send_to_admin_with_buttons(post_id, post, file_id):
    emoji = {'Смешные фото': '😂', 'Прогулка': '🌳', 'Еда': '🍲'}.get(post['category'], '📷')

    caption = (
        f"🆕 *НОВЫЙ ПОСТ НА МОДЕРАЦИИ*\n\n"
        f"📌 *{post['title']}*\n\n"
        f"{emoji} Категория: {post['category']}\n"
        f"👤 Автор: {post['author']}\n\n"
        f"🆔 `{post_id}`\n\n"
        f"👇 Выберите действие:"
    )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{post_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{post_id}")
    )

    try:
        bot.send_photo(ADMIN_ID, file_id, caption=caption,
                       parse_mode='Markdown', reply_markup=keyboard)
        print(f"✅ Пост {post_id} отправлен админу")
    except Exception as e:
        print(f"❌ Ошибка отправки админу: {e}")
        bot.send_message(ADMIN_ID, caption, parse_mode='Markdown', reply_markup=keyboard)


# ============================================================
# ОБРАБОТКА КНОПОК
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

            post = doc.to_dict()
            doc_ref.update({"status": "approved"})

            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "✅ Пост одобрен!")

            bot.send_message(
                ADMIN_ID,
                f"✅ *Пост опубликован на сайте!*\n\n"
                f"📌 {post.get('title', '')}\n"
                f"👤 {post.get('author', 'Гость')}\n\n"
                f"🔗 {SITE_URL}",
                parse_mode='Markdown',
                disable_web_page_preview=True
            )

            user_id = post.get('user_id')
            if user_id:
                try:
                    bot.send_message(
                        user_id,
                        f"🎉 *Ваш пост одобрен!*\n\n"
                        f"📌 «{post.get('title', '')}»\n\n"
                        f"🔗 Посмотреть: {SITE_URL}",
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                except:
                    pass

        except Exception as e:
            print(f"❌ Ошибка: {e}")
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
            doc_ref.delete()

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
                f"👤 {post.get('author', 'Гость')}",
                parse_mode='Markdown'
            )

            user_id = post.get('user_id')
            if user_id:
                try:
                    bot.send_message(
                        user_id,
                        f"😔 *Ваш пост отклонён модератором.*\n\n"
                        f"📌 «{post.get('title', '')}»",
                        parse_mode='Markdown'
                    )
                except:
                    pass
        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка: {e}")

    # ===== УДАЛИТЬ =====
    elif data.startswith("del_"):
        post_id = data.replace("del_", "")
        try:
            doc_ref = db.collection('posts').document(post_id)
            doc = doc_ref.get()
            if not doc.exists:
                bot.answer_callback_query(call.id, "❌ Пост уже удалён")
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None
                )
                return

            post = doc.to_dict()
            doc_ref.delete()

            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "🗑 Пост удалён!")

            bot.send_message(
                ADMIN_ID,
                f"🗑 *Пост удалён из архива*\n\n"
                f"📌 {post.get('title', '')}\n"
                f"👤 {post.get('author', 'Гость')}",
                parse_mode='Markdown'
            )

            user_id = post.get('user_id')
            if user_id:
                try:
                    bot.send_message(
                        user_id,
                        f"😔 *Ваш пост был удалён модератором.*\n\n"
                        f"📌 «{post.get('title', '')}»",
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
