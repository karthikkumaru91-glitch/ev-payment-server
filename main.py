import os
import hmac
import hashlib
import json

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import razorpay

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== READ FROM ENVIRONMENT — set these in Render's Environment tab ==========
RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
RAZORPAY_WEBHOOK_SECRET = os.environ["RAZORPAY_WEBHOOK_SECRET"]
DEVICE_SECRET = os.environ["DEVICE_SECRET"]  # must match the ESP32's DEVICE_SECRET exactly
# =====================================================================================

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

orders = {}

MAX_KWH_PER_SESSION = 50
MAX_HOURS_PER_SESSION = 24


def build_payload(order_id: str, mode: str, value: float) -> str:
    return f"{order_id}:{mode}:{value:.2f}"


def make_start_token(order_id: str, mode: str, value: float) -> str:
    payload = build_payload(order_id, mode, value)
    full = hmac.new(DEVICE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return full[:16]


@app.get("/")
def home():
    return {"status": "EV Charger Payment Server Running"}


@app.post("/create-order")
async def create_order(request: Request):
    data = await request.json()
    amount = data.get("amount")
    mode = data.get("mode")
    value = data.get("value")

    if not amount or amount < 1:
        raise HTTPException(status_code=400, detail="Invalid amount")
    if mode not in ("kwh", "hour"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    if not value or value <= 0:
        raise HTTPException(status_code=400, detail="Invalid value")
    if mode == "kwh" and value > MAX_KWH_PER_SESSION:
        raise HTTPException(status_code=400, detail="kWh value too large")
    if mode == "hour" and value > MAX_HOURS_PER_SESSION:
        raise HTTPException(status_code=400, detail="Hours value too large")

    amount_paise = int(round(amount * 100))

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "payment_capture": 1
    })

    orders[order["id"]] = {
        "amount": amount,
        "mode": mode,
        "value": value,
        "paid": False,
        "start_token": None,
    }

    return {
        "order_id": order["id"],
        "amount": amount_paise,
        "key_id": RAZORPAY_KEY_ID
    }


@app.post("/webhook")
async def razorpay_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")

    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not signature or not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(body)
    event = payload.get("event")

    if event == "payment.captured":
        order_id = payload["payload"]["payment"]["entity"]["order_id"]
        order = orders.get(order_id)

        if order and not order["paid"]:
            order["paid"] = True
            order["start_token"] = make_start_token(order_id, order["mode"], order["value"])
            print(f"Payment confirmed for order: {order_id}")

    return {"status": "ok"}


@app.get("/check-payment/{order_id}")
def check_payment(order_id: str):
    order = orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Unknown order")

    if not order["paid"]:
        try:
            payments = client.order.payments(order_id)
            captured = any(p["status"] == "captured" for p in payments["items"])
            if captured:
                order["paid"] = True
                order["start_token"] = make_start_token(order_id, order["mode"], order["value"])
        except Exception as e:
            print(f"check-payment fallback error: {e}")

    if not order["paid"]:
        return {"paid": False}

    return {
        "paid": True,
        "order_id": order_id,
        "mode": order["mode"],
        "value": order["value"],
        "startToken": order["start_token"],
    }
