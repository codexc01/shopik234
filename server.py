import os
import sys
import uuid
import json
import logging
import threading
import aiofiles
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, APIRouter, Request, HTTPException, Depends, Header, UploadFile, File, Form, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database as db
from auth import validate_telegram_init_data

# чтение .env если есть
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

# конфиг и переменные
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [a.strip() for a in ADMIN_IDS_RAW.split(",") if a.strip()]
WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://localhost:8000")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    UPLOADS_DIR = "/tmp/uploads"
else:
    UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("norvex_server")

app = FastAPI(title="NORVEX SHOP Backend API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# статика для загруженных картинок
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# проверка пользователя телеграм
async def get_current_tg_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        # локальный режим если тестируем без телеграма
        return {"user_id": 999999, "username": "local_dev", "is_admin": True, "is_local": True}

    token = authorization.replace("Bearer ", "").strip()
    if not token or token == "null" or token == "undefined":
        return {"user_id": 999999, "username": "local_dev", "is_admin": True, "is_local": True}

    auth_result = validate_telegram_init_data(token, BOT_TOKEN, ADMIN_IDS)
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительная подпись Telegram initData"
        )
    return auth_result

# проверка прав админа
async def require_admin(user: Dict[str, Any] = Depends(get_current_tg_user)) -> Dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ только для админа"
        )
    return user

# схемы валидации
class CategoryCreate(BaseModel):
    name: str
    iconKey: str = "games"

class ProductCreate(BaseModel):
    name: str
    catId: str
    price: int
    oldPrice: Optional[int] = 0
    badge: Optional[str] = ""
    img: Optional[str] = ""
    desc: Optional[str] = ""

class ProductUpdate(BaseModel):
    name: str
    catId: str
    price: int
    oldPrice: Optional[int] = 0
    badge: Optional[str] = ""
    img: Optional[str] = ""
    desc: Optional[str] = ""

class OrderItemInput(BaseModel):
    id: str
    qty: int = 1

class OrderCreateRequest(BaseModel):
    items: List[OrderItemInput]

class SettingsUpdate(BaseModel):
    botUsername: Optional[str] = None
    storeTitle: Optional[str] = None

router = APIRouter()

# главная страница магазина
@app.get("/")
@router.get("/")
async def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>NORVEX SHOP</h1><p>Загрузка витрины...</p>")

# проверка статуса апи
@app.get("/api")
@router.get("/api")
async def root_api():
    return {"ok": True, "status": "online", "message": "NORVEX SHOP API работает"}

# получение стартовых данных магазина
@router.get("/bootstrap")
@router.get("/api/bootstrap")
@app.get("/bootstrap")
@app.get("/api/bootstrap")
async def bootstrap(user: Dict[str, Any] = Depends(get_current_tg_user)):
    categories = db.get_categories()
    products = db.get_products()
    store_title = db.get_setting("store_title", "NORVEX SHOP")
    bot_handle = db.get_setting("tg_bot_handle", "NorvexShopBot")

    return {
        "ok": True,
        "isAdmin": user.get("is_admin", False),
        "user": user.get("user", {}),
        "storeTitle": store_title,
        "botHandle": bot_handle,
        "categories": categories,
        "products": products
    }

# список товаров
@router.get("/products")
async def list_products(catId: Optional[str] = None, q: Optional[str] = None):
    products = db.get_products(category_id=catId, search=q)
    return {"ok": True, "products": products}

# список категорий
@router.get("/categories")
async def list_categories():
    categories = db.get_categories()
    return {"ok": True, "categories": categories}

# оформление заказа с серверным расчетом цены
@router.post("/orders")
async def create_order(payload: OrderCreateRequest, user: Dict[str, Any] = Depends(get_current_tg_user)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Корзина пуста")

    try:
        buyer_id = user.get("user_id")
        user_info = user.get("user") or {}
        buyer_name = user_info.get("first_name") or user.get("username") or "Покупатель"
        buyer_username = user.get("username") or f"ID: {buyer_id}"

        raw_items = [{"id": it.id, "qty": it.qty} for it in payload.items]
        order_data, verified_items = db.create_secure_order(buyer_id, buyer_name, buyer_username, raw_items)

        # отправляем чек в телеграм
        send_order_bot_notifications(order_data, verified_items)

        return {
            "ok": True,
            "order": order_data
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"ошибка при создании заказа: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера при создании заказа")

# загрузка фото на сервер
@router.post("/upload")
async def upload_image(file: UploadFile = File(...), admin: Dict[str, Any] = Depends(require_admin)):
    allowed_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="Недопустимый формат файла")

    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOADS_DIR, filename)

    async with aiofiles.open(file_path, "wb") as out_file:
        while content := await file.read(1024 * 1024):
            await out_file.write(content)

    url_path = f"/uploads/{filename}"
    return {"ok": True, "url": url_path}

# добавление товара
@router.post("/products")
async def add_product(prod: ProductCreate, admin: Dict[str, Any] = Depends(require_admin)):
    new_prod = db.create_product(
        name=prod.name,
        category_id=prod.catId,
        price=prod.price,
        old_price=prod.oldPrice or 0,
        badge=prod.badge or "",
        image_url=prod.img or "",
        description=prod.desc or ""
    )
    return {"ok": True, "product": new_prod}

# редактирование товара
@router.put("/products/{prod_id}")
async def edit_product(prod_id: str, prod: ProductUpdate, admin: Dict[str, Any] = Depends(require_admin)):
    updated = db.update_product(
        prod_id=prod_id,
        name=prod.name,
        category_id=prod.catId,
        price=prod.price,
        old_price=prod.oldPrice or 0,
        badge=prod.badge or "",
        image_url=prod.img or "",
        description=prod.desc or ""
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return {"ok": True, "product": updated}

# удаление товара
@router.delete("/products/{prod_id}")
async def remove_product(prod_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    success = db.delete_product(prod_id)
    return {"ok": success}

# создание категории
@router.post("/categories")
async def add_category(cat: CategoryCreate, admin: Dict[str, Any] = Depends(require_admin)):
    cat_id = f"cat_{int(uuid.uuid4().int % 100000000)}"
    new_cat = db.create_category(cat_id, cat.name, cat.iconKey)
    return {"ok": True, "category": new_cat}

# удаление категории
@router.delete("/categories/{cat_id}")
async def remove_category(cat_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    success = db.delete_category(cat_id)
    return {"ok": success}

# сохранение настроек шопа
@router.post("/settings")
async def update_settings(settings: SettingsUpdate, admin: Dict[str, Any] = Depends(require_admin)):
    if settings.storeTitle:
        db.set_setting("store_title", settings.storeTitle)
    if settings.botUsername:
        db.set_setting("tg_bot_handle", settings.botUsername.replace("@", ""))
    return {"ok": True}

# обработка вебхука бота
@router.post("/webhook")
async def telegram_webhook(request: Request):
    if not BOT_TOKEN or "YOUR_BOT_TOKEN" in BOT_TOKEN:
        return {"ok": False, "error": "нет токена бота"}

    try:
        import telebot
        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
        update_json = await request.json()
        update = telebot.types.Update.de_json(update_json)
        
        if update.message:
            msg = update.message
            if msg.text and msg.text.startswith("/start"):
                webapp_url = os.environ.get("WEBAPP_URL", "https://shopik234.vercel.app")
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("🎮 Открыть магазин", web_app=telebot.types.WebAppInfo(url=webapp_url)))
                tg_bot.send_message(
                    msg.chat.id,
                    "Нажмите кнопку ниже 👇",
                    reply_markup=markup
                )
            elif msg.reply_to_message:
                # ответ админа через реплай клиенту
                reply_text = msg.reply_to_message.text or ""
                order_id = None
                if "NVX-" in reply_text:
                    for word in reply_text.split():
                        if "NVX-" in word:
                            order_id = word.replace(":", "").replace("[", "").replace("]", "").strip()
                            break
                if order_id and order_id in order_buyers_cache:
                    buyer_id = order_buyers_cache[order_id]
                    tg_bot.send_message(buyer_id, f"💬 <b>Сообщение от магазина:</b>\n\n{msg.text}")
                    tg_bot.reply_to(msg, f"✅ Сообщение отправлено покупателю (ID: {buyer_id})")

        return {"ok": True}
    except Exception as e:
        logger.error(f"ошибка обработки вебхука: {e}")
        return {"ok": False, "error": str(e)}

# подключение роутера
app.include_router(router)
app.include_router(router, prefix="/api")

# кэш покупателей для ответов через реплай
order_buyers_cache = {}

# отправка чеков и уведомлений о заказе
def send_order_bot_notifications(order_data: Dict[str, Any], verified_items: List[Dict[str, Any]]):
    if not BOT_TOKEN or "YOUR_BOT_TOKEN" in BOT_TOKEN:
        return

    try:
        import telebot
        from telebot import types
        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

        order_id = order_data["orderId"]
        buyer_id = order_data.get("buyerId")
        buyer_name = order_data.get("buyerName", "Клиент")
        buyer_username = f"@{order_data['buyerUsername']}" if order_data.get("buyerUsername") and not order_data['buyerUsername'].startswith("ID:") else order_data.get("buyerUsername", "")
        total_rub = order_data["totalRub"]
        total_count = order_data["totalCount"]

        if buyer_id:
            order_buyers_cache[order_id] = buyer_id

        # форматируем список товаров
        items_text = ""
        for i, it in enumerate(verified_items, start=1):
            items_text += f"{i}. <b>{it['name']}</b>: {it['qty']} шт × {it['price']:,} ₽ = <b>{it['subtotal']:,} ₽</b>\n"

        # чек покупателю
        if buyer_id:
            try:
                buyer_receipt = (
                    f"✅ <b>Заказ #{order_id} принят</b>\n\n"
                    f"📦 <b>Товары:</b>\n{items_text}\n"
                    f"💵 <b>Сумма к оплате:</b> <code>{total_rub:,} ₽</code>\n\n"
                    f"⏳ Скоро напишем прямо сюда для оплаты"
                )
                tg_bot.send_message(buyer_id, buyer_receipt)
            except Exception as e:
                logger.warning(f"не удалось отправить чек клиенту: {e}")

        # уведомление админу
        admin_order_msg = (
            f"🛍️ <b>Новый заказ: {order_id}</b>\n\n"
            f"👤 <b>Покупатель:</b> {buyer_name} ({buyer_username})\n"
            f"🆔 <b>ID клиента:</b> <code>{buyer_id}</code>\n\n"
            f"📦 <b>Товары ({total_count} шт):</b>\n{items_text}\n"
            f"💵 <b>Сумма к оплате:</b> <code>{total_rub:,} ₽</code>\n\n"
            f"💡 <i>Ответьте через Reply на это сообщение</i>"
        )

        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        done_btn = types.InlineKeyboardButton("✅ Заказ выполнен", callback_data=f"done_{order_id}")
        admin_markup.add(done_btn)

        for adm in ADMIN_IDS:
            if adm.isdigit():
                try:
                    tg_bot.send_message(int(adm), admin_order_msg, reply_markup=admin_markup)
                except Exception as e:
                    logger.warning(f"не удалось уведомить админа: {e}")

    except Exception as e:
        logger.error(f"ошибка отправки уведомления: {e}")

# локальный поллинг бота при разработке
def run_bot_listener():
    if not BOT_TOKEN or "YOUR_BOT_TOKEN" in BOT_TOKEN:
        return

    try:
        import telebot
        from telebot import types
        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

        @tg_bot.message_handler(commands=['start'])
        def on_start(msg):
            webapp_url = os.environ.get("WEBAPP_URL", "https://shopik234.vercel.app")
            
            try:
                tg_bot.set_chat_menu_button(
                    msg.chat.id,
                    types.MenuButtonWebApp(type="web_app", text="🎮 Магазин", web_app=types.WebAppInfo(url=webapp_url))
                )
            except Exception:
                pass

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🎮 Открыть магазин", web_app=types.WebAppInfo(url=webapp_url)))
            tg_bot.send_message(
                msg.chat.id,
                "Нажмите кнопку ниже 👇",
                reply_markup=markup
            )

        @tg_bot.message_handler(func=lambda m: m.reply_to_message is not None)
        def on_admin_reply(msg):
            reply_text = msg.reply_to_message.text or ""
            order_id = None
            if "NVX-" in reply_text:
                for word in reply_text.split():
                    if "NVX-" in word:
                        order_id = word.replace(":", "").replace("[", "").replace("]", "").strip()
                        break

            if order_id and order_id in order_buyers_cache:
                buyer_id = order_buyers_cache[order_id]
                try:
                    tg_bot.send_message(
                        buyer_id,
                        f"💬 <b>Сообщение от магазина:</b>\n\n{msg.text}"
                    )
                    tg_bot.reply_to(msg, f"✅ Сообщение отправлено покупателю (ID: {buyer_id})")
                except Exception as e:
                    tg_bot.reply_to(msg, f"❌ Ошибка отправки: {e}")

        @tg_bot.callback_query_handler(func=lambda call: call.data.startswith("done_"))
        def on_done(call):
            tg_bot.answer_callback_query(call.id, "Заказ отмечен как выполнен")
            tg_bot.edit_message_text(
                call.message.text + "\n\n<b>✅ Статус: заказ выполнен</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        logger.info("бот слушает события через polling")
        tg_bot.infinity_polling()
    except Exception as e:
        logger.error(f"ошибка поллинга бота: {e}")

# запускаем поллинг только если не на верселе
if not (os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")):
    threading.Thread(target=run_bot_listener, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
