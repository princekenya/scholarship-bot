"""
Kenya Scholarship & Opportunity Bot
Covers: Scholarships, Fellowships, Internships, Grants & Funding
Target: Kenyan students
Sources: Opportunity Desk, Scholars4Dev, AfterSchoolAfrica, DAAD, UN, RSS feeds
"""

import os
import json
import logging
import requests
import schedule
import time
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SEND_TIME          = os.getenv("SEND_TIME", "09:00")
MAX_OPPS           = int(os.getenv("MAX_OPPS", "10"))
ADMIN_PASSWORD     = os.getenv("ADMIN_PASSWORD", "scholar2024")
PORT               = int(os.getenv("PORT", "5000"))

SUBSCRIBERS_FILE   = "subscribers.json"
SENT_IDS_FILE      = "sent_ids.json"
TELEGRAM_API       = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ScholarshipBot/1.0)"}

# Category emojis
CATEGORY_EMOJI = {
    "scholarship": "🎓",
    "fellowship":  "🌍",
    "internship":  "💼",
    "grant":       "💰",
    "funding":     "💰",
    "exchange":    "✈️",
    "program":     "📚",
}

# Inline keyboard buttons
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
        [
            {"text": "🔥 All Opportunities", "callback_data": "cat_all"}
        ]
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


# ─── Telegram Helpers ────────────────────────────────────────────────────────

def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
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
#  OPPORTUNITY SOURCES
# ══════════════════════════════════════════════════════════════════════════════

KENYA_KEYWORDS = [
    "kenya", "african", "africa", "east africa", "sub-saharan",
    "developing countries", "developing nations", "global south",
    "international students", "all nationalities", "open to all"
]

SCHOLARSHIP_KEYWORDS = [
    "scholarship", "fellowship", "internship", "grant", "funding",
    "bursary", "award", "stipend", "exchange program", "study abroad",
    "masters", "phd", "undergraduate", "postgraduate", "research"
]

def is_relevant(title, desc=""):
    text = (title + " " + desc).lower()
    has_opportunity = any(k in text for k in SCHOLARSHIP_KEYWORDS)
    # Include if it's open internationally or mentions Africa/Kenya
    has_target = any(k in text for k in KENYA_KEYWORDS) or \
                 "international" in text or \
                 has_opportunity  # broad net for opportunities
    return has_opportunity and has_target

def detect_category(title):
    title_lower = title.lower()
    if any(k in title_lower for k in ["scholarship", "bursary", "tuition", "masters", "phd", "undergraduate"]):
        return "scholarship"
    if any(k in title_lower for k in ["fellowship", "fellow"]):
        return "fellowship"
    if any(k in title_lower for k in ["internship", "intern"]):
        return "internship"
    if any(k in title_lower for k in ["grant", "funding", "fund", "award", "prize"]):
        return "grant"
    return "scholarship"  # default

def get_emoji(category):
    return CATEGORY_EMOJI.get(category, "📌")


# ─── 1. Opportunity Desk RSS ─────────────────────────────────────────────────
def get_opportunity_desk():
    try:
        resp = requests.get("https://opportunitydesk.org/feed/", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:30]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            desc  = (item.findtext("description") or "").strip()[:200]
            if not title or not link:
                continue
            if not is_relevant(title, desc):
                continue
            cat = detect_category(title)
            results.append({
                "id":       f"od_{hash(link) % 999999}",
                "title":    title,
                "url":      link,
                "category": cat,
                "deadline": extract_deadline(desc),
                "source":   "Opportunity Desk"
            })
        log.info(f"Opportunity Desk: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Opportunity Desk: {ex}")
        return []


# ─── 2. Scholars4Dev RSS ─────────────────────────────────────────────────────
def get_scholars4dev():
    try:
        resp = requests.get("https://www.scholars4dev.com/feed/", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:30]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            desc  = (item.findtext("description") or "").strip()[:200]
            if not title or not link:
                continue
            cat = detect_category(title)
            results.append({
                "id":       f"s4d_{hash(link) % 999999}",
                "title":    title,
                "url":      link,
                "category": cat,
                "deadline": extract_deadline(desc),
                "source":   "Scholars4Dev"
            })
        log.info(f"Scholars4Dev: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Scholars4Dev: {ex}")
        return []


# ─── 3. AfterSchoolAfrica RSS ────────────────────────────────────────────────
def get_afterschoolafrica():
    try:
        resp = requests.get("https://www.afterscholafrica.com/feed/", headers=HEADERS, timeout=15)
        if not resp.ok:
            resp = requests.get("https://afterschoolafrica.com/feed/", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            desc  = (item.findtext("description") or "").strip()[:200]
            if not title or not link:
                continue
            cat = detect_category(title)
            results.append({
                "id":       f"asa_{hash(link) % 999999}",
                "title":    title,
                "url":      link,
                "category": cat,
                "deadline": extract_deadline(desc),
                "source":   "AfterSchoolAfrica"
            })
        log.info(f"AfterSchoolAfrica: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"AfterSchoolAfrica: {ex}")
        return []


# ─── 4. UN Jobs & Opportunities ──────────────────────────────────────────────
def get_un_opportunities():
    try:
        resp = requests.get("https://www.un.org/en/rss.xml", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            if not is_relevant(title):
                continue
            cat = detect_category(title)
            results.append({
                "id":       f"un_{hash(link) % 999999}",
                "title":    title,
                "url":      link,
                "category": cat,
                "deadline": "See link",
                "source":   "United Nations"
            })
        log.info(f"UN: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"UN: {ex}")
        return []


# ─── 5. Youth Opportunities RSS ──────────────────────────────────────────────
def get_youth_opportunities():
    try:
        resp = requests.get("https://www.youthop.com/feed", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        results = []
        for item in channel.findall("item")[:25]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            desc  = (item.findtext("description") or "").strip()[:200]
            if not title or not link:
                continue
            if not is_relevant(title, desc):
                continue
            cat = detect_category(title)
            results.append({
                "id":       f"yo_{hash(link) % 999999}",
                "title":    title,
                "url":      link,
                "category": cat,
                "deadline": extract_deadline(desc),
                "source":   "Youth Opportunities"
            })
        log.info(f"Youth Opportunities: {len(results)}")
        return results
    except Exception as ex:
        log.error(f"Youth Opportunities: {ex}")
        return []


# ─── 6. Reliable Fallback (Always Available) ─────────────────────────────────
def get_fallback_opportunities():
    today = datetime.now()
    return [
        {
            "id": "fb_1", "category": "scholarship",
            "title": "Mastercard Foundation Scholars Program — Full Scholarship",
            "deadline": "Varies by university",
            "url": "https://mastercardfdn.org/all/scholars/",
            "source": "Mastercard Foundation"
        },
        {
            "id": "fb_2", "category": "scholarship",
            "title": "DAAD Scholarships for Kenyans — Study in Germany",
            "deadline": "October each year",
            "url": "https://www.daad.de/en/study-and-research-in-germany/scholarships/",
            "source": "DAAD"
        },
        {
            "id": "fb_3", "category": "fellowship",
            "title": "Obama Foundation Africa Leaders Program",
            "deadline": "See link",
            "url": "https://www.obama.org/programs/leaders/africa/",
            "source": "Obama Foundation"
        },
        {
            "id": "fb_4", "category": "fellowship",
            "title": "Mandela Washington Fellowship for Young African Leaders",
            "deadline": "November each year",
            "url": "https://yali.state.gov/mwf/",
            "source": "US State Dept"
        },
        {
            "id": "fb_5", "category": "scholarship",
            "title": "Commonwealth Scholarships for Kenyan Students — UK",
            "deadline": "December each year",
            "url": "https://cscuk.fcdo.gov.uk/apply/",
            "source": "Commonwealth"
        },
        {
            "id": "fb_6", "category": "internship",
            "title": "UN Internship Programme — Open to Kenyans",
            "deadline": "Rolling applications",
            "url": "https://careers.un.org/internship",
            "source": "United Nations"
        },
        {
            "id": "fb_7", "category": "grant",
            "title": "Tony Elumelu Foundation Entrepreneurship Grant — $5,000",
            "deadline": "January each year",
            "url": "https://www.tonyelumelufoundation.org/teep",
            "source": "TEF"
        },
        {
            "id": "fb_8", "category": "scholarship",
            "title": "Chevening Scholarship — UK Government — Full Funding",
            "deadline": "November each year",
            "url": "https://www.chevening.org/apply/",
            "source": "UK Government"
        },
        {
            "id": "fb_9", "category": "fellowship",
            "title": "African Leadership Academy Fellowship",
            "deadline": "Rolling",
            "url": "https://www.africanleadershipacademy.org/",
            "source": "ALA"
        },
        {
            "id": "fb_10", "category": "grant",
            "title": "Google for Startups — Africa Fund",
            "deadline": "Rolling applications",
            "url": "https://startup.google.com/programs/black-founders-fund/africa/",
            "source": "Google"
        },
        {
            "id": "fb_11", "category": "internship",
            "title": "World Bank Junior Professional Associates Program",
            "deadline": "October each year",
            "url": "https://www.worldbank.org/en/about/careers/programs-and-internships",
            "source": "World Bank"
        },
        {
            "id": "fb_12", "category": "scholarship",
            "title": "Aga Khan Foundation International Scholarship",
            "deadline": "March each year",
            "url": "https://www.akdn.org/our-agencies/aga-khan-foundation/international-scholarship-programme",
            "source": "Aga Khan"
        },
    ]


# ─── Deadline Extractor ───────────────────────────────────────────────────────
def extract_deadline(text):
    """Try to find a deadline mention in description text."""
    text_lower = text.lower()
    months = ["january","february","march","april","may","june",
              "july","august","september","october","november","december"]
    for month in months:
        if month in text_lower:
            idx = text_lower.index(month)
            snippet = text[max(0, idx-10):idx+20].strip()
            if any(c.isdigit() for c in snippet):
                return snippet[:30]
    if "deadline" in text_lower:
        idx = text_lower.index("deadline")
        return text[idx:idx+40].strip()
    return "See link"


# ─── Aggregator ──────────────────────────────────────────────────────────────

def get_all_opportunities(category=None):
    """Fetch from all sources, filter by category, guarantee 10+."""
    log.info(f"Fetching opportunities (category={category})...")

    all_opps = []
    all_opps += get_opportunity_desk()
    all_opps += get_scholars4dev()
    all_opps += get_afterschoolafrica()
    all_opps += get_youth_opportunities()
    all_opps += get_un_opportunities()

    # Filter by category
    if category and category != "all":
        filtered = [o for o in all_opps if o["category"] == category]
    else:
        filtered = all_opps

    # Deduplicate by title
    seen, unique = set(), []
    for o in filtered:
        key = o["title"].lower().strip()[:60]
        if key not in seen and o["title"]:
            seen.add(key)
            unique.append(o)

    # Pad with fallback if not enough
    if len(unique) < 10:
        fallback = get_fallback_opportunities()
        if category and category != "all":
            fallback = [f for f in fallback if f["category"] == category]
        for o in fallback:
            key = o["title"].lower().strip()[:60]
            if key not in seen:
                seen.add(key)
                unique.append(o)

    log.info(f"Total opportunities: {len(unique)}")
    return unique


# ─── Message Builder ─────────────────────────────────────────────────────────

def build_message(opps, category=None):
    today = datetime.now().strftime("%A, %d %b %Y")

    cat_label = {
        "scholarship": "🎓 Scholarships",
        "fellowship":  "🌍 Fellowships",
        "internship":  "💼 Internships",
        "grant":       "💰 Grants & Funding",
        "all":         "🔥 All Opportunities",
        None:          "🔥 All Opportunities"
    }.get(category, "🔥 All Opportunities")

    msg = f"{cat_label} *for Kenyan Students*\n📅 {today}\n\n"

    for i, o in enumerate(opps[:MAX_OPPS], 1):
        emoji = get_emoji(o["category"])
        msg  += f"{emoji} *{i}. {o['title']}*\n"
        if o.get("deadline") and o["deadline"] != "See link":
            msg += f"   ⏰ Deadline: {o['deadline']}\n"
        msg += f"   🔗 {o['url']}\n"
        msg += f"   📌 _{o['source']}_\n\n"

    msg += "_Choose a category below or tap again to refresh 👇_"
    return msg


# ─── Broadcast ───────────────────────────────────────────────────────────────

def broadcast_opportunities():
    log.info("─── Broadcasting opportunities ───")
    subscribers = load_subscribers()
    if not subscribers:
        return {"sent": 0, "failed": 0, "opps": 0}

    sent_ids = load_sent_ids()
    all_opps = get_all_opportunities()
    new_opps = [o for o in all_opps if o["id"] not in sent_ids]
    if len(new_opps) < 5:
        new_opps = all_opps

    to_send = new_opps[:MAX_OPPS]
    message = build_message(to_send)

    sent, failed = 0, 0
    for chat_id in subscribers:
        if send_message(chat_id, message, reply_markup=MAIN_BUTTONS):
            sent += 1
        else:
            failed += 1

    sent_ids.update(o["id"] for o in to_send)
    save_sent_ids(sent_ids)
    log.info(f"Broadcast: {sent} sent, {failed} failed")
    return {"sent": sent, "failed": failed, "opps": len(to_send)}


# ─── Telegram Webhook ────────────────────────────────────────────────────────

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "ok"

    # ── Button taps ──────────────────────────────────────────────────────────
    if "callback_query" in data:
        cb      = data["callback_query"]
        chat_id = str(cb["message"]["chat"]["id"])
        cb_id   = cb["id"]
        action  = cb.get("data", "")

        answer_callback(cb_id)

        category = action.replace("cat_", "") if action.startswith("cat_") else "all"
        send_message(chat_id, "⏳ Fetching latest opportunities...")
        opps    = get_all_opportunities(category if category != "all" else None)
        message = build_message(opps, category)
        send_message(chat_id, message, reply_markup=MAIN_BUTTONS)
        return "ok"

    # ── Text messages ────────────────────────────────────────────────────────
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
                "joined": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            save_subscribers(subscribers)
            log.info(f"New subscriber: {name} ({chat_id})")

        send_message(chat_id,
            f"👋 *Habari {name}!* Welcome to the *Kenya Scholarship & Opportunity Bot!* 🎓\n\n"
            f"I send you *fresh scholarships, fellowships, internships and grants* every day!\n\n"
            f"📅 Daily updates at 9:00 AM\n"
            f"🎯 Curated for *Kenyan students*\n"
            f"🔕 /stop — Unsubscribe anytime\n\n"
            f"👇 *What are you looking for?*",
            reply_markup=MAIN_BUTTONS
        )

    elif text == "/stop":
        if chat_id in subscribers:
            del subscribers[chat_id]
            save_subscribers(subscribers)
        send_message(chat_id,
            "😢 You've been unsubscribed.\n\nType /start anytime to come back!\n\n"
            "Good luck with your applications! 🌟"
        )

    elif text == "/opportunities" or text == "/opps":
        send_message(chat_id, "⏳ Fetching latest opportunities for you...")
        opps    = get_all_opportunities()
        message = build_message(opps)
        send_message(chat_id, message, reply_markup=MAIN_BUTTONS)

    elif text == "/count":
        send_message(chat_id,
            f"👥 *Total subscribers:* {len(subscribers)}\n\n"
            f"Share the bot: @Kenya\\_Scholarship\\_Bot",
            reply_markup=MAIN_BUTTONS
        )

    elif text == "/help":
        send_message(chat_id,
            "🤖 *Kenya Scholarship & Opportunity Bot*\n\n"
            "📡 *Sources:* Opportunity Desk, Scholars4Dev, AfterSchoolAfrica, Youth Opportunities, UN & more\n\n"
            "*/start* — Subscribe & see menu\n"
            "*/opportunities* — Get all opportunities now\n"
            "*/stop* — Unsubscribe\n"
            "*/count* — See total subscribers\n\n"
            "Or use the buttons below 👇",
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
  .stat-value { font-size: 20px; font-weight: bold; color: #fff; }
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
  .sources { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .source-tag { background: #1e3a5f; color: #4fc3f7; padding: 4px 10px; border-radius: 20px; font-size: 11px; }
  .cat-tag { padding: 4px 10px; border-radius: 20px; font-size: 11px; }
  .cat-scholarship { background: #1a3a1a; color: #81c784; }
  .cat-fellowship  { background: #1a2a4a; color: #4fc3f7; }
  .cat-internship  { background: #3a2a1a; color: #ffb74d; }
  .cat-grant       { background: #3a1a1a; color: #ef9a9a; }
  .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
           background: #1e3a5f; color: #fff; padding: 12px 24px; border-radius: 30px;
           font-size: 14px; display: none; z-index: 99; }
  .login-wrap { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .login-card { background: #112240; border: 1px solid #1e3a5f; border-radius: 16px;
                padding: 30px; width: 90%; max-width: 360px; text-align: center; }
  .login-card h2 { color: #4fc3f7; margin-bottom: 6px; }
  .login-card p  { color: #888; font-size: 13px; margin-bottom: 20px; }
  input { width: 100%; padding: 12px; border: 1px solid #1e3a5f; border-radius: 8px;
          background: #0a1628; color: #fff; font-size: 15px; margin-bottom: 12px; }
  .result-box { background: #0a1628; border-radius: 8px; padding: 12px;
                font-size: 13px; color: #81c784; margin-top: 10px; display: none; }
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
    <p>Admin Dashboard</p>
  </div>
  <div class="container">

    <div class="card">
      <h2>📊 Stats</h2>
      <div class="stat">
        <span class="stat-label">Total Subscribers</span>
        <span class="stat-value" id="subCount">—</span>
      </div>
      <div class="stat">
        <span class="stat-label">Daily Send Time</span>
        <span class="stat-value" style="font-size:14px">9:00 AM</span>
      </div>
      <div class="stat">
        <span class="stat-label">Target Audience</span>
        <span class="stat-value" style="font-size:14px">🇰🇪 Kenyan Students</span>
      </div>
    </div>

    <div class="card">
      <h2>📡 Sources</h2>
      <div class="sources">
        <span class="source-tag">Opportunity Desk</span>
        <span class="source-tag">Scholars4Dev</span>
        <span class="source-tag">AfterSchoolAfrica</span>
        <span class="source-tag">Youth Opportunities</span>
        <span class="source-tag">United Nations</span>
        <span class="source-tag">+ Fallback</span>
      </div>
    </div>

    <div class="card">
      <h2>📂 Categories</h2>
      <div class="sources">
        <span class="cat-tag cat-scholarship">🎓 Scholarships</span>
        <span class="cat-tag cat-fellowship">🌍 Fellowships</span>
        <span class="cat-tag cat-internship">💼 Internships</span>
        <span class="cat-tag cat-grant">💰 Grants</span>
      </div>
    </div>

    <div class="card">
      <h2>⚡ Actions</h2>
      <button class="btn btn-success" onclick="broadcast()">📤 Send Opportunities to All Now</button>
      <button class="btn btn-primary" onclick="loadSubscribers()">🔄 Refresh</button>
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
            <div class="sub-meta">${s.username ? "@"+s.username : "No username"} · Joined ${s.joined}</div>
          </div>
        </div>`).join("");
      document.getElementById("subCount").textContent = data.subscribers.length;
    });
}
function broadcast() {
  const box = document.getElementById("resultBox");
  box.style.display = "block";
  box.textContent = "⏳ Fetching opportunities and sending...";
  fetch("/admin/broadcast", { method: "POST", headers: { "X-Admin-Password": password } })
    .then(r => r.json()).then(d => {
      box.textContent = `✅ Sent to ${d.sent} subscribers with ${d.opps} opportunities!`;
      showToast("✅ Done!");
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
    return jsonify({"subscriber_count": len(load_subscribers()), "send_time": SEND_TIME})

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

@app.route("/health")
def health():
    return jsonify({"status": "ok", "bot": "Kenya Scholarship Bot"})


# ─── Scheduler & Main ────────────────────────────────────────────────────────

def run_scheduler():
    schedule.every().day.at(SEND_TIME).do(broadcast_opportunities)
    log.info(f"Scheduler: daily at {SEND_TIME}")
    while True:
        schedule.run_pending()
        time.sleep(30)

def setup_webhook():
    url = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if url:
        set_webhook(f"https://{url}/webhook/{TELEGRAM_BOT_TOKEN}")

if __name__ == "__main__":
    setup_webhook()
    threading.Thread(target=run_scheduler, daemon=True).start()
    log.info(f"Bot starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
