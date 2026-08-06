"""
Configurazione una-tantum del webhook Telegram.

Richiede le env TELEGRAM_BOT_TOKEN (obbligatoria), BASE_URL e TELEGRAM_WEBHOOK_SECRET.
In locale legge il .env; in produzione usa le env di Render.

    # imposta il webhook su <BASE_URL>/telegram/webhook
    python3 telegram_setup.py set
    # mostra lo stato attuale
    python3 telegram_setup.py info
    # rimuove il webhook (bot in pausa)
    python3 telegram_setup.py delete
"""
import sys

from config import BASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET
import telegram_bot as tb


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN non impostata (env o .env).")
        return
    azione = sys.argv[1] if len(sys.argv) > 1 else "info"

    if azione == "set":
        if not BASE_URL:
            print("❌ BASE_URL non impostata (es. https://gestionale-...onrender.com).")
            return
        url = f"{BASE_URL}/telegram/webhook"
        r = tb.set_webhook(url, TELEGRAM_WEBHOOK_SECRET)
        print("setWebhook →", r)
        print("setMyCommands →", tb.set_commands())
        print("Webhook:", url, "| secret:", "sì" if TELEGRAM_WEBHOOK_SECRET else "NO (consigliato impostarlo)")
    elif azione == "delete":
        print("deleteWebhook →", tb.delete_webhook())
    else:  # info
        print("getWebhookInfo →", tb._api("getWebhookInfo", {}))
        print("getMe →", tb._api("getMe", {}))


if __name__ == "__main__":
    main()
