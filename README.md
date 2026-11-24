# Eldorado.gg Discord Order Notifier 📱🔔

Automatically monitors your Eldorado.gg seller account and pings your phone via Discord whenever someone buys an item!

---

### Features
* **Instant Phone Push Notification**: Pings your Discord user account (`<@671311332548673536>`) so your phone buzzes/rings.
* **Order Alerts**: Shows item title, price, quantity, buyer username, order status, and direct link.
* **Boosting Request Alerts**: Automatically notifies you the moment a new boosting request is posted for games you subscribed to!
* **Auto-Token Refresh**: Automatically refreshes Eldorado's 15-minute token in the background so it runs indefinitely without interruption.
* **No Spam / Duplicate Filtering**: Remembers previously processed items in `seen_orders.json` and `seen_boosts.json`.

---

### How to Run

#### Option 1: Double-click (Easiest)
Simply double-click **`start_notifier.bat`** in this folder!

#### Option 2: Command Line
Open PowerShell or Command Prompt in this folder and run:
```bash
py eldorado_notifier.py
```

To send a test order to your Discord to see how it looks:
```bash
py eldorado_notifier.py --test
```

---

### Mobile Notification Setup
To ensure your phone buzzes or rings:
1. Open the Discord app on your phone.
2. In the server where your webhook channel is located:
   - Long-press or tap the channel settings > **Notifications** > select **All Messages**.
3. Because the bot mentions your user ID directly, you will get notified even if the server is muted!
