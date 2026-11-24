import os
import sys
import time
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
import requests

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Eldorado Notifier Bot is running 24/7!")

    def log_message(self, format, *args):
        pass  # Suppress HTTP ping logs to keep console clean

def start_health_server():
    """Starts a lightweight web server for cloud platforms (Render, Koyeb, etc.)."""
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"[*] Cloud health check server listening on port {port}")
    except Exception as e:
        print(f"[!] Note: Cloud health server not started ({e})")

CONFIG_FILE = "config.json"
SEEN_ORDERS_FILE = "seen_orders.json"

AUTH_URL = "https://www.eldorado.gg/api/authentication/seller/token"
ORDERS_URL = "https://www.eldorado.gg/api/orders/me/seller/orders?pageSize=20"

def load_config():
    # 1. Check environment variables first (ideal for cloud hosting)
    env_client_id = os.environ.get("ELDORADO_CLIENT_ID") or os.environ.get("CLIENT_ID")
    env_secret = os.environ.get("ELDORADO_CLIENT_SECRET") or os.environ.get("CLIENT_SECRET")
    env_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    
    if env_client_id and env_secret and env_webhook:
        return {
            "client_id": env_client_id,
            "client_secret": env_secret,
            "discord_webhook_url": env_webhook,
            "discord_user_id": os.environ.get("DISCORD_USER_ID", ""),
            "check_interval_seconds": int(os.environ.get("CHECK_INTERVAL_SECONDS", 30))
        }

    # 2. Fall back to config.json
    if not os.path.exists(CONFIG_FILE):
        print(f"[!] Error: Configuration file '{CONFIG_FILE}' not found and cloud environment variables not set.")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_seen_orders():
    if os.path.exists(SEEN_ORDERS_FILE):
        try:
            with open(SEEN_ORDERS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return None  # None indicates first run

def save_seen_orders(seen_set):
    try:
        with open(SEEN_ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_set), f, indent=2)
    except Exception as e:
        print(f"[!] Warning: Could not save seen orders: {e}")

class EldoradoNotifier:
    def __init__(self, config):
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")
        self.webhook_url = config.get("discord_webhook_url")
        self.user_id = str(config.get("discord_user_id", "")).strip()
        self.check_interval = int(config.get("check_interval_seconds", 30))
        
        self.access_token = None
        self.token_expires_at = 0

    def get_token(self):
        """Requests a new 15-minute access token."""
        payload = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        res = requests.post(AUTH_URL, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            self.access_token = data.get("accessToken")
            # Refresh every 13 minutes (Eldorado tokens expire in 15 mins)
            self.token_expires_at = time.time() + (13 * 60)
            return self.access_token
        else:
            print(f"[!] Authentication failed: HTTP {res.status_code} - {res.text}")
            return None

    def ensure_authenticated(self):
        if not self.access_token or time.time() >= self.token_expires_at:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Authenticating with Eldorado API...")
            return self.get_token() is not None
        return True

    def fetch_orders(self):
        """Fetches the latest orders for the seller."""
        if not self.ensure_authenticated():
            return None

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        try:
            res = requests.get(ORDERS_URL, headers=headers, timeout=15)
            if res.status_code == 200:
                return res.json().get("results", [])
            elif res.status_code == 401:
                # Force token refresh on next attempt
                self.access_token = None
                print("[!] Access token expired or invalid. Will refresh on next check.")
            else:
                print(f"[!] Failed to fetch orders: HTTP {res.status_code} - {res.text[:150]}")
        except Exception as e:
            print(f"[!] Network error fetching orders: {e}")
        return None

    def send_discord_notification(self, order):
        """Sends a rich Discord notification with a mobile ping."""
        order_id = order.get("id", "N/A")
        buyer = order.get("buyerUsername", "Unknown")
        
        # Extract pricing
        total_price = order.get("totalPrice", {})
        amount = total_price.get("amount", "0.00")
        currency = total_price.get("currency", "USD")
        price_str = f"${amount:.2f} {currency}" if isinstance(amount, (int, float)) else f"{amount} {currency}"
        
        quantity = order.get("purchaseQuantity", 1)
        
        # Extract offer details
        offer_details = order.get("orderOfferDetails") or {}
        offer_title = offer_details.get("offerTitle")
        category_title = offer_details.get("gameCategoryTitle", "In-Game Goods")
        item_title = offer_title if offer_title else category_title
        
        # Order state
        state_obj = order.get("state") or {}
        current_state = state_obj.get("state", "Paid")
        
        order_link = f"https://www.eldorado.gg/dashboard/orders"
        
        mention = f"<@{self.user_id}> " if self.user_id else ""
        
        embed = {
            "title": "🛍️ New Eldorado Order Received!",
            "url": order_link,
            "color": 5763719,  # Vibrant Green
            "fields": [
                {
                    "name": "📦 Item / Service",
                    "value": str(item_title),
                    "inline": False
                },
                {
                    "name": "💰 Price",
                    "value": f"**{price_str}**",
                    "inline": True
                },
                {
                    "name": "🔢 Quantity",
                    "value": str(quantity),
                    "inline": True
                },
                {
                    "name": "👤 Buyer",
                    "value": f"`{buyer}`",
                    "inline": True
                },
                {
                    "name": "⚡ Status",
                    "value": f"`{current_state}`",
                    "inline": True
                },
                {
                    "name": "🆔 Order ID",
                    "value": f"`{order_id}`",
                    "inline": False
                }
            ],
            "footer": {
                "text": "Eldorado Order Monitor • Mobile Alert"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        payload = {
            "content": f"{mention}🚨 **NEW ORDER ALERT! Someone just bought an item!**",
            "embeds": [embed]
        }
        
        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            if res.status_code in (200, 204):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Discord notification sent for order {order_id}")
            else:
                print(f"[!] Failed to send Discord webhook: HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[!] Error sending Discord notification: {e}")

    def send_startup_message(self, tracked_orders_count):
        """Sends a one-time message confirming the bot is active."""
        mention = f"<@{self.user_id}> " if self.user_id else ""
        embed = {
            "title": "🟢 Eldorado Notifier Connected & Active",
            "description": (
                f"Your order monitor is now running and polling Eldorado every **{self.check_interval}s**.\n\n"
                f"• **Initial orders tracked:** {tracked_orders_count}\n"
                f"• **Notifications:** Instant mobile push notification when a new order arrives."
            ),
            "color": 3447003, # Blue
            "footer": {"text": "Eldorado Seller Bot"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        payload = {
            "content": f"{mention}Bot successfully started!",
            "embeds": [embed]
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=10)
        except Exception:
            pass

def main():
    start_health_server()
    config = load_config()
    notifier = EldoradoNotifier(config)
    
    # Check if testing mode
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("[*] Sending test notification to Discord...")
        test_order = {
            "id": "test-order-12345-sample",
            "buyerUsername": "TestBuyer",
            "totalPrice": {"amount": 25.00, "currency": "USD"},
            "purchaseQuantity": 1,
            "orderOfferDetails": {
                "offerTitle": "500k In-Game Coins / Items (Test Item)",
                "gameCategoryTitle": "Roblox Items"
            },
            "state": {"state": "Paid"}
        }
        notifier.send_discord_notification(test_order)
        print("[*] Test complete! Check your Discord.")
        return

    print("==================================================")
    print("      🚀 Eldorado.gg Discord Order Notifier       ")
    print("==================================================")
    print(f"[*] Checking orders every {notifier.check_interval} seconds.")
    print("[*] Press Ctrl+C anytime to stop.\n")

    seen_orders = load_seen_orders()

    # Initial orders check
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Initializing orders from Eldorado...")
    orders = notifier.fetch_orders()
    
    if orders is not None:
        if seen_orders is None:
            # First time running: mark existing past orders so we don't spam notifications
            seen_orders = {str(o.get("id")) for o in orders if o.get("id")}
            save_seen_orders(seen_orders)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Initialized! Saved {len(seen_orders)} existing past orders.")
            notifier.send_startup_message(len(seen_orders))
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Loaded {len(seen_orders)} previously seen orders.")
    else:
        if seen_orders is None:
            seen_orders = set()

    while True:
        try:
            orders = notifier.fetch_orders()
            if orders:
                for order in orders:
                    order_id = str(order.get("id"))
                    if order_id and order_id not in seen_orders:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 NEW ORDER DETECTED: {order_id} from {order.get('buyerUsername')}")
                        notifier.send_discord_notification(order)
                        seen_orders.add(order_id)
                        save_seen_orders(seen_orders)
        except Exception as e:
            print(f"[!] Unexpected error in main loop: {e}")

        time.sleep(notifier.check_interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Monitor stopped by user.")
