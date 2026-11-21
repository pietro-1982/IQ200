"""Fonti online aperte e gratuite: WordPress Jobs, Reddit (community IT/business), Remotive."""
import datetime as dt
import html
from html.parser import HTMLParser
import json
import re
import urllib.request
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

USER_AGENT = "IQ200-LeadFinder/2.0 (ricerca-opportunita-b2b)"

PATTERNS = {
    "Odoo / ERP": r"\bodoo\b|\berp\b|\bgestionale\b|\bmagazzino\b|\bfatturazione\b",
    "CRM": r"\bcrm\b|\bsalesforce\b|\bhubspot\b|\bgestione clienti\b|\bpipedrive\b",
    "E-commerce": r"\bwoo\s?commerce\b|\bshopify\b|\bprestashop\b|\bmagento\b|\be[- ]?commerce\b|\bnegozio online\b",
    "Siti web": r"\bwordpress\b|\bsit[oi] web\b|\bweb\s?site\b|\bweb design\b|\bportale web\b|\blanding page\b",
    "Automazioni AI": r"\b(?:ai automation|automazion[ei]|intelligenza artificiale|chatbot|ai agent|rpa|n8n|make\.com|zapier)\b",
    "Marketing digitale": r"\b(?:seo|google ads|meta ads|facebook ads|digital marketing|social media|lead generation)\b",
}

ITALY = r"\b(?:italy|italia|italiano|italiana|milan|milano|rome|roma|turin|torino|naples|napoli|florence|firenze|bologna|genoa|genova|venice|venezia|palermo|bari|bergamo|brescia|padova|verona|modena|parma)\b"
ONLY_ABROAD = r"\b(?:u\.?s\.?a?\.?|united states|uk|united kingdom|canada|australia|india)[ -]+(?:based|residents?|only)\b|\bw2 only\b"
EMPLOYMENT = r"\b(?:full[ -]time (?:employment|employee|position|role)|permanent (?:employment|employee)|contratto a tempo (?:in)?determinato|assunzione diretta|ral )\b"
SELF_PROMO = r"^\[?\s*(?:for hire|offro|mi propongo|disponibile per|cerco lavoro)\b"


def compact(s):
    return " ".join(html.unescape(s or "").split())


def fetch_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read(2_500_000)


class Plain(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.parts = []
        self.feed(markup or "")

    def handle_data(self, data):
        self.parts.append(data)


def clean_html(markup):
    return compact(" ".join(Plain(markup).parts))


def classify_text(title, description, location="", force_italy=False):
    full = f"{title} {description}"
    if re.search(EMPLOYMENT, full, re.I) or re.search(SELF_PROMO, title, re.I):
        return None
    if force_italy or re.search(ITALY, f"{location} {full}", re.I):
        region = "Italia confermata"
    elif re.search(r"remote|worldwide|europe|emea", location, re.I) and not re.search(ONLY_ABROAD, full, re.I):
        region = "Remoto · Italia da verificare"
    else:
        return None

    matches = []
    for category, pattern in PATTERNS.items():
        t_hits = list(re.finditer(pattern, title, re.I))
        b_hits = list(re.finditer(pattern, description, re.I))
        terms = list(dict.fromkeys(m.group().lower() for m in t_hits + b_hits))
        if terms:
            score = 45 + 20 * bool(t_hits) + 5 * min(len(terms), 5)
            matches.append((score, category, terms))
    if not matches:
        return None
    matches.sort(key=lambda v: -v[0])
    return region, matches


class WPIndex(HTMLParser):
    def __init__(self):
        super().__init__()
        self.card = None
        self.part = None
        self.parts = []
        self.jobs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "job-card" in attrs.get("class", "").split():
            p = urlsplit(attrs.get("href", ""))
            if p.scheme == "https" and p.netloc == "jobs.wordpress.net":
                self.card = "https://jobs.wordpress.net" + p.path.rstrip("/") + "/"
                self.parts = []
        if self.card and tag == "span":
            self.part = []

    def handle_data(self, data):
        if self.part is not None:
            self.part.append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self.part is not None:
            self.parts.append(compact("".join(self.part)))
            self.part = None
        if tag == "a" and self.card:
            if any(re.fullmatch(r"[^\w]*Project", p, re.I) for p in self.parts):
                loc = next((p[1:].strip() for p in self.parts if p.startswith(("🌎", "📍"))), "")
                self.jobs[self.card] = loc
            self.card = None


def fetch_wp_jobs():
    feed_xml = fetch_bytes("https://jobs.wordpress.net/feed/")
    items = ET.fromstring(feed_xml).findall("./channel/item")
    index = WPIndex()
    index.feed(fetch_bytes("https://jobs.wordpress.net/").decode("utf-8", errors="replace"))
    out = []
    for item in items:
        raw_link = (item.findtext("link") or "").strip().rstrip("/") + "/"
        if raw_link not in index.jobs:
            continue
        title = compact(item.findtext("title"))
        raw_desc = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or item.findtext("description") or ""
        desc = clean_html(raw_desc)
        res = classify_text(title, desc, index.jobs[raw_link])
        if not res:
            continue
        try:
            pub_date = parsedate_to_datetime(item.findtext("pubDate") or "").date()
        except (ValueError, TypeError):
            continue
        if (dt.date.today() - pub_date).days > 30:
            continue
        region, hits = res
        out.append({
            "id": raw_link,
            "url": raw_link,
            "titolo": title,
            "ente": "Privato / Azienda (WP Jobs)",
            "fonte": "WordPress Jobs",
            "canale": "online",
            "area": region,
            "citta": index.jobs[raw_link] or "Remoto",
            "servizio": hits[0][1],
            "altri": [x[1] for x in hits[1:]],
            "punteggio": hits[0][0],
            "motivo": "Incarico Project · " + ", ".join(hits[0][2][:4]),
            "estratto": desc[:400],
            "valore": "",
            "tipo": "Incarico a progetto",
            "stato": "aperta",
            "pubblicazione": pub_date.isoformat(),
            "scadenza": None,
        })
    return len(items), out


REDDIT_QUERIES = [
    ("ItaliaStartups", "gestionale OR crm OR sito web OR ecommerce OR preventivo OR sviluppatore", True),
    ("commercialisti", "gestionale OR fatturazione OR software OR automazione", True),
    ("Odoo", "italy OR italia OR italiano OR freelancer OR consultant", False),
    ("forhire", "[Hiring] (odoo OR n8n OR shopify OR wordpress OR automation)", False),
]


def fetch_reddit():
    out = []
    read_count = 0
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=21)
    for sub, query, is_ita in REDDIT_QUERIES:
        url = f"https://www.reddit.com/r/{sub}/search.json?q={quote(query)}&restrict_sr=1&sort=new&t=month&limit=25"
        try:
            data = json.loads(fetch_bytes(url).decode("utf-8"))
        except Exception:
            continue
        posts = data.get("data", {}).get("children", [])
        read_count += len(posts)
        for p in posts:
            d = p.get("data", {})
            created = dt.datetime.fromtimestamp(d.get("created_utc", 0), tz=dt.timezone.utc)
            if created < cutoff:
                continue
            title = compact(d.get("title", ""))
            body = compact(d.get("selftext", ""))
            permalink = "https://www.reddit.com" + d.get("permalink", "")
            res = classify_text(title, body, "Italia" if is_ita else "Remote", force_italy=is_ita)
            if not res:
                continue
            region, hits = res
            out.append({
                "id": permalink,
                "url": permalink,
                "titolo": title,
                "ente": f"Utente r/{sub}",
                "fonte": f"Reddit r/{sub}",
                "canale": "online",
                "area": region,
                "citta": "Italia" if is_ita else "Remoto",
                "servizio": hits[0][1],
                "altri": [x[1] for x in hits[1:]],
                "punteggio": hits[0][0],
                "motivo": "Post community · " + ", ".join(hits[0][2][:4]),
                "estratto": body[:400] or title,
                "valore": "",
                "tipo": "Richiesta da privato/PMI",
                "stato": "aperta",
                "pubblicazione": created.date().isoformat(),
                "scadenza": None,
            })
    return read_count, out


def fetch_remotive():
    url = "https://remotive.com/api/remote-jobs?limit=50"
    data = json.loads(fetch_bytes(url).decode("utf-8"))
    jobs = data.get("jobs", [])
    out = []
    cutoff = dt.date.today() - dt.timedelta(days=21)
    for j in jobs:
        j_type = (j.get("job_type") or "").lower()
        if j_type not in ("freelance", "contract", "other", ""):
            continue
        title = compact(j.get("title", ""))
        desc = clean_html(j.get("description", ""))
        loc = compact(j.get("candidate_required_location", ""))
        res = classify_text(title, desc, loc)
        if not res:
            continue
        try:
            pub_date = dt.date.fromisoformat((j.get("publication_date") or "")[:10])
        except ValueError:
            continue
        if pub_date < cutoff:
            continue
        region, hits = res
        job_url = j.get("url", "")
        out.append({
            "id": job_url,
            "url": job_url,
            "titolo": title,
            "ente": compact(j.get("company_name", "Azienda (Remotive)")),
            "fonte": "Remotive",
            "canale": "online",
            "area": region,
            "citta": loc or "Remoto",
            "servizio": hits[0][1],
            "altri": [x[1] for x in hits[1:]],
            "punteggio": hits[0][0],
            "motivo": "Contratto/Freelance · " + ", ".join(hits[0][2][:4]),
            "estratto": desc[:400],
            "valore": compact(j.get("salary", ""))[:40],
            "tipo": "Contratto / Freelance",
            "stato": "aperta",
            "pubblicazione": pub_date.isoformat(),
            "scadenza": None,
        })
    return len(jobs), out


def fetch_all_online():
    all_projects = []
    logs = []
    seen_urls = set()

    for name, fn in [
        ("WordPress Jobs", fetch_wp_jobs),
        ("Reddit Community", fetch_reddit),
        ("Remotive", fetch_remotive),
    ]:
        try:
            read, items = fn()
            added = 0
            for it in items:
                if it["url"] not in seen_urls:
                    seen_urls.add(it["url"])
                    all_projects.append(it)
                    added += 1
            logs.append({"fonte": name, "esito": "ok", "avvisi_letti": read, "classificate": added})
        except Exception as e:
            logs.append({"fonte": name, "esito": "ERRORE", "dettaglio": str(e)})

    all_projects.sort(key=lambda x: (x["area"] != "Italia confermata", -x["punteggio"], x["pubblicazione"]))
    return logs, all_projects