import os
import sys
import uuid
import json
import time
import html
import logging
import threading
import asyncio
import aiofiles
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, APIRouter, Request, HTTPException, Depends, Header, UploadFile, File, Form, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import database as db
import payments
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "").strip()
ADMIN_IDS = [a.strip() for a in ADMIN_IDS_RAW.split(",") if a.strip()]
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://shopik234.vercel.app").strip()

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

app = FastAPI(title="NORVEX SHOP Luxury API", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# статика для картинок
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# проверка пользователя телеграм (безопасная проверка с защитой админки)
async def get_current_tg_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        return {"user_id": None, "username": "guest", "is_admin": False, "is_guest": True}

    token = authorization.replace("Bearer ", "").strip()
    if not token or token in ["null", "undefined", "none", ""]:
        return {"user_id": None, "username": "guest", "is_admin": False, "is_guest": True}

    auth_result = validate_telegram_init_data(token, BOT_TOKEN, ADMIN_IDS)
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительная или устаревшая подпись Telegram initData"
        )
    return auth_result

# проверка прав админа (строгий запрет для гостей)
async def require_admin(user: Dict[str, Any] = Depends(get_current_tg_user)) -> Dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещен: требуются права администратора"
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
    qty: int = Field(default=1, ge=1, le=100)

class OrderCreateRequest(BaseModel):
    items: List[OrderItemInput]
    paymentMethod: Optional[str] = "manual"
    promoCode: Optional[str] = ""
    useBonus: Optional[int] = Field(default=0, ge=0)

class PromoValidateRequest(BaseModel):
    code: str
    totalRub: int = Field(..., ge=0)

class PromoCreateRequest(BaseModel):
    code: str
    discountType: str = "percent" # "percent" | "fixed"
    discountVal: float = Field(..., gt=0)
    minOrder: Optional[int] = Field(default=0, ge=0)
    maxUses: Optional[int] = Field(default=0, ge=0)

class StockAddRequest(BaseModel):
    keys: List[str]

class BroadcastRequest(BaseModel):
    text: str
    buttonText: Optional[str] = None
    buttonUrl: Optional[str] = None
    imageUrl: Optional[str] = None

class SettingsUpdate(BaseModel):
    botUsername: Optional[str] = None
    storeTitle: Optional[str] = None
    refPercent: Optional[int] = Field(default=5, ge=0, le=50)

class PaymentSettingsUpdate(BaseModel):
    cryptobotEnabled: Optional[bool] = None
    cryptobotToken: Optional[str] = None
    starsEnabled: Optional[bool] = None
    starsRate: Optional[float] = None
    aaioEnabled: Optional[bool] = None
    aaioMerchantId: Optional[str] = None
    aaioSecret1: Optional[str] = None
    aaioSecret2: Optional[str] = None
    sbpEnabled: Optional[bool] = None
    sbpPhone: Optional[str] = None
    sbpBank: Optional[str] = None
    sbpRecipient: Optional[str] = None

router = APIRouter()
order_buyers_cache = {}

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
    return {"ok": True, "status": "online", "message": "NORVEX SHOP Luxury API работает"}

# получение стартовых данных магазина
@router.get("/bootstrap")
@router.get("/api/bootstrap")
@app.get("/bootstrap")
@app.get("/api/bootstrap")
async def bootstrap(user: Dict[str, Any] = Depends(get_current_tg_user)):
    user_id = user.get("user_id")
    user_info = user.get("user") or {}
    
    # авторегистрация пользователя
    if user_id:
        db.register_bot_user(
            user_id=user_id,
            username=user.get("username", ""),
            first_name=user_info.get("first_name", "")
        )

    categories = db.get_categories()
    products = db.get_products()
    store_title = db.get_setting("store_title", "NORVEX SHOP")
    bot_handle = db.get_setting("tg_bot_handle", "NorvexShopBot")
    ref_percent = int(db.get_setting("ref_percent", "5"))

    payment_methods = get_public_payment_methods()
    user_profile = db.get_user_profile(user_id) if user_id else {}

    return {
        "ok": True,
        "isAdmin": user.get("is_admin", False),
        "user": user.get("user", {}),
        "storeTitle": store_title,
        "botHandle": bot_handle,
        "refPercent": ref_percent,
        "categories": categories,
        "products": products,
        "paymentMethods": payment_methods,
        "profile": user_profile
    }

def get_public_payment_methods() -> Dict[str, Any]:
    cryptobot_token = db.get_setting("cryptobot_token", os.environ.get("CRYPTOBOT_TOKEN", ""))
    cryptobot_enabled = db.get_setting("cryptobot_enabled", "true" if cryptobot_token else "false") == "true"
    
    stars_enabled = db.get_setting("stars_enabled", "true") == "true"
    stars_rate = float(db.get_setting("stars_rate", "2.0"))
    
    aaio_merchant = db.get_setting("aaio_merchant_id", os.environ.get("AAIO_MERCHANT_ID", ""))
    aaio_enabled = db.get_setting("aaio_enabled", "true" if aaio_merchant else "false") == "true"
    
    sbp_enabled = db.get_setting("sbp_enabled", "true") == "true"
    sbp_phone = db.get_setting("sbp_phone", "")
    sbp_bank = db.get_setting("sbp_bank", "СБП / Т-Банк / Сбер")
    sbp_recipient = db.get_setting("sbp_recipient", "")

    return {
        "cryptobot": {"enabled": cryptobot_enabled, "name": "CryptoBot (USDT, TON)", "icon": "💎"},
        "stars": {"enabled": stars_enabled, "name": "Telegram Stars (Звёзды)", "icon": "⭐", "rate": stars_rate},
        "aaio": {"enabled": aaio_enabled, "name": "Карты РФ / СБП (Aaio)", "icon": "💳"},
        "sbp": {
            "enabled": sbp_enabled,
            "name": "Прямой перевод СБП",
            "icon": "📱",
            "phone": sbp_phone,
            "bank": sbp_bank,
            "recipient": sbp_recipient
        }
    }

# профиль пользователя и рефералы
@router.get("/profile")
async def get_profile(user: Dict[str, Any] = Depends(get_current_tg_user)):
    user_id = user.get("user_id")
    profile = db.get_user_profile(user_id) if user_id else {}
    return {"ok": True, "profile": profile}

# история покупок пользователя
@router.get("/my-orders")
async def get_my_orders(user: Dict[str, Any] = Depends(get_current_tg_user)):
    user_id = user.get("user_id")
    orders = db.get_user_orders(user_id) if user_id else []
    return {"ok": True, "orders": orders}

# проверка промокода
@router.post("/promo/validate")
async def validate_promo_endpoint(payload: PromoValidateRequest):
    ok, msg, discount_rub = db.validate_promo(payload.code, payload.totalRub)
    return {
        "ok": ok,
        "message": msg,
        "discountRub": discount_rub
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

# оформление заказа с промокодом, бонусами и платежной интеграцией
@router.post("/orders")
async def create_order(payload: OrderCreateRequest, user: Dict[str, Any] = Depends(get_current_tg_user)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Корзина пуста")

    try:
        buyer_id = user.get("user_id")
        user_info = user.get("user") or {}
        buyer_name = user_info.get("first_name") or user.get("username") or "Покупатель"
        buyer_username = user.get("username") or (f"ID: {buyer_id}" if buyer_id else "Гость")
        payment_method = (payload.paymentMethod or "manual").lower()

        raw_items = [{"id": it.id, "qty": max(1, min(it.qty, 100))} for it in payload.items]
        bonus_to_use = payload.useBonus if buyer_id else 0
        
        order_data, verified_items = db.create_secure_order(
            buyer_id=buyer_id, 
            buyer_name=buyer_name, 
            buyer_username=buyer_username, 
            client_items=raw_items,
            promo_code=payload.promoCode or "",
            use_bonus=bonus_to_use
        )
        order_code = order_data["orderId"]
        total_rub = order_data["totalRub"]

        payment_result = {
            "method": payment_method,
            "payUrl": None,
            "invoiceLink": None,
            "starsAmount": None,
            "sbpInfo": None
        }

        # 1. CryptoBot
        if payment_method == "cryptobot":
            cb_token = db.get_setting("cryptobot_token", os.environ.get("CRYPTOBOT_TOKEN", ""))
            if cb_token:
                store_title = db.get_setting("store_title", "NORVEX SHOP")
                invoice = await payments.create_cryptobot_invoice(
                    api_token=cb_token,
                    order_code=order_code,
                    amount_rub=float(total_rub),
                    description=f"{store_title} заказ"
                )
                if invoice:
                    payment_result["payUrl"] = invoice.get("pay_url")
                    db.update_order_payment(order_code, "cryptobot", str(invoice.get("invoice_id")), invoice.get("pay_url"))

        # 2. Telegram Stars
        elif payment_method == "stars":
            stars_rate = float(db.get_setting("stars_rate", "2.0"))
            stars_amount = max(1, round(total_rub / (stars_rate if stars_rate > 0 else 2.0)))
            store_title = db.get_setting("store_title", "NORVEX SHOP")
            
            invoice_link = await payments.create_telegram_stars_invoice_link(
                bot_token=BOT_TOKEN,
                order_code=order_code,
                title=f"Заказ #{order_code}",
                description=f"Оплата в {store_title} ({len(verified_items)} поз.)",
                stars_amount=stars_amount
            )
            if invoice_link:
                payment_result["invoiceLink"] = invoice_link
                payment_result["starsAmount"] = stars_amount
                db.update_order_payment(order_code, "stars", "", invoice_link)

        # 3. Aaio (Карты РФ / СБП)
        elif payment_method == "aaio":
            m_id = db.get_setting("aaio_merchant_id", os.environ.get("AAIO_MERCHANT_ID", ""))
            s_1 = db.get_setting("aaio_secret_1", os.environ.get("AAIO_SECRET_1", ""))
            if m_id and s_1:
                store_title = db.get_setting("store_title", "NORVEX SHOP")
                pay_url = payments.create_aaio_payment_url(
                    merchant_id=m_id,
                    secret_1=s_1,
                    order_code=order_code,
                    amount_rub=float(total_rub),
                    description=f"{store_title} заказ"
                )
                if pay_url:
                    payment_result["payUrl"] = pay_url
                    db.update_order_payment(order_code, "aaio", "", pay_url)

        # 4. СБП Прямой перевод
        elif payment_method == "sbp":
            db.update_order_payment(order_code, "sbp")
            payment_result["sbpInfo"] = {
                "phone": db.get_setting("sbp_phone", ""),
                "bank": db.get_setting("sbp_bank", "СБП"),
                "recipient": db.get_setting("sbp_recipient", "")
            }
        else:
            db.update_order_payment(order_code, "manual")

        # отправляем чек и уведомления
        send_order_bot_notifications(order_data, verified_items, payment_result)

        return {
            "ok": True,
            "order": order_data,
            "payment": payment_result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"ошибка создания заказа: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при создании заказа")

# загрузка картинок товаров
@router.post("/upload")
async def upload_image(file: UploadFile = File(...), admin: Dict[str, Any] = Depends(require_admin)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        ext = ".png"

    filename = f"img_{uuid.uuid4().hex[:12]}{ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)

    try:
        content = await file.read()
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(content)
        return {"ok": True, "url": f"/uploads/{filename}"}
    except Exception as e:
        logger.error(f"ошибка загрузки файла: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при сохранении изображения")

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

# сохранение общих настроек
@router.post("/settings")
async def update_settings(settings: SettingsUpdate, admin: Dict[str, Any] = Depends(require_admin)):
    if settings.storeTitle:
        db.set_setting("store_title", settings.storeTitle)
    if settings.botUsername:
        db.set_setting("tg_bot_handle", settings.botUsername.replace("@", ""))
    if settings.refPercent is not None:
        db.set_setting("ref_percent", str(settings.refPercent))
    return {"ok": True}

# --- АДМИНКА: СКЛАД ЦИФРОВЫХ КЛЮЧЕЙ (АВТОВЫДАЧА) ---
@router.get("/admin/stock/{product_id}")
async def get_stock(product_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    stock_items = db.get_product_stock(product_id)
    return {"ok": True, "stock": stock_items}

@router.post("/admin/stock/{product_id}")
async def add_stock(product_id: str, payload: StockAddRequest, admin: Dict[str, Any] = Depends(require_admin)):
    added_count = db.add_product_stock(product_id, payload.keys)
    return {"ok": True, "addedCount": added_count}

# --- АДМИНКА: ПРОМОКОДЫ ---
@router.get("/admin/promos")
async def list_promos(admin: Dict[str, Any] = Depends(require_admin)):
    promos = db.get_all_promos()
    return {"ok": True, "promos": promos}

@router.post("/admin/promos")
async def create_promo_endpoint(payload: PromoCreateRequest, admin: Dict[str, Any] = Depends(require_admin)):
    res = db.create_promo_code(
        code=payload.code,
        discount_type=payload.discountType,
        discount_val=payload.discountVal,
        min_order=payload.minOrder or 0,
        max_uses=payload.maxUses or 0
    )
    return {"ok": True, "promo": res}

@router.delete("/admin/promos/{code}")
async def delete_promo_endpoint(code: str, admin: Dict[str, Any] = Depends(require_admin)):
    success = db.delete_promo_code(code)
    return {"ok": success}

# --- АДМИНКА: РАССЫЛКА ПО БАЗЕ ПОЛЬЗОВАТЕЛЕЙ ---
@router.post("/admin/broadcast")
async def broadcast_message(payload: BroadcastRequest, admin: Dict[str, Any] = Depends(require_admin)):
    if not BOT_TOKEN:
        raise HTTPException(status_code=400, detail="Токен бота не настроен в переменных окружения")

    users = db.get_all_bot_users()
    if not users:
        return {"ok": True, "sent": 0, "total": 0, "message": "В базе пока нет пользователей"}

    import telebot
    from telebot import types
    tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

    markup = None
    if payload.buttonText and payload.buttonUrl:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(payload.buttonText, url=payload.buttonUrl))

    sent_count = 0
    fail_count = 0

    for u in users:
        uid = u["userId"]
        try:
            if payload.imageUrl and payload.imageUrl.startswith("http"):
                tg_bot.send_photo(uid, payload.imageUrl, caption=payload.text, reply_markup=markup)
            else:
                tg_bot.send_message(uid, payload.text, reply_markup=markup)
            sent_count += 1
            await asyncio.sleep(0.05) # защита от лимитов telegram
        except Exception:
            fail_count += 1

    return {
        "ok": True,
        "sent": sent_count,
        "failed": fail_count,
        "total": len(users)
    }

# --- АДМИНКА: ПЛАТЕЖНЫЕ НАСТРОЙКИ ---
@router.get("/admin/payment-settings")
async def get_admin_payment_settings(admin: Dict[str, Any] = Depends(require_admin)):
    return {
        "ok": True,
        "cryptobotEnabled": db.get_setting("cryptobot_enabled", "false") == "true",
        "cryptobotToken": db.get_setting("cryptobot_token", os.environ.get("CRYPTOBOT_TOKEN", "")),
        "starsEnabled": db.get_setting("stars_enabled", "true") == "true",
        "starsRate": float(db.get_setting("stars_rate", "2.0")),
        "aaioEnabled": db.get_setting("aaio_enabled", "false") == "true",
        "aaioMerchantId": db.get_setting("aaio_merchant_id", os.environ.get("AAIO_MERCHANT_ID", "")),
        "aaioSecret1": db.get_setting("aaio_secret_1", os.environ.get("AAIO_SECRET_1", "")),
        "aaioSecret2": db.get_setting("aaio_secret_2", os.environ.get("AAIO_SECRET_2", "")),
        "sbpEnabled": db.get_setting("sbp_enabled", "true") == "true",
        "sbpPhone": db.get_setting("sbp_phone", ""),
        "sbpBank": db.get_setting("sbp_bank", "СБП"),
        "sbpRecipient": db.get_setting("sbp_recipient", "")
    }

@router.post("/admin/payment-settings")
async def save_admin_payment_settings(payload: PaymentSettingsUpdate, admin: Dict[str, Any] = Depends(require_admin)):
    if payload.cryptobotEnabled is not None:
        db.set_setting("cryptobot_enabled", "true" if payload.cryptobotEnabled else "false")
    if payload.cryptobotToken is not None:
        db.set_setting("cryptobot_token", payload.cryptobotToken.strip())
        
    if payload.starsEnabled is not None:
        db.set_setting("stars_enabled", "true" if payload.starsEnabled else "false")
    if payload.starsRate is not None:
        db.set_setting("stars_rate", str(payload.starsRate))
        
    if payload.aaioEnabled is not None:
        db.set_setting("aaio_enabled", "true" if payload.aaioEnabled else "false")
    if payload.aaioMerchantId is not None:
        db.set_setting("aaio_merchant_id", payload.aaioMerchantId.strip())
    if payload.aaioSecret1 is not None:
        db.set_setting("aaio_secret_1", payload.aaioSecret1.strip())
    if payload.aaioSecret2 is not None:
        db.set_setting("aaio_secret_2", payload.aaioSecret2.strip())
        
    if payload.sbpEnabled is not None:
        db.set_setting("sbp_enabled", "true" if payload.sbpEnabled else "false")
    if payload.sbpPhone is not None:
        db.set_setting("sbp_phone", payload.sbpPhone.strip())
    if payload.sbpBank is not None:
        db.set_setting("sbp_bank", payload.sbpBank.strip())
    if payload.sbpRecipient is not None:
        db.set_setting("sbp_recipient", payload.sbpRecipient.strip())

    return {"ok": True, "message": "Настройки сохранены"}

# вебхук CryptoBot
@router.post("/payments/cryptobot/webhook")
async def cryptobot_webhook(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("crypto-pay-api-signature", "")
    token = db.get_setting("cryptobot_token", os.environ.get("CRYPTOBOT_TOKEN", ""))
    
    if not token or not payments.verify_cryptobot_webhook(raw_body, sig, token):
        raise HTTPException(status_code=400, detail="Неверная или отсутствующая подпись CryptoBot")

    try:
        data = json.loads(raw_body.decode("utf-8"))
        update_type = data.get("update_type")
        payload = data.get("payload", {})

        if update_type == "invoice_paid":
            order_code = payload.get("payload")
            invoice_id = str(payload.get("invoice_id", ""))
            amount = payload.get("amount", "")
            asset = payload.get("asset", "")
            if order_code:
                notify_order_paid(order_code, f"CryptoBot ({amount} {asset})", invoice_id)
        return {"ok": True}
    except Exception as e:
        logger.error(f"ошибка cryptobot webhook: {e}")
        return {"ok": False, "error": str(e)}

# вебхук Aaio
@router.post("/payments/aaio/webhook")
async def aaio_webhook(request: Request):
    form_data = await request.form()
    merchant_id = str(form_data.get("merchant_id", ""))
    order_id = str(form_data.get("order_id", ""))
    amount = str(form_data.get("amount", ""))
    currency = str(form_data.get("currency", "RUB"))
    sign = str(form_data.get("sign", ""))

    s_2 = db.get_setting("aaio_secret_2", os.environ.get("AAIO_SECRET_2", ""))
    if not s_2 or not payments.verify_aaio_webhook(merchant_id, s_2, order_id, amount, currency, sign):
        raise HTTPException(status_code=400, detail="Неверная или отсутствующая подпись Aaio")

    try:
        notify_order_paid(order_id, f"Aaio СБП/Карты ({amount} ₽)")
        return "OK"
    except Exception as e:
        logger.error(f"ошибка aaio webhook: {e}")
        return "ERROR"

# --- ОБРАБОТКА ОПЛАТЫ И АВТОВЫДАЧА ТОВАРОВ ---
def notify_order_paid(order_code: str, payment_source: str, payment_id: Optional[str] = None):
    order = db.get_order(order_code)
    if not order:
        logger.warning(f"notify_order_paid: заказ {order_code} не найден")
        return

    # Защита от повторной обработки (идемпотентность вебхуков)
    if order.get("status") == "paid":
        logger.info(f"Заказ {order_code} уже оплачен, повторная выдача пропущена")
        return

    # меняем статус заказа
    db.mark_order_paid(order_code, payment_id)

    # списываем бонусы и учитываем промокод в момент успешной оплаты
    buyer_id = order.get("buyerId")
    bonus_used = int(order.get("bonusUsed") or 0)
    promo_code = str(order.get("promoCode") or "").strip().upper()
    
    if buyer_id and bonus_used > 0:
        db.deduct_referral_bonus(buyer_id, bonus_used)
        
    if promo_code:
        db.increment_promo_use(promo_code)

    # автовыдача ключей из пула склада
    delivered_keys = db.pop_keys_for_order(order_code, order.get("items", []))

    # начисление реферального бонуса пригласителю
    total_rub = int(order.get("totalRub") or 0)
    ref_percent = int(db.get_setting("ref_percent", "5"))

    if buyer_id:
        referrer_id = db.get_referrer_for_user(buyer_id)
        if referrer_id and total_rub > 0:
            reward = int(round(total_rub * (ref_percent / 100.0)))
            if reward > 0:
                db.add_referral_bonus(referrer_id, reward)
                if BOT_TOKEN:
                    try:
                        import telebot
                        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
                        tg_bot.send_message(
                            referrer_id,
                            f"🎁 <b>Вам начислен реферальный бонус!</b>\n\n"
                            f"💰 <b>+{reward} ₽</b> за покупку приглашенного друга\n"
                            f"Вы можете оплатить этими бонусами свой следующий заказ"
                        )
                    except Exception:
                        pass

    if not BOT_TOKEN:
        return

    try:
        import telebot
        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

        # форматируем ключи для выдачи с защитой от спецсимволов HTML
        keys_text = ""
        if delivered_keys:
            keys_text = "\n\n⚡ <b>ВАШИ КУПЛЕННЫЕ КЛЮЧИ / ДАННЫЕ:</b>\n"
            for dk in delivered_keys:
                p_name = html.escape(str(dk.get("productName", "")))
                keys_text += f"\n📦 <b>{p_name}:</b>\n"
                for k in dk.get("keys", []):
                    keys_text += f"<code>{html.escape(str(k))}</code>\n"

        # сообщение клиенту
        if buyer_id:
            try:
                buyer_msg = (
                    f"🎉 <b>Заказ #{html.escape(order_code)} успешно оплачен!</b>\n\n"
                    f"💳 <b>Способ:</b> {html.escape(payment_source)}\n"
                    f"💵 <b>Сумма:</b> {total_rub:,} ₽"
                    f"{keys_text}\n\n"
                    f"✨ Купленные ключи также сохранены в вашем приложении во вкладке «Мои покупки»"
                )
                tg_bot.send_message(buyer_id, buyer_msg)
            except Exception as e:
                logger.warning(f"не удалось отправить чек клиенту: {e}")

        # сообщение админам
        b_name = html.escape(str(order.get("buyerName") or "Клиент"))
        b_user = html.escape(str(order.get("buyerUsername") or f"ID: {buyer_id}"))
        admin_msg = (
            f"💰 <b>ПОЛУЧЕНА ОПЛАТА ПО ЗАКАЗУ #{html.escape(order_code)}</b>\n\n"
            f"👤 <b>Клиент:</b> {b_name} (@{b_user})\n"
            f"💵 <b>Сумма:</b> <code>{total_rub:,} ₽</code>\n"
            f"💳 <b>Способ:</b> {html.escape(payment_source)}\n"
            f"⚡ <b>Автовыдача:</b> {'Выдано ' + str(len(delivered_keys)) + ' поз.' if delivered_keys else 'Ручная выдача'}"
        )
        for adm in ADMIN_IDS:
            if adm.isdigit():
                try:
                    tg_bot.send_message(int(adm), admin_msg)
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"ошибка отправки уведомления об оплате: {e}")

# обработка вебхука бота (включая Stars и /start ref_...)
@router.post("/webhook")
async def telegram_webhook(request: Request):
    if not BOT_TOKEN:
        return {"ok": False, "error": "нет токена бота"}

    try:
        import telebot
        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
        update_json = await request.json()
        update = telebot.types.Update.de_json(update_json)

        # 1. Pre-checkout query для Stars
        if update.pre_checkout_query:
            tg_bot.answer_pre_checkout_query(update.pre_checkout_query.id, ok=True)
            return {"ok": True}

        # 2. Сообщения
        if update.message:
            msg = update.message
            
            # успешная оплата через Stars
            if msg.successful_payment:
                sp = msg.successful_payment
                order_code = sp.invoice_payload
                stars_count = sp.total_amount
                notify_order_paid(order_code, f"Telegram Stars ({stars_count} ⭐)")
                return {"ok": True}

            if msg.text and msg.text.startswith("/start"):
                # проверяем реферальный код
                referrer_id = None
                parts = msg.text.split()
                if len(parts) > 1 and parts[1].startswith("ref_"):
                    ref_str = parts[1].replace("ref_", "")
                    if ref_str.isdigit():
                        referrer_id = int(ref_str)

                # сохраняем пользователя
                db.register_bot_user(
                    user_id=msg.chat.id,
                    username=msg.from_user.username or "",
                    first_name=msg.from_user.first_name or "",
                    referrer_id=referrer_id
                )

                webapp_url = os.environ.get("WEBAPP_URL", "https://shopik234.vercel.app")
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("🎮 Открыть магазин", web_app=telebot.types.WebAppInfo(url=webapp_url)))
                tg_bot.send_message(
                    msg.chat.id,
                    "Нажмите кнопку ниже 👇",
                    reply_markup=markup
                )
            elif msg.reply_to_message:
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

# отправка чеков и уведомлений о новом заказе
def send_order_bot_notifications(order_data: Dict[str, Any], verified_items: List[Dict[str, Any]], payment_result: Dict[str, Any]):
    if not BOT_TOKEN:
        return

    try:
        import telebot
        from telebot import types
        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

        order_id = html.escape(str(order_data.get("orderId", "")))
        buyer_id = order_data.get("buyerId")
        buyer_name = html.escape(str(order_data.get("buyerName", "Клиент")))
        raw_username = str(order_data.get("buyerUsername", "") or "")
        buyer_username = f"@{html.escape(raw_username)}" if raw_username and not raw_username.startswith("ID:") else html.escape(raw_username)
        total_rub = int(order_data.get("totalRub", 0))
        total_count = int(order_data.get("totalCount", 0))
        pm_method = payment_result.get("method", "manual")
        discount_rub = int(order_data.get("discountRub", 0))
        bonus_used = int(order_data.get("bonusUsed", 0))

        if buyer_id:
            order_buyers_cache[order_id] = buyer_id

        items_text = ""
        for i, it in enumerate(verified_items, start=1):
            it_name = html.escape(str(it.get("name", "Товар")))
            it_qty = int(it.get("qty", 1))
            it_price = int(it.get("price", 0))
            it_subtotal = int(it.get("subtotal", 0))
            items_text += f"{i}. <b>{it_name}</b>: {it_qty} шт × {it_price:,} ₽ = <b>{it_subtotal:,} ₽</b>\n"

        pm_titles = {
            "cryptobot": "💎 CryptoBot (USDT / TON)",
            "stars": "⭐ Telegram Stars",
            "aaio": "💳 Карты РФ / СБП (Aaio)",
            "sbp": "📱 Прямой перевод СБП",
            "manual": "💬 Согласование с менеджером"
        }
        pm_title = html.escape(pm_titles.get(pm_method, str(pm_method)))

        extra_info = ""
        if discount_rub > 0:
            extra_info += f"🎟️ Скидка по промокоду: -{discount_rub:,} ₽\n"
        if bonus_used > 0:
            extra_info += f"🎁 Бонусы списаны: -{bonus_used:,} ₽\n"

        # чек покупателю
        if buyer_id:
            try:
                buyer_receipt = (
                    f"✅ <b>Заказ #{order_id} принят</b>\n\n"
                    f"📦 <b>Товары:</b>\n{items_text}\n"
                    f"{extra_info}"
                    f"💵 <b>Сумма к оплате:</b> <code>{total_rub:,} ₽</code>\n"
                    f"💳 <b>Выбранный способ:</b> {pm_title}\n\n"
                    f"⏳ Ожидайте подтверждения или перейдите к оплате в окне магазина"
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
            f"{extra_info}"
            f"💵 <b>Сумма к оплате:</b> <code>{total_rub:,} ₽</code>\n"
            f"💳 <b>Способ оплаты:</b> {pm_title}\n\n"
            f"💡 <i>Ответьте через Reply на это сообщение</i>"
        )

        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        done_btn = types.InlineKeyboardButton("✅ Выполнен", callback_data=f"done_{order_id}")
        paid_btn = types.InlineKeyboardButton("💰 Оплачен (Автовыдача)", callback_data=f"paid_{order_id}")
        admin_markup.add(paid_btn, done_btn)

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
    if not BOT_TOKEN:
        return

    try:
        import telebot
        from telebot import types
        tg_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

        @tg_bot.pre_checkout_query_handler(func=lambda query: True)
        def on_pre_checkout(pre_checkout_query):
            tg_bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

        @tg_bot.message_handler(content_types=['successful_payment'])
        def on_successful_payment(msg):
            sp = msg.successful_payment
            order_code = sp.invoice_payload
            notify_order_paid(order_code, f"Telegram Stars ({sp.total_amount} ⭐)")

        @tg_bot.message_handler(commands=['start'])
        def on_start(msg):
            referrer_id = None
            parts = msg.text.split()
            if len(parts) > 1 and parts[1].startswith("ref_"):
                ref_str = parts[1].replace("ref_", "")
                if ref_str.isdigit():
                    referrer_id = int(ref_str)

            db.register_bot_user(
                user_id=msg.chat.id,
                username=msg.from_user.username or "",
                first_name=msg.from_user.first_name or "",
                referrer_id=referrer_id
            )

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

        @tg_bot.callback_query_handler(func=lambda call: call.data.startswith("paid_"))
        def on_paid(call):
            order_id = call.data.replace("paid_", "")
            notify_order_paid(order_id, "Подтверждено админом вручную")
            tg_bot.answer_callback_query(call.id, "Заказ оплачен, ключи выданы")
            tg_bot.edit_message_text(
                call.message.text + "\n\n<b>💰 Статус: ОПЛАЧЕН (Ключи выданы)</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

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

# подключаем роутер
app.include_router(router)
app.include_router(router, prefix="/api")

# запускаем поллинг только если не на верселе
if not (os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")):
    threading.Thread(target=run_bot_listener, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
