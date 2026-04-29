"""
RailApp – Telegram Userbot
Läuft 24/7 auf Railway.app
Parst Meldungen von @bernd_betriebslage_bot im Format:
  📌 Betriebsstelle
  📅 von - bis
  📢 Kategorie - Unterkategorie
  Beschreibung
  ---
  Region1, Region2, Region3
"""

import os
import json
import asyncio
import httpx
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ─────────────────────────────────────────────
#  KONFIGURATION
# ─────────────────────────────────────────────
API_ID       = int(os.environ.get("TELEGRAM_API_ID",   "33767078"))
API_HASH     = os.environ.get("TELEGRAM_API_HASH",     "8b79f1137437f1c1b9e35e7c79c5b135")
SESSION_STR  = os.environ.get("TELEGRAM_SESSION",      "")
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
#  PARSER
# ─────────────────────────────────────────────
def parse_bernd_message(text: str) -> dict:
    """
    Parst exaktes Format von @bernd_betriebslage_bot:

    📌 Düsseldorf Abstellbahnhof (KDA)
    📅 29.04.2026 17:32 - 29.04.2026 23:59
    📢 Behördliche Maßnahme - Sonstige Behördliche Maßnahmen
    Zurückhalten von Zügen für SPNV
    ---
    Niederrhein-Netz, Rund um Düsseldorf, Köln - Düren - Aachen
    """
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]

    result = {
        'bst':             '',
        'von_datum':       None,
        'bis_datum':       None,
        'kategorie':       '',
        'unterkategorie':  '',
        'beschreibung':    '',
        'regionen':        [],
        'region':          'Allgemein',
        'prioritaet':      'normal',
        'status':          'aktiv',
    }

    beschr_lines = []
    nach_strich  = False

    for line in lines:
        if line.startswith('📌'):
            result['bst'] = line.replace('📌', '').strip()

        elif line.startswith('📅'):
            datum_str = line.replace('📅', '').strip()
            teile = datum_str.split(' - ')
            if len(teile) >= 1:
                result['von_datum'] = parse_de_dt(teile[0].strip())
            if len(teile) >= 2:
                result['bis_datum'] = parse_de_dt(teile[1].strip())

        elif line.startswith('📢'):
            kat = line.replace('📢', '').strip()
            if ' - ' in kat:
                p = kat.split(' - ', 1)
                result['kategorie']    = p[0].strip()
                result['unterkategorie']= p[1].strip()
            else:
                result['kategorie'] = kat

        elif line == '---':
            nach_strich = True

        elif nach_strich:
            regs = [r.strip() for r in line.split(',') if r.strip()]
            result['regionen'] = regs
            result['region']   = regs[0] if regs else 'Allgemein'

        elif not any(line.startswith(e) for e in ['📌','📅','📢']):
            beschr_lines.append(line)

    result['beschreibung'] = ' '.join(beschr_lines).strip()

    # Priorität ableiten
    kat = result['kategorie'].lower()
    if any(x in kat for x in ['unfall','notfall','sperrung','vollsperrung','person']):
        result['prioritaet'] = 'hoch'
    elif any(x in kat for x in ['verspätung','störung','defekt','behördlich','signal']):
        result['prioritaet'] = 'mittel'

    return result


def parse_de_dt(s: str):
    """29.04.2026 17:32 → ISO-String"""
    for fmt in ['%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S', '%d.%m.%Y']:
        try:
            return datetime.strptime(s.strip(), fmt).isoformat()
        except ValueError:
            continue
    return None


# ─────────────────────────────────────────────
#  SUPABASE
# ─────────────────────────────────────────────
async def sb_post(table: str, payload: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(url, headers=SB_HEADERS, content=json.dumps(payload))
        if r.status_code not in (200, 201):
            print(f"⚠ {table}: {r.status_code} – {r.text[:150]}")
        return r.status_code in (200, 201)


# ─────────────────────────────────────────────
#  HAUPTPROGRAMM
# ─────────────────────────────────────────────
async def main():
    print("=" * 55)
    print("  RailApp Telegram Userbot")
    print(f"  Start: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("=" * 55)

    session = StringSession(SESSION_STR) \
        if SESSION_STR and SESSION_STR not in ('', 'placeholder') \
        else StringSession()

    async with TelegramClient(session, API_ID, API_HASH) as client:

        if not SESSION_STR or SESSION_STR == 'placeholder':
            print("\n⚠️  Session-String für Railway:\n")
            print(client.session.save())
            print()

        try:
            bernd_bot = await client.get_entity(BOT_USERNAME)
            bernd_id  = bernd_bot.id
            print(f"✅ Verbunden mit @{BOT_USERNAME} (ID: {bernd_id})")
        except Exception as e:
            print(f"⚠ Bot nicht gefunden: {e}")
            bernd_id = None

        @client.on(events.NewMessage)
        async def handler(event):
            try:
                text = (event.message.text or "").strip()
                if len(text) < 10:
                    return

                sender    = await event.get_sender()
                sender_id = getattr(sender, 'id', 0)
                s_name    = getattr(sender, 'username', '') or getattr(sender, 'first_name', '') or ''

                from_bernd = (bernd_id and sender_id == bernd_id) or \
                             BOT_USERNAME.lower() in s_name.lower()
                if not from_bernd:
                    return

                ts = datetime.now().strftime('%H:%M:%S')
                print(f"\n📨 Neue Meldung [{ts}]:")
                print(text[:400])
                print("─" * 40)

                parsed = parse_bernd_message(text)
                regionen = parsed['regionen'] if parsed['regionen'] else ['Allgemein']

                print(f"  📌 {parsed['bst']}")
                print(f"  📅 {parsed['von_datum']} → {parsed['bis_datum']}")
                print(f"  📢 {parsed['kategorie']} / {parsed['unterkategorie']}")
                print(f"  📝 {parsed['beschreibung'][:60]}")
                print(f"  🗺  {', '.join(regionen)}")

                # 1. sqf_nachrichten (Rohdaten)
                await sb_post('sqf_nachrichten', {
                    "telegram_msg_id": event.message.id,
                    "chat_id":    str(event.chat_id),
                    "sender_name": s_name,
                    "region":     parsed['region'],
                    "strecke":    parsed['bst'],
                    "ursache":    parsed['kategorie'],
                    "massnahme":  parsed['unterkategorie'],
                    "status":     parsed['status'],
                    "prioritaet": parsed['prioritaet'],
                    "volltext":   text[:2000],
                    "empfangen_am": datetime.utcnow().isoformat(),
                })

                # 2. bl_meldungen – je Region einen Eintrag
                titel = parsed['bst'] or parsed['kategorie'] or \
                        parsed['beschreibung'][:80] or 'Störungsmeldung'

                for region in regionen:
                    await sb_post('bl_meldungen', {
                        "typ":          "telegram",
                        "region":       region,
                        "titel":        titel,
                        "volltext":     text[:2000],
                        "strecke":      parsed['bst'],
                        "beschreibung": parsed['beschreibung'],
                        "prioritaet":   parsed['prioritaet'],
                        "status":       parsed['status'],
                        "telegram_id":  event.message.id,
                        "created_at":   datetime.utcnow().isoformat(),
                    })

                print(f"✅ Gespeichert – {len(regionen)} Region(en)")

            except Exception as e:
                import traceback
                print(f"⚠ Handler-Fehler: {e}")
                traceback.print_exc()

        print(f"\n🟢 Läuft – warte auf Meldungen von @{BOT_USERNAME}…\n")
        await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
