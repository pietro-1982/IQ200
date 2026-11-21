"""Classificatore semantico tramite Google Gemini API (zero dipendenze esterne)."""
import json
import os
import time
import urllib.error
import urllib.request

GEMINI_MODEL = "gemini-3.5-flash-lite"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

CATEGORIE_AMMESSE = [
    "Odoo / ERP",
    "CRM",
    "Siti web",
    "Automazioni AI",
    "E-commerce",
    "Marketing digitale",
    "IT generico (da valutare)",
    "SCARTA",
]

PROMPT_SISTEMA = """Sei un analista commerciale senior per una web & software agency italiana che vende:
1. Odoo / ERP (gestionali, magazzino, contabilità, fatturazione, PMI)
2. CRM (gestione clienti, HubSpot, Salesforce, pipeline vendite)
3. Siti web (realizzazione/restyling siti web, portali, WordPress, UX/UI)
4. Automazioni AI (intelligenza artificiale, chatbot, agenti AI, n8n, Make, RPA, automazione processi)
5. E-commerce (Shopify, WooCommerce, PrestaShop, Magento, vendita online)
6. Marketing digitale (SEO, Google Ads, Meta Ads, social media, lead generation)

Analizza la lista JSON di annunci/bandi ricevuta e per ciascun elemento restituisci un oggetto JSON con:
- "id": lo stesso id ricevuto in input
- "servizio": scegli ESATTAMENTE una voce tra: "Odoo / ERP", "CRM", "Siti web", "Automazioni AI", "E-commerce", "Marketing digitale", "IT generico (da valutare)", oppure "SCARTA"
- "punteggio": intero da 10 a 100 (quanto è in target e ad alto valore commerciale; metti 0 se SCARTA)
- "motivo": spiegazione sintetica in italiano (max 140 caratteri) del bisogno reale del cliente o perché è in target.

Regole rigide:
- Usa "SCARTA" per: acquisto hardware/PC/stampanti, licenze office/antivirus standard, connettività/telefonia, manutenzione sistemistica pura, assunzioni dipendenti full-time, o post di persone che OFFRONO servizi invece di cercarli.
- Usa "IT generico (da valutare)" solo se è un progetto software reale ma non rientra nelle prime 6 categorie.
- Rispondi SOLO con un array JSON valido, senza markdown o testo aggiuntivo."""


def _call_gemini(batch, api_key):
    payload = {
        "systemInstruction": {"parts": [{"text": PROMPT_SISTEMA}]},
        "contents": [{"parts": [{"text": json.dumps(batch, ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        f"{API_URL}?key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def refine_with_ai(items):
    """Raffina con Gemini gli annunci online e i bandi TED ambigui/generici."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return items, {"attiva": False, "motivo": "GEMINI_API_KEY non configurata"}

    to_analyze = [
        it for it in items
        if it.get("canale") == "online"
        or it.get("servizio") == "IT generico (da valutare)"
        or it.get("punteggio", 0) < 75
    ]

    results_map = {}
    errors = 0
    batch_size = 15

    for i in range(0, len(to_analyze), batch_size):
        chunk = to_analyze[i : i + batch_size]
        compact_chunk = [
            {
                "id": it["id"],
                "canale": it.get("canale"),
                "titolo": it.get("titolo", "")[:200],
                "ente": it.get("ente", "")[:100],
                "estratto": it.get("estratto", "")[:500],
            }
            for it in chunk
        ]
        try:
            ai_out = _call_gemini(compact_chunk, api_key)
            for row in ai_out:
                if isinstance(row, dict) and row.get("id") and row.get("servizio") in CATEGORIE_AMMESSE:
                    results_map[row["id"]] = row
        except (urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as e:
            errors += 1
            print(f"[AI] Errore batch {i}: {e}")
        if i + batch_size < len(to_analyze):
            time.sleep(2)

    refined = []
    scartati = 0
    for it in items:
        ai_res = results_map.get(it["id"])
        if ai_res:
            if ai_res["servizio"] == "SCARTA":
                scartati += 1
                continue
            it["servizio"] = ai_res["servizio"]
            it["punteggio"] = max(10, min(100, int(ai_res.get("punteggio", it["punteggio"]))))
            if ai_res.get("motivo"):
                it["motivo"] = "AI · " + ai_res["motivo"]
        refined.append(it)

    stats = {
        "attiva": True,
        "modello": GEMINI_MODEL,
        "analizzati": len(to_analyze),
        "riclassificati": len(results_map),
        "scartati": scartati,
        "errori_batch": errors,
    }
    return refined, stats