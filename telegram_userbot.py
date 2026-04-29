"""
RailApp – Telegram Userbot
Läuft 24/7 auf Railway.app
Empfängt alle Nachrichten von @bernd_betriebslage_bot
und speichert sie in Supabase.
"""

import os
import re
import json
import asyncio
import httpx
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ─────────────────────────────────────────────
#  KONFIGURATION (aus Environment Variables)
# ─────────────────────────────────────────────
API_ID       = int(os.environ.get("TELEGRAM_API_ID",   "33767078"))
API_HASH     = os.environ.get("TELEGRAM_API_HASH",     "8b79f1137437f1c1b9e35e7c79c5b135")
SESSION_STR  = os.environ.get("TELEGRAM_SESSION",      "")  # wird beim ersten Start generiert
BOT_USERNAME = os.environ.get("BERND_BOT_USERNAME",    "bernd_betriebslage_bot")

SUPABASE_URL = os.environ.get("SUPABASE_URL",  "https://ehmacbdsjtcnlvezdfpj.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY",  "sb_publishable_C6RTBCRGu0Czi6q0z1P1NQ_3UxOeZHf")

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal"
}

# ─────────────────────────────────────────────
#  NACHRICHT PARSEN
# ─────────────────────────────────────────────
def parse_stoerung(text: str) -> dict:
    """
    Extrahiert strukturierte Daten aus einer Störungsmeldung.
    Typisches Format:
    🔴 Region: Bayern
    Zug: ICE 123
    Strecke: München – Nürnberg
    Verspätung: 45 Min
    Ursache: Technischer Defekt
    """
    result = {
        "region":      extract(text, r"Region[:\s]+([^\n]+)"),
        "zug":         extract(text, r"Zug[:\s]+([^\n]+)"),
        "zugnummer":   extract(text, r"\b(ICE|IC|EC|RE|RB|S)\s*(\d+)"),
        "strecke":     extract(text, r"Strecke[:\s]+([^\n]+)"),
        "verspaetung": extract_min(text),
        "ursache":     extract(text, r"Ursache[:\s]+([^\n]+)"),
        "massnahme":   extract(text, r"Ma[ßs]nahme[:\s]+([^\n]+)"),
        "status":      detect_status(text),
        "prioritaet":  detect_priority(text),
    }
    return result

def extract(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return m.group(1).strip() if len(m.groups()) >= 1 else m.group(0).strip()
    return ""

def extract_min(text: str) -> int:
    """Extrahiert Verspätungsminuten aus Text."""
    patterns = [
        r"(\d+)\s*Min(?:uten?)?",
        r"Versp[äa]tung[:\s]+(\d+)",
        r"ca\.\s*(\d+)\s*Min",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except:
                pass
    return 0

def detect_status(text: str) -> str:
    text_lower = text.lower()
    if any(x in text_lower for x in ["beendet", "aufgehoben", "normalbetrieb", "✅"]):
        return "beendet"
    if any(x in text_lower for x in ["update", "aktualisierung", "nachtrag"]):
        return "update"
    if any(x in text_lower for x in ["neu", "new", "störung", "🔴", "⚠️"]):
        return "neu"
    return "neu"

def detect_priority(text: str) -> str:
    if "🔴" in text or "überregional" in text.lower():
        return "hoch"
    if "⚠️" in text or "regional" in text.lower():
        return "mittel"
    return "normal"

def detect_region(text: str, sender_name: str) -> str:
    """Region aus Nachrichtentext oder Absendernamen."""
    regionen = [
        "Bayern", "Baden-Württemberg", "NRW", "Hessen", "Niedersachsen",
        "Hamburg", "Berlin", "Brandenburg", "Sachsen", "Thüringen",
        "Rheinland-Pfalz", "Saarland", "Bremen", "Schleswig-Holstein",
        "Mecklenburg", "Sachsen-Anhalt", "Nord", "Süd", "West", "Ost",
        "Frankfurt", "München", "Stuttgart", "Köln", "Hamburg",
    ]
    combined = text + " " + sender_name
    for r in regionen:
        if r.lower() in combined.lower():
            return r
    return "Allgemein"

# ─────────────────────────────────────────────
#  SUPABASE SPEICHERN
# ─────────────────────────────────────────────
async def save_to_supabase(message_data: dict):
    url = f"{SUPABASE_URL}/rest/v1/sqf_nachrichten"
    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=SB_HEADERS,
                              content=json.dumps(message_data))
        if r.status_code in (200, 201):
            print(f"✅ Gespeichert: {message_data.get('region','?')} – {message_data.get('zugnummer','?')}")
        else:
            print(f"⚠ Supabase Fehler: {r.status_code} {r.text[:200]}")

# ─────────────────────────────────────────────
#  HAUPTPROGRAMM
# ─────────────────────────────────────────────
async def main():
    print("=" * 50)
    print("  RailApp Telegram Userbot")
    print(f"  Start: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("=" * 50)

    # Session: aus ENV laden oder neu erstellen
    session = StringSession(SESSION_STR) if SESSION_STR else StringSession()

    async with TelegramClient(session, API_ID, API_HASH) as client:

        # Beim ersten Start: Session-String ausgeben zum Speichern
        if not SESSION_STR:
            print("\n⚠️  WICHTIG: Kopiere diesen Session-String als")
            print("   TELEGRAM_SESSION Environment Variable in Railway:\n")
            print(client.session.save())
            print("\n")

        # Bot-Entity laden
        try:
            bernd_bot = await client.get_entity(BOT_USERNAME)
            print(f"✅ Verbunden mit @{BOT_USERNAME}")
        except Exception as e:
            print(f"⚠ Bot nicht gefunden: {e}")
            bernd_bot = None

        # Event Handler: Alle neuen Nachrichten
        @client.on(events.NewMessage)
        async def handler(event):
            try:
                # Nur Nachrichten vom Bernd-Bot oder Weiterleitungen davon
                sender = await event.get_sender()
                sender_name = getattr(sender, 'username', '') or getattr(sender, 'first_name', '') or ''

                is_from_bernd = (
                    BOT_USERNAME.lower() in sender_name.lower() or
                    (bernd_bot and event.sender_id == bernd_bot.id) or
                    (event.message.fwd_from and bernd_bot and
                     getattr(event.message.fwd_from.from_id, 'user_id', None) == bernd_bot.id)
                )

                # Auch weitergeleitet Nachrichten akzeptieren
                if not is_from_bernd and not event.message.fwd_from:
                    return

                text = event.message.text or ""
                if len(text.strip()) < 5:
                    return

                print(f"\n📨 Neue Nachricht von {sender_name}:")
                print(text[:200])

                # Parsen
                parsed   = parse_stoerung(text)
                region   = parsed["region"] or detect_region(text, sender_name)

                # Supabase Payload
                payload = {
                    "telegram_msg_id": event.message.id,
                    "chat_id":         str(event.chat_id),
                    "sender_name":     sender_name,
                    "region":          region,
                    "zug":             parsed["zug"],
                    "zugnummer":       parsed["zugnummer"],
                    "strecke":         parsed["strecke"],
                    "verspaetung_min": parsed["verspaetung"],
                    "ursache":         parsed["ursache"],
                    "massnahme":       parsed["massnahme"],
                    "status":          parsed["status"],
                    "prioritaet":      parsed["prioritaet"],
                    "volltext":        text[:2000],
                    "empfangen_am":    datetime.utcnow().isoformat(),
                }

                await save_to_supabase(payload)

            except Exception as e:
                print(f"⚠ Handler-Fehler: {e}")

        print(f"\n🟢 Userbot läuft – warte auf Nachrichten von @{BOT_USERNAME}…\n")
        await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
