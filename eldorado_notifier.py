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
    """Starts a lightweight web server for cloud platforms (Render, Koyeb, Railway, etc.)."""
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
SEEN_BOOSTS_FILE = "seen_boosts.json"

AUTH_URL = "https://www.eldorado.gg/api/authentication/seller/token"
ORDERS_URL = "https://www.eldorado.gg/api/orders/me/seller/orders?pageSize=20"
BOOSTING_URL = "https://www.eldorado.gg/api/boostingOffers/me/boostingRequests/received?pageSize=20"

def get_env(*keys):
    """Fetches an environment variable matching any of the given keys, 
    automatically handling quotes, case-insensitivity, and extra spaces."""
    normalized = {
        k.strip('"\' ').lower(): v.strip('"\' ')
        for k, v in os.environ.items()
    }
    for key in keys:
        target = key.strip('"\' ').lower()
        if target in normalized and normalized[target]:
            return normalized[target]
    return None

def load_config():
    # 1. Check environment variables first (ideal for cloud hosting)
    env_client_id = get_env("client_id", "eldorado_client_id")
    env_secret = get_env("client_secret", "eldorado_client_secret")
    env_webhook = get_env("discord_webhook_url", "webhook_url")

    if env_client_id and env_secret and env_webhook:
        return {
            "client_id": env_client_id,
            "client_secret": env_secret,
            "discord_webhook_url": env_webhook,
            "discord_user_id": get_env("discord_user_id", "user_id") or "",
            "check_interval_seconds": int(get_env("check_interval_seconds", "interval") or 30)
        }

    # 2. Fall back to config.json
    if not os.path.exists(CONFIG_FILE):
        print(f"[!] Error: Configuration file '{CONFIG_FILE}' not found and cloud environment variables not set.")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_seen_items(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return None  # None indicates first run

def save_seen_items(filename, seen_set):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(list(seen_set), f, indent=2)
    except Exception as e:
        print(f"[!] Warning: Could not save seen items to {filename}: {e}")

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

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

    def fetch_orders(self):
        """Fetches the latest orders for the seller."""
        if not self.ensure_authenticated():
            return None

        try:
            res = requests.get(ORDERS_URL, headers=self._get_headers(), timeout=15)
            if res.status_code == 200:
                return res.json().get("results", [])
            elif res.status_code == 401:
                self.access_token = None
                print("[!] Access token expired. Will refresh on next check.")
            else:
                print(f"[!] Failed to fetch orders: HTTP {res.status_code} - {res.text[:150]}")
        except Exception as e:
            print(f"[!] Network error fetching orders: {e}")
        return None

    def fetch_boosting_requests(self):
        """Fetches subscribed boosting requests."""
        if not self.ensure_authenticated():
            return None

        try:
            res = requests.get(BOOSTING_URL, headers=self._get_headers(), timeout=15)
            if res.status_code == 200:
                return res.json().get("results", [])
            elif res.status_code == 401:
                self.access_token = None
            else:
                print(f"[!] Failed to fetch boosting requests: HTTP {res.status_code}")
        except Exception as e:
            print(f"[!] Network error fetching boosting requests: {e}")
        return None

    def send_discord_order_notification(self, order):
        """Sends a rich Discord notification for a new order."""
        order_id = order.get("id", "N/A")
        buyer = order.get("buyerUsername", "Unknown")
        
        total_price = order.get("totalPrice", {})
        amount = total_price.get("amount", "0.00")
        currency = total_price.get("currency", "USD")
        price_str = f"${amount:.2f} {currency}" if isinstance(amount, (int, float)) else f"{amount} {currency}"
        
        quantity = order.get("purchaseQuantity", 1)
        offer_details = order.get("orderOfferDetails") or {}
        offer_title = offer_details.get("offerTitle")
        category_title = offer_details.get("gameCategoryTitle", "In-Game Goods")
        item_title = offer_title if offer_title else category_title
        
        state_obj = order.get("state") or {}
        current_state = state_obj.get("state", "Paid")
        
        order_link = "https://www.eldorado.gg/dashboard/orders"
        mention = f"<@{self.user_id}> " if self.user_id else ""
        
        embed = {
            "title": "🛍️ New Eldorado Order Received!",
            "url": order_link,
            "color": 5763719,  # Green
            "fields": [
                {"name": "📦 Item / Service", "value": str(item_title), "inline": False},
                {"name": "💰 Price", "value": f"**{price_str}**", "inline": True},
                {"name": "🔢 Quantity", "value": str(quantity), "inline": True},
                {"name": "👤 Buyer", "value": f"`{buyer}`", "inline": True},
                {"name": "⚡ Status", "value": f"`{current_state}`", "inline": True},
                {"name": "🆔 Order ID", "value": f"`{order_id}`", "inline": False}
            ],
            "footer": {"text": "Eldorado Order Monitor • Mobile Alert"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        payload = {
            "content": f"{mention}🚨 **NEW ORDER! Someone just bought an item!**",
            "embeds": [embed]
        }
        
        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            if res.status_code in (200, 204):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Discord order alert sent: {order_id}")
            else:
                print(f"[!] Failed to send Discord webhook: HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[!] Error sending Discord order notification: {e}")

    def send_discord_boosting_notification(self, req):
        """Sends a rich Discord notification for a new subscribed boosting request."""
        req_id = req.get("id", "N/A")
        buyer = req.get("buyerUsername", "Unknown")
        category = req.get("boostingCategoryTitle", "Custom Request")
        req_link = f"https://www.eldorado.gg/boosting-request/{req_id}"
        
        mention = f"<@{self.user_id}> " if self.user_id else ""
        
        embed = {
            "title": "🚀 New Boosting Request Posted!",
            "url": req_link,
            "color": 10181046,  # Purple
            "description": f"A buyer posted a new boosting request in **{category}** that matches your subscriptions!",
            "fields": [
                {"name": "👤 Buyer", "value": f"`{buyer}`", "inline": True},
                {"name": "📂 Category", "value": str(category), "inline": True},
                {"name": "🔗 Link", "value": f"[Open Boosting Request]({req_link})", "inline": False}
            ],
            "footer": {"text": "Eldorado Boosting Monitor • Mobile Alert"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        payload = {
            "content": f"{mention}⚡ **NEW BOOSTING REQUEST!** Be the first to place an offer!",
            "embeds": [embed]
        }
        
        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            if res.status_code in (200, 204):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Discord boosting alert sent: {req_id}")
            else:
                print(f"[!] Failed to send boosting alert: HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[!] Error sending boosting notification: {e}")

    def send_startup_message(self, tracked_orders_count, tracked_boosts_count):
        """Sends a one-time message confirming the bot is active."""
        mention = f"<@{self.user_id}> " if self.user_id else ""
        embed = {
            "title": "🟢 Eldorado Monitor Connected & Active",
            "description": (
                f"Your monitor is now running 24/7 on the cloud and checking Eldorado every **{self.check_interval}s**.\n\n"
                f"• **Active Monitoring:** 🛍️ New Orders + 🚀 Subscribed Boosting Requests\n"
                f"• **Initial orders tracked:** {tracked_orders_count}\n"
                f"• **Initial boosting requests tracked:** {tracked_boosts_count}"
            ),
            "color": 3447003, # Blue
            "footer": {"text": "Eldorado 24/7 Cloud Bot"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        payload = {
            "content": f"{mention}Bot successfully started in Cloud!",
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
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            print("[*] Sending test order notification to Discord...")
            test_order = {
                "id": "test-order-sample",
                "buyerUsername": "TestBuyer",
                "totalPrice": {"amount": 25.00, "currency": "USD"},
                "purchaseQuantity": 1,
                "orderOfferDetails": {
                    "offerTitle": "500k In-Game Coins / Items (Test Item)",
                    "gameCategoryTitle": "Roblox Items"
                },
                "state": {"state": "Paid"}
            }
            notifier.send_discord_order_notification(test_order)
            print("[*] Order test complete! Check your Discord.")
            return
        elif sys.argv[1] == "--test-boost":
            print("[*] Sending test boosting notification to Discord...")
            test_boost = {
                "id": "test-boost-sample",
                "buyerUsername": "GamerBuyer99",
                "boostingCategoryTitle": "Custom Raid / Leveling Request"
            }
            notifier.send_discord_boosting_notification(test_boost)
            print("[*] Boosting test complete! Check your Discord.")
            return

    print("==================================================")
    print("   🚀 Eldorado.gg Orders & Boosting Discord Bot   ")
    print("==================================================")
    print(f"[*] Checking orders & boosting requests every {notifier.check_interval} seconds.")
    print("[*] Press Ctrl+C anytime to stop.\n")

    seen_orders = load_seen_items(SEEN_ORDERS_FILE)
    seen_boosts = load_seen_items(SEEN_BOOSTS_FILE)

    # Initial checks
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Initializing orders and boosting from Eldorado...")
    orders = notifier.fetch_orders()
    boosts = notifier.fetch_boosting_requests()
    
    is_first_run = (seen_orders is None or seen_boosts is None)
    
    if seen_orders is None:
        seen_orders = {str(o.get("id")) for o in (orders or []) if o.get("id")}
        save_seen_items(SEEN_ORDERS_FILE, seen_orders)

    if seen_boosts is None:
        seen_boosts = {str(b.get("id")) for b in (boosts or []) if b.get("id")}
        save_seen_items(SEEN_BOOSTS_FILE, seen_boosts)

    if is_first_run:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Initialized! Saved {len(seen_orders)} orders and {len(seen_boosts)} boosting requests.")
        notifier.send_startup_message(len(seen_orders), len(seen_boosts))
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Loaded {len(seen_orders)} orders and {len(seen_boosts)} boosting requests.")

    while True:
        try:
            # 1. Check Orders
            current_orders = notifier.fetch_orders()
            if current_orders:
                for order in current_orders:
                    order_id = str(order.get("id"))
                    if order_id and order_id not in seen_orders:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 NEW ORDER DETECTED: {order_id} from {order.get('buyerUsername')}")
                        notifier.send_discord_order_notification(order)
                        seen_orders.add(order_id)
                        save_seen_items(SEEN_ORDERS_FILE, seen_orders)

            # 2. Check Subscribed Boosting Requests
            current_boosts = notifier.fetch_boosting_requests()
            if current_boosts:
                for req in current_boosts:
                    req_id = str(req.get("id"))
                    if req_id and req_id not in seen_boosts:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 NEW BOOSTING REQUEST DETECTED: {req_id} from {req.get('buyerUsername')}")
                        notifier.send_discord_boosting_notification(req)
                        seen_boosts.add(req_id)
                        save_seen_items(SEEN_BOOSTS_FILE, seen_boosts)

        except Exception as e:
            print(f"[!] Unexpected error in main loop: {e}")

        time.sleep(notifier.check_interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Monitor stopped by user.")
