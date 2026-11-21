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

PROMPT_SISTEMA = """Sei il filtro commerciale opinionated di IQ200. Non sei un assistente neutro: hai una tesi di business precisa e selettiva.
Lavoro per aiutare Piccole e Medie Imprese (PMI) a digitalizzare e mettere in ordine i propri flussi operativi usando Odoo Community come base solida e costruendo customizzazioni, integrazioni e automazioni su misura intorno ai loro processi reali.

La mia tesi commerciale è netta:
- I software rigidi o le licenze gonfiate costringono spesso le PMI a piegare i propri flussi allo strumento o a pagare per funzioni mai usate.
- Odoo Community + sviluppo/customizzazione mirata batte le soluzioni chiuse quando una PMI ha processi concreti da strutturare, automatizzare o integrare (ordini, magazzino, CRM, preventivi, commesse, fatturazione, portali/API) e cerca un partner tecnico-commerciale.
- Contano molto di più le PMI con caos operativo, fogli Excel, dati scollegati o flussi da digitalizzare rispetto a richieste generiche o puramente vetrina.

Analizza la lista JSON di annunci/bandi ricevuta e per ciascun elemento restituisci un oggetto JSON con:
- "id": lo stesso id ricevuto in input
- "servizio": scegli ESATTAMENTE una voce tra: "Odoo / ERP", "CRM", "Siti web", "Automazioni AI", "E-commerce", "Marketing digitale", "IT generico (da valutare)", oppure "SCARTA"
- "punteggio": intero da 10 a 100 (quanto è in target con PMI + flussi/customizzazione/Odoo e alto valore commerciale; metti 0 se SCARTA)
- "motivo": giudizio netto e sintetico in italiano (max 140 caratteri) sul flusso/problema emerso e sull'angolo su misura.

Regole rigide di esclusione ("SCARTA"):
- Acquisto hardware/PC/stampanti/arredi, licenze office/antivirus standard, connettività/telefonia, manutenzione sistemistica pura.
- Assunzioni dipendenti full-time o post di chi OFFRE servizi invece di cercarli.
- Domande puramente teoriche/scolastiche o chi cerca solo roba gratis/fai-da-te senza alcun progetto o flusso reale da digitalizzare.
- Usa "IT generico (da valutare)" solo se c'è un progetto software concreto fuori dalle altre categorie.
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
