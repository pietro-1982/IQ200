"""IQ200 LeadFinder - motore automatico: TED + fonti online aperte + Gemini AI + Telegram."""
import datetime
import json
import os
import urllib.request
from online import fetch_all_online
from ai_classifier import refine_with_ai
from telegram_alert import notify_top_leads

API = "https://api.ted.europa.eu/v3/notices/search"

SERVIZI = {
    "Odoo / ERP": {
        "cpv": ["48440000", "48443000", "48450000", "72212440", "48441000"],
        "kw": ["erp", "gestionale", "odoo", "contabilit", "magazzino"],
    },
    "CRM": {
        "cpv": ["48445000", "72212445"],
        "kw": ["crm", "customer relationship", "gestione clienti"],
    },
    "Siti web": {
        "cpv": ["72413000", "72415000", "72414000", "72420000"],
        "kw": ["sito web", "siti web", "portale web", "website", "web site", "wordpress"],
    },
    "Automazioni AI": {
        "cpv": ["72212224"],
        "kw": ["intelligenza artificiale", "artificial intelligence", "automazione dei processi", "chatbot", "machine learning", "rpa"],
    },
    "E-commerce": {
        "cpv": ["72212461", "48000000"],
        "kw": ["e-commerce", "ecommerce", "commercio elettronico", "vendita online", "piattaforma di vendita"],
    },
    "Marketing digitale": {
        "cpv": ["79340000", "79341000", "79342000", "79342200", "79413000"],
        "kw": ["marketing", "pubblicit", "social media", "comunicazione digitale", "campagna"],
    },
}

CPV_ALL = sorted({c for s in SERVIZI.values() for c in s["cpv"]} | {"72000000", "72200000", "72400000", "72260000"})
FIELDS = [
    "publication-number", "notice-title", "buyer-name", "publication-date",
    "deadline-receipt-tender-date-lot", "classification-cpv", "notice-type",
    "buyer-city", "estimated-value-lot", "description-lot",
]


def txt(v):
    if isinstance(v, dict):
        for k in ("ita", "eng"):
            if k in v:
                return " ".join(v[k]) if isinstance(v[k], list) else str(v[k])
        return " ".join(" ".join(x) if isinstance(x, list) else str(x) for x in v.values())
    if isinstance(v, list):
        return " ".join(map(str, v))
    return str(v or "")


def fetch_ted(days=30):
    since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    q = (
        f"buyer-country=ITA AND classification-cpv IN ({' '.join(CPV_ALL)}) "
        f"AND publication-date>={since} AND notice-type IN (cn-standard cn-social pin-only)"
    )
    out = []
    page = 1
    while page <= 10:
        body = json.dumps({"query": q, "fields": FIELDS, "limit": 100, "page": page}).encode()
        r = urllib.request.Request(API, body, {"Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(r, timeout=60))
        n = d.get("notices", [])
        out += n
        if len(n) < 100:
            break
        page += 1
    return out


def classify_ted(n):
    title = txt(n.get("notice-title"))
    desc = txt(n.get("description-lot"))[:1500]
    full = (" " + title + " " + desc + " ").lower()
    cpvs = set(n.get("classification-cpv", []))

    if any(w in title.lower() for w in ["computer portatili", "hardware", "stampanti", "arredi", "pc desktop", "fotocopiatrici"]):
        return None

    hits = []
    for s, r in SERVIZI.items():
        score = 0
        why = []
        if cpvs & set(r["cpv"]) and r["cpv"] != ["72212461", "48000000"]:
            score += 50
            why.append("CPV " + ",".join(sorted(cpvs & set(r["cpv"]))))
        kws = [k.strip() for k in r["kw"] if k in full]
        if kws:
            score += 25 + 10 * min(len(kws), 3)
            why.append("parole: " + ", ".join(kws))
        if score:
            hits.append((score, s, "; ".join(why)))

    if not hits:
        hits = [(20, "IT generico (da valutare)", "solo CPV informatico generico")]
    hits.sort(reverse=True)

    dl = [x[:10] for x in n.get("deadline-receipt-tender-date-lot", []) if x]
    dl = min(dl) if dl else None
    today = datetime.date.today().isoformat()
    stato = "scaduta" if dl and dl < today else "aperta" if dl else "scadenza non indicata"
    pn = n["publication-number"]

    return {
        "id": pn,
        "titolo": title,
        "ente": txt(n.get("buyer-name")),
        "citta": txt(n.get("buyer-city")),
        "area": "Italia confermata",
        "canale": "ted",
        "pubblicazione": txt(n.get("publication-date"))[:10],
        "scadenza": dl,
        "stato": stato,
        "tipo": "Avviso preliminare" if n.get("notice-type") == "pin-only" else "Bando di gara",
        "servizio": hits[0][1],
        "altri": [h[1] for h in hits[1:]],
        "punteggio": min(100, hits[0][0]),
        "motivo": hits[0][2],
        "estratto": desc[:400],
        "valore": txt(n.get("estimated-value-lot"))[:40],
        "url": f"https://ted.europa.eu/it/notice/-/detail/{pn}",
        "fonte": "TED – appalti pubblici UE",
    }


def main():
    log = {
        "eseguito": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "fonti": [],
    }
    try:
        raw = fetch_ted()
        log["fonti"].append({"fonte": "TED", "esito": "ok", "avvisi_letti": len(raw)})
    except Exception as e:
        raw = []
        log["fonti"].append({"fonte": "TED", "esito": "ERRORE", "dettaglio": str(e)})

    seen = {}
    for n in raw:
        c = classify_ted(n)
        k = (c["titolo"], c["ente"]) if c else None
        if c and k not in seen:
            seen[k] = c

    ted_items = list(seen.values())
    online_logs, online_items = fetch_all_online()
    log["fonti"].extend(online_logs)

    all_items = ted_items + online_items

    # Classificazione AI con Gemini (se GEMINI_API_KEY configurata)
    all_items, ai_log = refine_with_ai(all_items)
    log["ai"] = ai_log

    # Ordinamento finale
    all_items.sort(
        key=lambda x: (
            x.get("stato") == "scaduta",
            x.get("area") != "Italia confermata",
            -x.get("punteggio", 0),
            x.get("scadenza") or "9999",
        )
    )

    log["classificate"] = len(all_items)

    # Notifica Telegram per i lead migliori (se TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID configurati)
    log["telegram"] = notify_top_leads(all_items)

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json.tmp", "w", encoding="utf-8") as stream:
        json.dump({"log": log, "opportunita": all_items}, stream, ensure_ascii=False, indent=1)
    os.replace("docs/data.json.tmp", "docs/data.json")
    print(json.dumps(log, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()