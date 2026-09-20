import os
import json
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore

# ============================================================
# НАСТРОЙКИ (читаются из переменных окружения Render)
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
FIREBASE_JSON = os.environ.get("FIREBASE_JSON")

# ============================================================
# ПРОВЕРКА ПЕРЕМЕННЫХ
# ============================================================
print("=" * 50)
print("🚀 Запуск бота...")
print(f"BOT_TOKEN: {'✅ есть' if BOT_TOKEN else '❌ НЕТ'}")
print(f"ADMIN_ID: {ADMIN_ID if ADMIN_ID else '❌ НЕТ'}")
print(f"FIREBASE_JSON: {'✅ есть' if FIREBASE_JSON else '❌ НЕТ'}")
print("=" * 50)

# ============================================================
# ИНИЦИАЛИЗАЦИЯ FIREBASE
# ============================================================
db = None

if FIREBASE_JSON:
    try:
        cred_dict = json.loads(FIREBASE_JSON)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Firebase успешно подключён")
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка JSON в FIREBASE_JSON: {e}")
    except Exception as e:
        print(f"❌ Ошибка Firebase: {e}")
else:
    print("❌ FIREBASE_JSON не найден в переменных окружения")

# ============================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================================
if not BOT_TOKEN:
    print("❌ BOT_TOKEN не найден — бот не может запуститься")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)


# ============================================================
# /start и /help
# ============================================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет доступа к этому боту.")
        return

    text = """
👋 *Привет, администратор!*

Я бот для модерации постов архива Советского Техникума-Интерната.

📋 *Команды:*

/pending — список постов на модерации
/approve `<ID>` — одобрить пост
/reject `<ID>` — отклонить пост
/stats — статистика архива
/help — эта справка

💡 *Как это работает:*
1. Пользователь отправляет пост через сайт
2. Пост сохраняется в Firebase со статусом "pending"
3. Вы получаете уведомление здесь
4. Одобряете или отклоняете пост командой
    """
    bot.reply_to(message, text, parse_mode='Markdown')


# ============================================================
# /pending — список постов на модерации
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
        query = posts_ref.where('status', '==', 'pending')
        docs = list(query.stream())

        if not docs:
            bot.reply_to(message, "✅ Нет постов на модерации")
            return

        text = f"📋 *Постов на модерации: {len(docs)}*\n\n"
        for i, doc in enumerate(docs, 1):
            data = doc.to_dict()
            title = data.get('title', 'Без названия')
            category = data.get('category', '')
            text += f"{i}. *{title}*\n"
            text += f"   📂 {category}\n"
            text += f"   🆔 `{doc.id}`\n\n"

        text += "💡 `/approve <ID>` или `/reject <ID>`"
        bot.reply_to(message, text, parse_mode='Markdown')

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


# ============================================================
# /approve <ID> — одобрить пост
# ============================================================
@bot.message_handler(commands=['approve'])
def approve_post(message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=1)
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
            bot.reply_to(message, f"❌ Пост `{post_id}` не найден", parse_mode='Markdown')
            return

        post_ref.update({'status': 'approved'})
        bot.reply_to(message, f"✅ Пост `{post_id}` одобрен и опубликован!", parse_mode='Markdown')
        print(f"✅ Пост {post_id} одобрен")

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


# ============================================================
# /reject <ID> — отклонить пост
# ============================================================
@bot.message_handler(commands=['reject'])
def reject_post(message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=1)
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
            bot.reply_to(message, f"❌ Пост `{post_id}` не найден", parse_mode='Markdown')
            return

        post_ref.update({'status': 'rejected'})
        bot.reply_to(message, f"❌ Пост `{post_id}` отклонён", parse_mode='Markdown')
        print(f"❌ Пост {post_id} отклонён")

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


# ============================================================
# /stats — статистика архива
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
        all_docs = list(posts_ref.stream())

        total = len(all_docs)
        approved = sum(1 for d in all_docs if d.to_dict().get('status') == 'approved')
        pending = sum(1 for d in all_docs if d.to_dict().get('status') == 'pending')
        rejected = sum(1 for d in all_docs if d.to_dict().get('status') == 'rejected')

        text = f"""
📊 *Статистика архива*

📝 Всего постов: *{total}*
✅ Опубликовано: *{approved}*
⏳ На модерации: *{pending}*
❌ Отклонено: *{rejected}*
        """
        bot.reply_to(message, text, parse_mode='Markdown')

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


# ============================================================
# Обработка остальных сообщений
# ============================================================
@bot.message_handler(func=lambda m: True)
def echo(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, "🤖 Используйте /help для списка команд")


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == '__main__':
    print("🤖 Бот запущен и слушает сообщения...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
