"""
Kenya Scholarship & Opportunity Bot — Upgraded Edition
- Kenyan time (EAT = UTC+3)
- Minimum 15 direct application links guaranteed
- All links go directly to application/RSVP pages
- Categories: Scholarships, Fellowships, Internships, Grants
"""

import os
import json
import logging
import requests
import schedule
import time
import threading
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SEND_TIME          = os.getenv("SEND_TIME", "09:00")   # Kenyan time (EAT)
MAX_OPPS           = int(os.getenv("MAX_OPPS", "15"))
ADMIN_PASSWORD     = os.getenv("ADMIN_PASSWORD", "scholar2024")
PORT               = int(os.getenv("PORT", "5000"))

EAT                = ZoneInfo("Africa/Nairobi")   # East Africa Time = UTC+3

SUBSCRIBERS_FILE   = "subscribers.json"
SENT_IDS_FILE      = "sent_ids.json"
LAST_RUN_FILE      = "last_run.json"
TELEGRAM_API       = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
HEADERS            = {"User-Agent": "Mozilla/5.0 (compatible; ScholarshipBot/1.0)"}

MAIN_BUTTONS = {
    "inline_keyboard": [
        [
            {"text": "🎓 Scholarships", "callback_data": "cat_scholarship"},
            {"text": "🌍 Fellowships",  "callback_data": "cat_fellowship"},
        ],
        [
            {"text": "💼 Internships",  "callback_data": "cat_internship"},
            {"text": "💰 Grants",       "callback_data": "cat_grant"},
        ],
        [{"text": "🔥 All Opportunities", "callback_data": "cat_all"}]
    ]
}

app = Flask(__name__)


# ─── Storage ─────────────────────────────────────────────────────────────────

def load_subscribers():
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE) as f:
            return json.load(f)
    return {}

def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subs, f, indent=2)

def load_sent_ids():
    if os.path.exists(SENT_IDS_FILE):
        with open(SENT_IDS_FILE) as f:
            return set(json.load(f))
    return set()

def save_sent_ids(ids):
    with open(SENT_IDS_FILE, "w") as f:
        json.dump(list(ids), f)

def now_eat():
    """Current time in Kenyan timezone."""
    return datetime.now(EAT)

def load_last_run():
    if os.path.exists(LAST_RUN_FILE):
        with open(LAST_RUN_FILE) as f:
            return json.load(f).get("last_sent_day")
    return None

def save_last_run(day_str):
    with open(LAST_RUN_FILE, "w") as f:
        json.dump({"last_sent_day": day_str}, f)


# ─── Telegram Helpers ────────────────────────────────────────────────────────

def send_message(chat_id, text, parse_mode="HTML", reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
        return resp.ok
    except Exception as ex:
        log.error(f"Telegram error to {chat_id}: {ex}")
        return False

def answer_callback(callback_query_id, text=None):
    try:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload, timeout=10)
    except Exception:
        pass

def set_webhook(url):
    resp = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": url})
    log.info(f"Webhook: {resp.json()}")


# ══════════════════════════════════════════════════════════════════════════════
#  CURATED DIRECT APPLICATION LINKS (Always Legit, Always Direct)
# ══════════════════════════════════════════════════════════════════════════════

def get_curated_opportunities():
    """
    Hand-picked, verified opportunities with DIRECT application links.
    All open to Kenyan/African students. Updated regularly.
    """
    return [
        # ── SCHOLARSHIPS ─────────────────────────────────────────────────────
        {
            "id": "cur_1", "category": "scholarship",
            "title": "Mastercard Foundation Scholars Program — Full Scholarship (Tuition + Living)",
            "deadline": "Varies by university — check link",
            "url": "https://mastercardfdn.org/all/scholars/becoming-a-scholar/",
            "source": "Mastercard Foundation"
        },
        {
            "id": "cur_2", "category": "scholarship",
            "title": "Chevening Scholarship 2025/26 — Full UK Government Funding",
            "deadline": "November 2025",
            "url": "https://www.chevening.org/apply/",
            "source": "UK Government"
        },
        {
            "id": "cur_3", "category": "scholarship",
            "title": "DAAD Scholarships — Study in Germany (Masters & PhD)",
            "deadline": "October annually",
            "url": "https://www.daad.de/en/study-and-research-in-germany/scholarships/daad-scholarships/",
            "source": "DAAD Germany"
        },
        {
            "id": "cur_4", "category": "scholarship",
            "title": "Commonwealth Scholarship — UK Masters & PhD for Kenyans",
            "deadline": "December annually",
            "url": "https://cscuk.fcdo.gov.uk/apply/",
            "source": "Commonwealth"
        },
        {
            "id": "cur_5", "category": "scholarship",
            "title": "Aga Khan Foundation International Scholarship",
            "deadline": "March annually",
            "url": "https://www.akdn.org/our-agencies/aga-khan-foundation/international-scholarship-programme/how-apply",
            "source": "Aga Khan Foundation"
        },
        {
            "id": "cur_6", "category": "scholarship",
            "title": "OFID Scholarship Award — $20,000 for African Students",
            "deadline": "June annually",
            "url": "https://ofid.org/what-we-do/people/scholarship-program/",
            "source": "OFID"
        },
        {
            "id": "cur_7", "category": "scholarship",
            "title": "Australia Awards Scholarships — Open to Kenyans",
            "deadline": "April annually",
            "url": "https://www.australiaawardsfellowships.dfat.gov.au/apply",
            "source": "Australia Government"
        },
        {
            "id": "cur_8", "category": "scholarship",
            "title": "Korean Government Scholarship (KGSP) — Full Funding",
            "deadline": "February annually",
            "url": "https://www.studyinkorea.go.kr/en/sub/gks/allnew_gks_gov.do",
            "source": "Korean Government"
        },
        {
            "id": "cur_9", "category": "scholarship",
            "title": "Japanese Government (MEXT) Scholarship — Full Funding",
            "deadline": "May annually",
            "url": "https://www.studyinjapan.go.jp/en/smap-stopj-applications-mext.html",
            "source": "Japan Government"
        },
        {
            "id": "cur_10", "category": "scholarship",
            "title": "Erasmus Mundus Scholarships — Study in Europe (Fully Funded)",
            "deadline": "January annually",
            "url": "https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en",
            "source": "European Union"
        },

        # ── FELLOWSHIPS ──────────────────────────────────────────────────────
        {
            "id": "cur_11", "category": "fellowship",
            "title": "Mandela Washington Fellowship for Young African Leaders — Apply Now",
            "deadline": "November annually",
            "url": "https://yali.state.gov/mwf/",
            "source": "US State Department"
        },
        {
            "id": "cur_12", "category": "fellowship",
            "title": "Obama Foundation Africa Leaders Program — Application",
            "deadline": "Rolling — apply now",
            "url": "https://www.obama.org/programs/leaders/africa/",
            "source": "Obama Foundation"
        },
        {
            "id": "cur_13", "category": "fellowship",
            "title": "African Leadership Academy Fellowship — Direct Application",
            "deadline": "Rolling",
            "url": "https://www.africanleadershipacademy.org/admissions/how-to-apply/",
            "source": "ALA"
        },
        {
            "id": "cur_14", "category": "fellowship",
            "title": "Aspen New Voices Fellowship — African Thought Leaders",
            "deadline": "Rolling applications",
            "url": "https://www.aspeninstitute.org/programs/new-voices/apply/",
            "source": "Aspen Institute"
        },
        {
            "id": "cur_15", "category": "fellowship",
            "title": "Acumen East Africa Fellows Program",
            "deadline": "See link",
            "url": "https://acumen.org/fellowships/east-africa-fellowship/",
            "source": "Acumen"
        },
        {
            "id": "cur_16", "category": "fellowship",
            "title": "Hubert H. Humphrey Fellowship — US Exchange Program",
            "deadline": "See link",
            "url": "https://exchanges.state.gov/non-us/program/hubert-h-humphrey-fellowship-program",
            "source": "US Exchange Programs"
        },
        {
            "id": "cur_17", "category": "fellowship",
            "title": "German Chancellor Fellowship — Alexander von Humboldt Foundation",
            "deadline": "March annually",
            "url": "https://www.humboldt-foundation.de/en/apply/sponsorship-programmes/german-chancellor-fellowship",
            "source": "Humboldt Foundation"
        },

        # ── INTERNSHIPS ──────────────────────────────────────────────────────
        {
            "id": "cur_18", "category": "internship",
            "title": "United Nations Internship Programme — Apply Directly",
            "deadline": "Rolling — open now",
            "url": "https://careers.un.org/lbw/home.aspx?viewtype=ip",
            "source": "United Nations"
        },
        {
            "id": "cur_19", "category": "internship",
            "title": "World Bank Junior Professional Associates — Direct Application",
            "deadline": "October annually",
            "url": "https://www.worldbank.org/en/about/careers/programs-and-internships/junior-professional-associates",
            "source": "World Bank"
        },
        {
            "id": "cur_20", "category": "internship",
            "title": "African Development Bank Internship Program",
            "deadline": "Rolling",
            "url": "https://www.afdb.org/en/about/careers/internship-programme",
            "source": "African Development Bank"
        },
        {
            "id": "cur_21", "category": "internship",
            "title": "IMF Internship Program — International Monetary Fund",
            "deadline": "January & October",
            "url": "https://www.imf.org/en/About/Recruitment/internship-program",
            "source": "IMF"
        },
        {
            "id": "cur_22", "category": "internship",
            "title": "Google BOLD Internship — Open to African Students",
            "deadline": "Rolling",
            "url": "https://buildyourfuture.withgoogle.com/programs/bold",
            "source": "Google"
        },
        {
            "id": "cur_23", "category": "internship",
            "title": "Microsoft Internship — EMEA Region (Kenya eligible)",
            "deadline": "Rolling",
            "url": "https://careers.microsoft.com/students/us/en/usiternship",
            "source": "Microsoft"
        },

        # ── GRANTS & FUNDING ─────────────────────────────────────────────────
        {
            "id": "cur_24", "category": "grant",
            "title": "Tony Elumelu Foundation Entrepreneurship Grant — $5,000",
            "deadline": "January annually",
            "url": "https://www.tonyelumelufoundation.org/teep/apply",
            "source": "Tony Elumelu Foundation"
        },
        {
            "id": "cur_25", "category": "grant",
            "title": "Google for Startups Africa Fund — Apply Now",
            "deadline": "Rolling",
            "url": "https://startup.google.com/programs/black-founders-fund/africa/",
            "source": "Google"
        },
        {
            "id": "cur_26", "category": "grant",
            "title": "Echoing Green Fellowship Grant — $90,000 for Social Entrepreneurs",
            "deadline": "January annually",
            "url": "https://echoinggreen.org/fellowship/apply/",
            "source": "Echoing Green"
        },
        {
            "id": "cur_27", "category": "grant",
            "title": "Hivos East Africa Innovation Fund — Kenyan Startups",
            "deadline": "Rolling",
            "url": "https://east-africa.hivos.org/",
            "source": "Hivos"
        },
        {
            "id": "cur_28", "category": "grant",
            "title": "Gates Foundation Grand Challenges Explorations — $100,000",
            "deadline": "Rolling rounds",
            "url": "https://gcgh.grandchallenges.org/submit",
            "source": "Gates Foundation"
        },
        {
            "id": "cur_29", "category": "grant",
            "title": "GSMA Innovation Fund for Mobile Internet — Africa",
            "deadline": "See link",
            "url": "https://www.gsma.com/mobilefordevelopment/innovation-fund/",
            "source": "GSMA"
        },
        {
            "id": "cur_30", "category": "grant",
            "title": "Villgro Africa — Grant + Support for African Health Startups",
            "deadline": "Rolling",
            "url": "https://villgroafrica.org/apply/",
            "source": "Villgro Africa"
        },
    ]


# ─── RSS Live Sources (bonus on top of curated) ──────────────────────────────

SCHOLARSHIP_KEYWORDS = [
    "scholarship", "fellowship", "internship", "grant", "funding", "bursary",
    "award", "stipend", "exchange", "masters", "phd", "apply", "application"
]

def get_opportunity_desk():
    try:
        resp = requests.get("https://opportunitydesk.org/feed/", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            if not any(k in title.lower() for k in SCHOLARSHIP_KEYWORDS):
                continue
            cat = detect_category(title)
            results.append({
                "id": f"od_{hash(link) % 999999}", "title": title,
                "url": link, "category": cat,
                "deadline": "See link", "source": "Opportunity Desk"
            })
        log.info(f"Opportunity Desk: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Opportunity Desk: {ex}")
        return []

def get_scholars4dev():
    try:
        resp = requests.get("https://www.scholars4dev.com/feed/", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            cat = detect_category(title)
            results.append({
                "id": f"s4d_{hash(link) % 999999}", "title": title,
                "url": link, "category": cat,
                "deadline": "See link", "source": "Scholars4Dev"
            })
        log.info(f"Scholars4Dev: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Scholars4Dev: {ex}")
        return []

def get_youth_opportunities():
    try:
        resp = requests.get("https://www.youthop.com/feed", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            if not any(k in title.lower() for k in SCHOLARSHIP_KEYWORDS):
                continue
            cat = detect_category(title)
            results.append({
                "id": f"yo_{hash(link) % 999999}", "title": title,
                "url": link, "category": cat,
                "deadline": "See link", "source": "Youth Opportunities"
            })
        log.info(f"Youth Opportunities: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Youth Opportunities: {ex}")
        return []

def detect_category(title):
    t = title.lower()
    if any(k in t for k in ["fellowship", "fellow"]):
        return "fellowship"
    if any(k in t for k in ["internship", "intern"]):
        return "internship"
    if any(k in t for k in ["grant", "funding", "fund", "award", "prize", "entrepreneur"]):
        return "grant"
    return "scholarship"


# ─── Aggregator ──────────────────────────────────────────────────────────────

def get_all_opportunities(category=None):
    log.info(f"Fetching all opportunities (category={category})")

    # Start with curated (always reliable, direct links)
    curated = get_curated_opportunities()

    # Add live RSS sources on top
    live = []
    live += get_opportunity_desk()
    live += get_scholars4dev()
    live += get_youth_opportunities()

    all_opps = curated + live

    # Filter by category
    if category and category != "all":
        all_opps = [o for o in all_opps if o["category"] == category]

    # Deduplicate by title
    seen, unique = set(), []
    for o in all_opps:
        key = o["title"].lower().strip()[:60]
        if key not in seen and o["title"]:
            seen.add(key)
            unique.append(o)

    log.info(f"Total unique: {len(unique)}")
    return unique


# ─── Message Builder ─────────────────────────────────────────────────────────

CATEGORY_EMOJI = {
    "scholarship": "🎓",
    "fellowship":  "🌍",
    "internship":  "💼",
    "grant":       "💰",
}

def build_message(opps, category=None):
    now = now_eat()
    today = now.strftime("%A, %d %b %Y · %I:%M %p EAT")

    cat_label = {
        "scholarship": "🎓 Scholarships",
        "fellowship":  "🌍 Fellowships",
        "internship":  "💼 Internships",
        "grant":       "💰 Grants & Funding",
    }.get(category, "🔥 All Opportunities")

    msg = f"<b>{cat_label} for Kenyan Students</b>\n📅 {today}\n\n"

    to_show = opps[:MAX_OPPS]
    for i, o in enumerate(to_show, 1):
        emoji = CATEGORY_EMOJI.get(o["category"], "📌")
        title = html.escape(o['title'])
        source = html.escape(o['source'])
        msg  += f"{emoji} <b>{i}. {title}</b>\n"
        if o.get("deadline") and o["deadline"] != "See link":
            deadline = html.escape(o['deadline'])
            msg += f"   ⏰ <b>Deadline:</b> {deadline}\n"
        msg += f"   🔗 <a href='{o['url']}'>Click Here to Apply</a>\n"
        msg += f"   📌 <i>{source}</i>\n\n"

    msg += f"<i>Showing {len(to_show)} opportunities. Tap a button for more 👇</i>"
    return msg


# ─── Broadcast ───────────────────────────────────────────────────────────────

def broadcast_opportunities():
    log.info("─── Daily broadcast ───")
    subscribers = load_subscribers()
    if not subscribers:
        log.info("No subscribers.")
        return {"sent": 0, "failed": 0, "opps": 0}

    sent_ids = load_sent_ids()
    all_opps = get_all_opportunities()

    # Filter already sent, but always keep curated ones
    new_opps = [o for o in all_opps if o["id"] not in sent_ids or o["id"].startswith("cur_")]
    if len(new_opps) < MAX_OPPS:
        new_opps = all_opps  # reset if too few

    to_send = new_opps[:MAX_OPPS]
    message = build_message(to_send)

    sent, failed = 0, 0
    for chat_id in subscribers:
        if send_message(chat_id, message, reply_markup=MAIN_BUTTONS):
            sent += 1
        else:
            failed += 1

    # Only track non-curated as sent (curated rotate back in)
    sent_ids.update(o["id"] for o in to_send if not o["id"].startswith("cur_"))
    save_sent_ids(sent_ids)

    log.info(f"Broadcast: {sent} sent, {failed} failed, {len(to_send)} opps")
    return {"sent": sent, "failed": failed, "opps": len(to_send)}


# ─── Scheduler (Kenya Time) ───────────────────────────────────────────────────

def run_scheduler():
    """
    Bulletproof scheduler using Kenyan time.
    Checks every 20 seconds. If it is past send time and not yet sent today, sends immediately.
    Uses persistent file storage so restarts don't trigger double sends (or miss sends).
    """
    log.info(f"Scheduler started — daily broadcast at {SEND_TIME} EAT (Nairobi)")
    send_hour, send_min = map(int, SEND_TIME.split(":"))

    while True:
        try:
            now           = now_eat()
            today_str     = now.strftime("%Y-%m-%d")
            last_sent_day = load_last_run()
            
            now_total = now.hour * 60 + now.minute
            snd_total = send_hour * 60 + send_min

            # Send if: past send time today AND not yet sent today
            if now_total >= snd_total and last_sent_day != today_str:
                log.info(f"Sending daily broadcast — Nairobi: {now.strftime('%H:%M EAT')}")
                broadcast_opportunities()
                save_last_run(today_str)
        except Exception as ex:
            log.error(f"Scheduler error: {ex}")
        time.sleep(20)


# ─── Webhook Handler ─────────────────────────────────────────────────────────

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "ok"

    # Button taps
    if "callback_query" in data:
        cb      = data["callback_query"]
        chat_id = str(cb["message"]["chat"]["id"])
        cb_id   = cb["id"]
        action  = cb.get("data", "")
        answer_callback(cb_id)
        category = action.replace("cat_", "") if action.startswith("cat_") else None
        if category == "all":
            category = None
        send_message(chat_id, "⏳ Fetching latest opportunities...")
        opps    = get_all_opportunities(category)
        send_message(chat_id, build_message(opps, category), reply_markup=MAIN_BUTTONS)
        return "ok"

    # Text messages
    message  = data.get("message", {})
    chat     = message.get("chat", {})
    text     = message.get("text", "").strip()
    chat_id  = str(chat.get("id", ""))
    name     = chat.get("first_name", "Friend")
    username = chat.get("username", "")
    if not chat_id:
        return "ok"

    subscribers = load_subscribers()

    if text == "/start":
        if chat_id not in subscribers:
            subscribers[chat_id] = {
                "name": name, "username": username,
                "joined": now_eat().strftime("%Y-%m-%d %H:%M EAT")
            }
            save_subscribers(subscribers)
            log.info(f"New subscriber: {name} ({chat_id})")

        send_message(chat_id,
            f"👋 <b>Habari {name}!</b> Welcome to the <b>Kenya Scholarship Bot!</b> 🇰🇪🎓\n\n"
            f"I send you <b>direct application links</b> for scholarships, fellowships, internships and grants — "
            f"all open to Kenyan students!\n\n"
            f"📅 <b>Daily update:</b> Every day at <b>{SEND_TIME} Nairobi time</b>\n"
            f"🔗 <b>All links</b> go directly to application pages\n"
            f"✅ <b>Minimum 15 opportunities</b> every broadcast\n\n"
            f"👇 <b>What are you looking for today?</b>",
            reply_markup=MAIN_BUTTONS
        )

    elif text == "/stop":
        if chat_id in subscribers:
            del subscribers[chat_id]
            save_subscribers(subscribers)
        send_message(chat_id,
            "😢 You've been unsubscribed.\n\nType /start anytime to come back!\n\nGood luck! 🌟"
        )

    elif text in ["/opportunities", "/opps"]:
        send_message(chat_id, "⏳ Fetching the latest opportunities...")
        opps = get_all_opportunities()
        send_message(chat_id, build_message(opps), reply_markup=MAIN_BUTTONS)

    elif text == "/count":
        send_message(chat_id,
            f"👥 <b>Total subscribers:</b> {len(subscribers)}\n\n"
            f"🕐 <b>Current Nairobi time:</b> {now_eat().strftime('%I:%M %p EAT')}",
            reply_markup=MAIN_BUTTONS
        )

    elif text == "/time":
        send_message(chat_id,
            f"🕐 <b>Current Nairobi time:</b> {now_eat().strftime('%A, %d %b %Y · %I:%M %p EAT')}\n"
            f"📅 <b>Next broadcast:</b> Today/Tomorrow at <b>{SEND_TIME} EAT</b>",
            reply_markup=MAIN_BUTTONS
        )

    elif text == "/help":
        send_message(chat_id,
            "🤖 <b>Kenya Scholarship & Opportunity Bot</b>\n\n"
            "📡 <b>Sources:</b> Opportunity Desk, Scholars4Dev, Youth Opportunities + 30 curated links\n"
            "🔗 <b>All links</b> go directly to application pages\n"
            "✅ <b>Minimum 15</b> opportunities per broadcast\n"
            f"⏰ <b>Sends daily at {SEND_TIME} Nairobi time</b>\n\n"
            "<b>/start</b> — Subscribe\n"
            "<b>/opportunities</b> — Get all opportunities now\n"
            "<b>/time</b> — Check current Nairobi time\n"
            "<b>/stop</b> — Unsubscribe\n"
            "<b>/help</b> — This message\n\n"
            "👇 Or tap a category:",
            reply_markup=MAIN_BUTTONS
        )

    else:
        send_message(chat_id,
            "👇 Choose what you're looking for:",
            reply_markup=MAIN_BUTTONS
        )

    return "ok"


# ─── Admin Panel ─────────────────────────────────────────────────────────────

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scholarship Bot Admin</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0a1628; color: #e0e0e0; min-height: 100vh; }
  .header { background: linear-gradient(135deg, #1a2a4a, #0d3b6e);
            padding: 20px; text-align: center; border-bottom: 1px solid #1e3a5f; }
  .header h1 { font-size: 22px; color: #4fc3f7; }
  .header p  { font-size: 13px; color: #888; margin-top: 4px; }
  .container { max-width: 600px; margin: 0 auto; padding: 20px; }
  .card { background: #112240; border: 1px solid #1e3a5f; border-radius: 12px;
          padding: 20px; margin-bottom: 16px; }
  .card h2 { font-size: 15px; color: #4fc3f7; margin-bottom: 14px; }
  .stat { display: flex; justify-content: space-between; align-items: center;
          padding: 10px 0; border-bottom: 1px solid #1e3a5f; }
  .stat:last-child { border-bottom: none; }
  .stat-label { font-size: 13px; color: #aaa; }
  .stat-value { font-size: 18px; font-weight: bold; color: #fff; }
  .btn { width: 100%; padding: 14px; border: none; border-radius: 10px;
         font-size: 15px; font-weight: 600; cursor: pointer; margin-bottom: 10px; transition: opacity 0.2s; }
  .btn:active { opacity: 0.7; }
  .btn-primary { background: linear-gradient(135deg, #4fc3f7, #0288d1); color: #fff; }
  .btn-success { background: linear-gradient(135deg, #81c784, #388e3c); color: #fff; }
  .subscriber { display: flex; align-items: center; padding: 10px 0; border-bottom: 1px solid #1e3a5f; }
  .subscriber:last-child { border-bottom: none; }
  .avatar { width: 36px; height: 36px; border-radius: 50%; background: #0288d1;
            display: flex; align-items: center; justify-content: center;
            font-weight: bold; color: #fff; margin-right: 12px; font-size: 14px; flex-shrink: 0; }
  .sub-info { flex: 1; }
  .sub-name { font-size: 14px; font-weight: 600; }
  .sub-meta { font-size: 11px; color: #888; margin-top: 2px; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .tag { padding: 4px 10px; border-radius: 20px; font-size: 11px; }
  .tag-blue   { background: #1e3a5f; color: #4fc3f7; }
  .tag-green  { background: #1a3a1a; color: #81c784; }
  .tag-orange { background: #3a2a1a; color: #ffb74d; }
  .tag-red    { background: #3a1a1a; color: #ef9a9a; }
  .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
           background: #1e3a5f; color: #fff; padding: 12px 24px; border-radius: 30px;
           font-size: 14px; display: none; z-index: 99; }
  .login-wrap { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .login-card { background: #112240; border: 1px solid #1e3a5f; border-radius: 16px;
                padding: 30px; width: 90%; max-width: 360px; text-align: center; }
  .login-card h2 { color: #4fc3f7; margin-bottom: 6px; }
  .login-card p { color: #888; font-size: 13px; margin-bottom: 20px; }
  input { width: 100%; padding: 12px; border: 1px solid #1e3a5f; border-radius: 8px;
          background: #0a1628; color: #fff; font-size: 15px; margin-bottom: 12px; }
  .result-box { background: #0a1628; border-radius: 8px; padding: 12px;
                font-size: 13px; color: #81c784; margin-top: 10px; display: none; }
  .time-display { font-size: 24px; font-weight: bold; color: #4fc3f7; text-align: center;
                  padding: 10px 0; }
  #adminPanel { display: none; }
</style>
</head>
<body>
<div class="login-wrap" id="loginWrap">
  <div class="login-card">
    <h2>🎓 Admin Panel</h2>
    <p>Kenya Scholarship Bot</p>
    <input type="password" id="pwInput" placeholder="Enter password" />
    <button class="btn btn-primary" onclick="login()">Login</button>
  </div>
</div>

<div id="adminPanel">
  <div class="header">
    <h1>🎓 Kenya Scholarship Bot</h1>
    <p>Admin Dashboard — Nairobi Time</p>
  </div>
  <div class="container">

    <div class="card">
      <h2>🕐 Nairobi Time (EAT)</h2>
      <div class="time-display" id="nairobiTime">--:-- --</div>
    </div>

    <div class="card">
      <h2>📊 Stats</h2>
      <div class="stat">
        <span class="stat-label">Total Subscribers</span>
        <span class="stat-value" id="subCount">—</span>
      </div>
      <div class="stat">
        <span class="stat-label">Daily Broadcast Time</span>
        <span class="stat-value">09:00 AM EAT</span>
      </div>
      <div class="stat">
        <span class="stat-label">Min Opportunities Per Broadcast</span>
        <span class="stat-value">15</span>
      </div>
      <div class="stat">
        <span class="stat-label">Curated Direct Links</span>
        <span class="stat-value">30</span>
      </div>
      <div class="stat">
        <span class="stat-label">Target Audience</span>
        <span class="stat-value">🇰🇪 Kenyan Students</span>
      </div>
    </div>

    <div class="card">
      <h2>📂 Categories Covered</h2>
      <div class="tags">
        <span class="tag tag-green">🎓 Scholarships</span>
        <span class="tag tag-blue">🌍 Fellowships</span>
        <span class="tag tag-orange">💼 Internships</span>
        <span class="tag tag-red">💰 Grants</span>
      </div>
    </div>

    <div class="card">
      <h2>📡 Sources</h2>
      <div class="tags">
        <span class="tag tag-blue">Opportunity Desk</span>
        <span class="tag tag-blue">Scholars4Dev</span>
        <span class="tag tag-blue">Youth Opportunities</span>
        <span class="tag tag-blue">30 Curated Links</span>
      </div>
    </div>

    <div class="card">
      <h2>⚡ Actions</h2>
      <button class="btn btn-success" onclick="broadcast()">📤 Send to All Subscribers Now</button>
      <button class="btn btn-primary" onclick="testBroadcast()">🧪 Send TEST to Admin Only</button>
      <button class="btn btn-primary" onclick="loadSubscribers()">🔄 Refresh Subscribers</button>
      <div class="result-box" id="resultBox"></div>
    </div>

    <div class="card">
      <h2>👥 Subscribers</h2>
      <div id="subList">Loading...</div>
    </div>

  </div>
</div>

<div class="toast" id="toast"></div>
<script>
let password = "";

// Live Nairobi clock
function updateClock() {
  const now = new Date();
  const eat = new Date(now.toLocaleString("en-US", { timeZone: "Africa/Nairobi" }));
  const h   = eat.getHours() % 12 || 12;
  const m   = String(eat.getMinutes()).padStart(2, "0");
  const s   = String(eat.getSeconds()).padStart(2, "0");
  const ap  = eat.getHours() >= 12 ? "PM" : "AM";
  const el  = document.getElementById("nairobiTime");
  if (el) el.textContent = `${h}:${m}:${s} ${ap} EAT`;
}
setInterval(updateClock, 1000);
updateClock();

function login() {
  password = document.getElementById("pwInput").value;
  fetch("/admin/stats", { headers: { "X-Admin-Password": password } }).then(r => {
    if (r.ok) {
      document.getElementById("loginWrap").style.display = "none";
      document.getElementById("adminPanel").style.display = "block";
      loadData();
    } else { showToast("❌ Wrong password"); }
  });
}
function loadData() {
  fetch("/admin/stats", { headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      document.getElementById("subCount").textContent = d.subscriber_count;
    });
  loadSubscribers();
}
function loadSubscribers() {
  fetch("/admin/subscribers", { headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(data => {
      const list = document.getElementById("subList");
      if (!data.subscribers || data.subscribers.length === 0) {
        list.innerHTML = '<p style="color:#888;font-size:13px">No subscribers yet!</p>';
        return;
      }
      list.innerHTML = data.subscribers.map(s => `
        <div class="subscriber">
          <div class="avatar">${s.name[0].toUpperCase()}</div>
          <div class="sub-info">
            <div class="sub-name">${s.name}</div>
            <div class="sub-meta">${s.username ? "@"+s.username : "No username"} · ${s.joined}</div>
          </div>
        </div>`).join("");
      document.getElementById("subCount").textContent = data.subscribers.length;
    });
}
function broadcast() {
  const box = document.getElementById("resultBox");
  box.style.display = "block";
  box.textContent = "⏳ Sending opportunities to all subscribers...";
  fetch("/admin/broadcast", { method: "POST", headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      box.textContent = `✅ Sent to ${d.sent} subscribers with ${d.opps} opportunities!`;
      showToast("✅ Done!");
    }).catch(() => { box.textContent = "❌ Something went wrong."; });
}
function testBroadcast() {
  const box = document.getElementById("resultBox");
  box.style.display = "block";
  box.textContent = "⏳ Sending test broadcast to admin...";
  fetch("/admin/test-broadcast", { method: "POST", headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      box.textContent = d.success ? "✅ Test message sent to admin!" : "❌ " + d.error;
      showToast(d.success ? "✅ Done!" : "❌ Error");
    }).catch(() => { box.textContent = "❌ Something went wrong."; });
}
function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.style.display = "block";
  setTimeout(() => t.style.display = "none", 3000);
}
document.getElementById("pwInput").addEventListener("keydown", e => { if (e.key==="Enter") login(); });
</script>
</body>
</html>
"""

def check_admin(req):
    return req.headers.get("X-Admin-Password") == ADMIN_PASSWORD

@app.route("/")
def index():
    return render_template_string(ADMIN_HTML)

@app.route("/admin/stats")
def admin_stats():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "subscriber_count": len(load_subscribers()),
        "send_time": SEND_TIME,
        "nairobi_time": now_eat().strftime("%I:%M %p EAT")
    })

@app.route("/admin/subscribers")
def admin_subscribers():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    subs = load_subscribers()
    return jsonify({"subscribers": [
        {"name": v["name"], "username": v.get("username", ""), "joined": v["joined"]}
        for v in subs.values()
    ]})

@app.route("/admin/broadcast", methods=["POST"])
def admin_broadcast():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    return jsonify(broadcast_opportunities())

@app.route("/admin/test-broadcast", methods=["POST"])
def admin_test_broadcast():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 401
    # Try to find a 'chat_id' for testing (e.g. from the .env if set, or just use first subscriber)
    test_id = os.getenv("TELEGRAM_CHAT_ID")
    if not test_id:
        subs = load_subscribers()
        if subs: test_id = list(subs.keys())[0]
    
    if not test_id:
        return jsonify({"success": False, "error": "No subscriber found for testing"})
    
    all_opps = get_all_opportunities()
    message = build_message(all_opps[:MAX_OPPS])
    success = send_message(test_id, "🧪 <b>TEST BROADCAST</b>\n\n" + message)
    return jsonify({"success": success, "error": None if success else "Telegram failed"})

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "nairobi_time": now_eat().strftime("%I:%M %p EAT"),
        "next_broadcast": SEND_TIME + " EAT"
    })


# ─── Self-Ping (Keep Railway Awake) ──────────────────────────────────────────

def self_ping():
    """Pings /health every 5 minutes to prevent Railway free tier from sleeping."""
    app_url = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not app_url:
        log.warning("No app URL for self-ping — bot may sleep and miss send time.")
        return
    prefix = "" if app_url.startswith("http") else "https://"
    ping_url = f"{prefix}{app_url}/health"
    log.info(f"Self-ping active → {ping_url} every 5 min")
    while True:
        try:
            resp = requests.get(ping_url, timeout=10)
            log.info(f"Ping OK ({resp.status_code}) — Nairobi: {now_eat().strftime('%H:%M EAT')}")
        except Exception as ex:
            log.warning(f"Ping failed: {ex}")
        time.sleep(300)


# ─── Main ────────────────────────────────────────────────────────────────────

def setup_webhook():
    url = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if url:
        set_webhook(f"https://{url}/webhook/{TELEGRAM_BOT_TOKEN}")

# Start background threads at module level so gunicorn picks them up
setup_webhook()
threading.Thread(target=run_scheduler, daemon=True).start()
threading.Thread(target=self_ping,     daemon=True).start()
log.info(f"Bot started — scheduler running, daily at {SEND_TIME} Nairobi time")

if __name__ == "__main__":
    log.info(f"Running directly on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
