"""Invio alert su Telegram per le opportunità migliori di IQ200 LeadFinder."""
import json
import os
import urllib.parse
import urllib.request


def send_telegram_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "false",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise ValueError(f"Risposta Telegram non ok: {data}")


def notify_top_leads(items, max_alerts=8, min_score=60):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return {"attivo": False, "inviati": 0, "motivo": "TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID mancanti"}

    candidates = [
        it for it in items
        if it.get("stato") != "scaduta"
        and it.get("servizio") != "IT generico (da valutare)"
        and (it.get("punteggio", 0) >= min_score or it.get("canale") == "online")
    ][:max_alerts]

    sent = 0
    errors = 0
    for it in candidates:
        msg = (
            f"🎯 IQ200 LeadFinder — {it.get('servizio', 'Opportunità')} (Pertinenza {it.get('punteggio', 0)})\n"
            f"📌 {it.get('titolo', '')}\n"
            f"🏢 {it.get('ente', '')} ({it.get('fonte', '')})\n"
            f"📍 {it.get('area', '')} {('· ' + it.get('citta')) if it.get('citta') else ''}\n"
        )
        if it.get("scadenza"):
            msg += f"⏳ Scadenza: {it['scadenza']}\n"
        if it.get("motivo"):
            msg += f"💡 {it['motivo']}\n"
        if it.get("url"):
            msg += f"🔗 {it['url']}"

        try:
            send_telegram_message(token, chat_id, msg[:4000])
            sent += 1
        except Exception as e:
            errors += 1
            print(f"[Telegram] Errore invio: {e}")

    return {"attivo": True, "inviati": sent, "errori": errors}