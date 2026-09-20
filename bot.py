import os
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore
import json

# ============================================================
# НАСТРОЙКИ (замените на свои)
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8949342076:AAGIMPeRnthC-CjyCSe6ME-4K9Z8JuVm2bI")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 7709067838))

# Путь к файлу с ключом Firebase (service account JSON)
FIREBASE_KEY_PATH = os.environ.get("FIREBASE_KEY_PATH", "firebase-key.json")

# ============================================================
# ИНИЦИАЛИЗАЦИЯ FIREBASE
# ============================================================
try:
    # Если переменная окружения содержит JSON-строку
    firebase_json = os.environ.get("FIREBASE_JSON")
    if firebase_json:
        cred = credentials.Certificate(json.loads(firebase_json))
    else:
        # Иначе читаем из файла
        cred = credentials.Certificate(FIREBASE_KEY_PATH)

    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase успешно подключён")
except Exception as e:
    print(f"❌ Ошибка подключения Firebase: {e}")
    db = None

# ============================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================================
bot = telebot.TeleBot(BOT_TOKEN)

# ============================================================
# КОМАНДА /start
# ============================================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет доступа к этому боту.")
        return

    welcome_text = """
👋 *Добро пожаловать в бот модерации архива!*

📋 *Доступные команды:*

`/pending` — список постов на модерации
`/approve <ID>` — одобрить пост
`/reject <ID>` — отклонить пост
`/stats` — статистика архива
`/help` — это сообщение

💡 *Как это работает:*
1. Пользователь отправляет пост через сайт
2. Вы получаете уведомление в этом боте
3. Используйте команды для модерации
    """
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

# ============================================================
# КОМАНДА /pending — список постов на модерации
# ============================================================
@bot.message_handler(commands=['pending'])
def list_pending(message):
    if message.from_user.id != ADMIN_ID:
        return

    if not db:
        bot.reply_to(message, "❌ Firebase не подключён")
        return

    try:
        posts_ref = db.collection('posts')
        query = posts_ref.where('status', '==', 'pending').order_by('createdAt', direction=firestore.Query.DESCENDING)
        docs = query.stream()

        pending_posts = []
        for doc in docs:
            data = doc.to_dict()
            pending_posts.append({
                'id': doc.id,
                'title': data.get('title', 'Без названия'),
                'category': data.get('category', ''),
                'createdAt': data.get('createdAt', '')
            })

        if not pending_posts:
            bot.reply_to(message, "✅ Нет постов на модерации")
            return

        text = "📋 *Посты на модерации:*\n\n"
        for i, post in enumerate(pending_posts, 1):
            text += f"{i}. *{post['title']}*\n"
            text += f"   🆔 `{post['id']}`\n"
            text += f"   📂 {post['category']}\n\n"

        text += "💡 Используйте `/approve <ID>` или `/reject <ID>`"

        bot.reply_to(message, text, parse_mode='Markdown')

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ============================================================
# КОМАНДА /approve — одобрить пост
# ============================================================
@bot.message_handler(commands=['approve'])
def approve_post(message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: `/approve <ID>`", parse_mode='Markdown')
        return

    post_id = args[1].strip()

    if not db:
        bot.reply_to(message, "❌ Firebase не подключён")
        return

    try:
        post_ref = db.collection('posts').document(post_id)
        post_doc = post_ref.get()

        if not post_doc.exists:
            bot.reply_to(message, f"❌ Пост с ID `{post_id}` не найден", parse_mode='Markdown')
            return

        post_ref.update({'status': 'approved'})
        bot.reply_to(message, f"✅ Пост `{post_id}` одобрен и опубликован!", parse_mode='Markdown')
        print(f"✅ Пост {post_id} одобрен")

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ============================================================
# КОМАНДА /reject — отклонить пост
# ============================================================
@bot.message_handler(commands=['reject'])
def reject_post(message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: `/reject <ID>`", parse_mode='Markdown')
        return

    post_id = args[1].strip()

    if not db:
        bot.reply_to(message, "❌ Firebase не подключён")
        return

    try:
        post_ref = db.collection('posts').document(post_id)
        post_doc = post_ref.get()

        if not post_doc.exists:
            bot.reply_to(message, f"❌ Пост с ID `{post_id}` не найден", parse_mode='Markdown')
            return

        post_ref.update({'status': 'rejected'})
        bot.reply_to(message, f"❌ Пост `{post_id}` отклонён", parse_mode='Markdown')
        print(f"❌ Пост {post_id} отклонён")

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ============================================================
# КОМАНДА /stats — статистика
# ============================================================
@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.from_user.id != ADMIN_ID:
        return

    if not db:
        bot.reply_to(message, "❌ Firebase не подключён")
        return

    try:
        posts_ref = db.collection('posts')
        all_posts = list(posts_ref.stream())

        total = len(all_posts)
        approved = sum(1 for p in all_posts if p.to_dict().get('status') == 'approved')
        pending = sum(1 for p in all_posts if p.to_dict().get('status') == 'pending')
        rejected = sum(1 for p in all_posts if p.to_dict().get('status') == 'rejected')

        stats_text = f"""
📊 *Статистика архива*

📝 Всего постов: *{total}*
✅ Опубликовано: *{approved}*
⏳ На модерации: *{pending}*
❌ Отклонено: *{rejected}*
        """
        bot.reply_to(message, stats_text, parse_mode='Markdown')

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

# ============================================================
# ОБРАБОТКА НЕИЗВЕСТНЫХ СООБЩЕНИЙ
# ============================================================
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, "🤖 Используйте /help для списка команд")

# ============================================================
# ЗАПУСК БОТА
# ============================================================
if __name__ == '__main__':
    print("🚀 Бот запущен...")
    bot.infinity_polling()
