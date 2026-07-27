from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import razorpay
import hmac
import hashlib
import json

app = FastAPI()

# Allow webpage to talk to this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== REPLACE THESE ==========
RAZORPAY_KEY_ID = "rzp_test_TIV9QzBESbwUEt"
RAZORPAY_KEY_SECRET = "HOoQtiT2X0GuVAgmBHlvp9G2"
WEBHOOK_SECRET = "evcharger2026"   # We will set this later
# ==================================

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Store successful payments temporarily
paid_orders = set()

@app.get("/")
def home():
    return {"status": "EV Charger Payment Server Running"}

@app.post("/create-order")
async def create_order(request: Request):
    data = await request.json()
    amount = data.get("amount")  # amount in rupees

    if not amount or amount < 1:
        raise HTTPException(status_code=400, detail="Invalid amount")

    amount_paise = int(amount * 100)  # Razorpay uses paise

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "payment_capture": 1
    })

    return {
        "order_id": order["id"],
        "amount": amount_paise,
        "key_id": RAZORPAY_KEY_ID
    }

@app.post("/webhook")
async def razorpay_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")

    # Verify webhook signature
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if signature != expected_signature:
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(body)
    event = payload.get("event")

    if event == "payment.captured":
        order_id = payload["payload"]["payment"]["entity"]["order_id"]
        paid_orders.add(order_id)
        print(f"Payment successful for order: {order_id}")

    return {"status": "ok"}

@app.get("/check-payment/{order_id}")
def check_payment(order_id: str):
    if order_id in paid_orders:
        return {"paid": True}
    return {"paid": False}
