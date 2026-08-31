"""
🤖 NORVEX SHOP — ЕДИНЫЙ TELEGRAM БОТ + WEB APP МАГАЗИН
=====================================================
Всё работает в ОДНОМ боте:
1. Запуск магазина через кнопку меню «🎮 Магазин» и кнопку «Открыть NORVEX SHOP».
2. Прием заказов прямо в чат бота (без спам-блока).
3. Пересылка заказа вам (администратору) с деталями и кнопками.
4. Ответ покупателю от лица бота через Reply (свайп сообщения) или кнопку.
"""

import json
import logging
from telebot import TeleBot, types

# ==========================================
# ⚙️ НАСТРОЙКИ (ВСТАВЬТЕ ВАШИ ДАННЫЕ)
# ==========================================
BOT_TOKEN = "ВАШ_ТОКЕН_ОТ_BOTFATHER"    # Токен от @BotFather
ADMIN_ID = 123456789                    # Ваш Telegram ID (узнать в @userinfobot)
WEBAPP_URL = "https://your-domain.com"  # Ссылка на ваш index.html

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bot = TeleBot(BOT_TOKEN, parse_mode="HTML")

# Хранилище: order_id -> buyer_id
order_buyers = {}

# ==========================================
# 🚀 КОМАНДА /START (И ДИПЛИНКИ ЗАКАЗОВ)
# ==========================================
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_name = message.from_user.first_name or "Покупатель"
    user_id = message.from_user.id
    
    # 1. Устанавливаем постоянную кнопку «🎮 Магазин» в левом нижнем углу чата
    try:
        bot.set_chat_menu_button(
            message.chat.id,
            types.MenuButtonWebApp(type="web_app", text="🎮 Магазин", web_app=types.WebAppInfo(url=WEBAPP_URL))
        )
    except Exception as e:
        logging.warning(f"Could not set menu button: {e}")

    # 2. Проверяем, не перешел ли клиент по ссылке оформления заказа
    text_args = message.text.split()
    if len(text_args) > 1 and text_args[1].startswith("order_"):
        order_id = text_args[1].replace("order_", "")
        order_buyers[order_id] = user_id
        bot.send_message(
            user_id,
            f"👋 <b>Здравствуйте, {user_name}!</b>\n\n"
            f"Ваш запрос по заказу <b>#{order_id}</b> передан администратору.\n"
            f"⏳ Ожидайте ответа и реквизитов прямо в этом чате!"
        )
        return

    # 3. Обычное приветственное сообщение
    markup = types.InlineKeyboardMarkup()
    web_app_btn = types.InlineKeyboardButton(
        text="🎮 Открыть NORVEX SHOP",
        web_app=types.WebAppInfo(url=WEBAPP_URL)
    )
    support_btn = types.InlineKeyboardButton(
        text="💬 Служба поддержки",
        callback_data="btn_support"
    )
    markup.add(web_app_btn)
    markup.add(support_btn)

    welcome_text = (
        f"👋 <b>Добро пожаловать в NORVEX SHOP, {user_name}!</b>\n\n"
        f"⚡ <b>Игровые ключи, донат, подписки и валюта</b> с моментальной выдачей.\n\n"
        f"Нажмите кнопку ниже или кнопку <b>«🎮 Магазин»</b> внизу, чтобы открыть каталог 👇"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# ==========================================
# 📦 ОБРАБОТКА ЗАКАЗА ИЗ WEB APP
# ==========================================
@bot.message_handler(content_types=['web_app_data'])
def handle_web_app_data(message):
    try:
        data = json.loads(message.web_app_data.data)
        order_id = data.get("orderId", "NVX-000000")
        items = data.get("items", [])
        total_rub = data.get("totalRub", 0)
        total_count = data.get("totalCount", 0)
        buyer_id = message.from_user.id
        buyer_username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {buyer_id}"
        buyer_name = message.from_user.full_name or "Клиент"

        # Привязываем заказ к покупателю
        order_buyers[order_id] = buyer_id

        # Формируем чек
        items_text = ""
        for i, it in enumerate(items, start=1):
            subtotal = it['price'] * it['qty']
            items_text += f"{i}. <b>{it['name']}</b> — {it['qty']} шт. × {it['price']:,} ₽ = <b>{subtotal:,} ₽</b>\n"

        # Ответ покупателю в этом же боте
        buyer_confirm_msg = (
            f"✅ <b>Заказ {order_id} принят!</b>\n\n"
            f"📦 <b>Состав заказа:</b>\n{items_text}\n"
            f"💵 <b>Сумма к оплате:</b> <code>{total_rub:,} ₽</code>\n\n"
            f"⏳ Менеджер уже проверяет заказ и сейчас напишет вам <b>прямо в этот чат</b> реквизиты для оплаты."
        )
        bot.send_message(buyer_id, buyer_confirm_msg)

        # Уведомление админу
        admin_order_msg = (
            f"🛍️ <b>НОВЫЙ ЗАКАЗ: {order_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Покупатель:</b> {buyer_name} ({buyer_username})\n"
            f"🆔 <b>ID клиента:</b> <code>{buyer_id}</code>\n\n"
            f"📦 <b>Товары ({total_count} шт.):</b>\n{items_text}\n"
            f"💵 <b>СУММА К ОПЛАТЕ:</b> <code>{total_rub:,} ₽</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Ответьте на это сообщение (Reply), чтобы отправить покупателю реквизиты или ключ!</i>"
        )

        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        reply_btn = types.InlineKeyboardButton("💬 Написать клиенту", callback_data=f"reply_{order_id}")
        done_btn = types.InlineKeyboardButton("✅ Заказ выполнен", callback_data=f"done_{order_id}")
        admin_markup.add(reply_btn, done_btn)

        bot.send_message(ADMIN_ID, admin_order_msg, reply_markup=admin_markup)
        logging.info(f"Order {order_id} from {buyer_id} processed.")

    except Exception as e:
        logging.error(f"Error handling web_app_data: {e}")
        bot.send_message(message.chat.id, "⚠️ Ошибка при обработке заказа. Попробуйте еще раз.")

# ==========================================
# 💬 ДВУСТОРОННЯЯ СВЯЗЬ: АДМИН -> КЛИЕНТ
# ==========================================
@bot.message_handler(func=lambda msg: msg.chat.id == ADMIN_ID and msg.reply_to_message is not None)
def handle_admin_reply(message):
    """
    Админ нажимает «Ответить» (Reply) на сообщение заказа,
    и бот пересылает текст клиенту прямо в чат с этим ботом.
    """
    reply_text = message.reply_to_message.text or ""
    
    # Поиск номера заказа
    order_id = None
    if "NVX-" in reply_text:
        for word in reply_text.split():
            if "NVX-" in word:
                order_id = word.replace(":", "").replace("[", "").replace("]", "").strip()
                break

    if not order_id or order_id not in order_buyers:
        bot.reply_to(message, "⚠️ Не удалось определить покупателя. Нажмите кнопку «💬 Написать клиенту».")
        return

    buyer_id = order_buyers[order_id]
    try:
        bot.send_message(
            buyer_id,
            f"💬 <b>Сообщение от администрации NORVEX SHOP (по заказу {order_id}):</b>\n\n{message.text}"
        )
        bot.reply_to(message, f"✅ Сообщение доставлено клиенту (ID: {buyer_id})!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка отправки: {e}")

# ==========================================
# 🔘 КНОПКИ УПРАВЛЕНИЯ
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data == "btn_support":
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "💬 <b>Служба поддержки NORVEX SHOP:</b>\nНапишите ваш вопрос прямо в этот чат, и оператор ответит вам."
        )
    elif call.data.startswith("done_"):
        order_id = call.data.replace("done_", "")
        bot.answer_callback_query(call.id, "Заказ отмечен как выполнен!")
        bot.edit_message_text(
            call.message.text + "\n\n<b>✅ СТАТУС: ЗАКАЗ ВЫПОЛНЕН</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
    elif call.data.startswith("reply_"):
        order_id = call.data.replace("reply_", "")
        bot.answer_callback_query(call.id)
        msg = bot.send_message(
            ADMIN_ID,
            f"✍️ <b>Введите сообщение для клиента по заказу {order_id}:</b>"
        )
        bot.register_next_step_handler(msg, send_direct_reply_to_buyer, order_id)

def send_direct_reply_to_buyer(message, order_id):
    if order_id not in order_buyers:
        bot.send_message(ADMIN_ID, "⚠️ Покупатель не найден.")
        return

    buyer_id = order_buyers[order_id]
    try:
        bot.send_message(
            buyer_id,
            f"💬 <b>Сообщение по заказу {order_id} от NORVEX SHOP:</b>\n\n{message.text}"
        )
        bot.send_message(ADMIN_ID, f"✅ Сообщение доставлено покупателю!")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка отправки: {e}")

if __name__ == "__main__":
    print("🚀 NORVEX SHOP Bot запущен и ожидает заказы...")
    bot.infinity_polling()
