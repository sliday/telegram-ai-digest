import os
import asyncio
import aiohttp
import logging
import json
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from telethon import TelegramClient
from pytz import UTC

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_env_from_file(env_file='.env'):
    env_path = Path(env_file)
    if env_path.exists():
        with env_path.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    else:
        logging.warning(f".env file not found at {env_path.absolute()}. Using system environment variables.")


load_env_from_file()


def get_env_variable(var_name):
    value = os.getenv(var_name)
    if value is None:
        raise ValueError(f"Environment variable '{var_name}' is not set.")
    return value


try:
    API_ID = int(get_env_variable('API_ID'))
    API_HASH = get_env_variable('API_HASH')
    PHONE_NUMBER = get_env_variable('PHONE_NUMBER')
    CHANNEL_USERNAMES = [c.strip() for c in get_env_variable('CHANNEL_USERNAMES').split(',')]
    CLAUDE_API_KEY = get_env_variable('CLAUDE_API_KEY')
    TARGET_CHANNEL = get_env_variable('TARGET_CHANNEL')
except ValueError as e:
    logging.error(f"Environment variable error: {str(e)}")
    raise

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
MAX_REQUESTS_PER_MINUTE = 30
REQUEST_INTERVAL = 60 / MAX_REQUESTS_PER_MINUTE
semaphore = asyncio.Semaphore(MAX_REQUESTS_PER_MINUTE)

client = TelegramClient('session', API_ID, API_HASH)


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

async def call_claude_api(session, prompt, retry=True):
    headers = {
        "Content-Type": "application/json",
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01"
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}]
    }
    async with semaphore:
        try:
            async with session.post(CLAUDE_API_URL, json=payload, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['content'][0]['text']
                else:
                    error_text = await response.text()
                    logging.error(f"API call failed {response.status}: {error_text}")
                    if retry:
                        await asyncio.sleep(REQUEST_INTERVAL)
                        return await call_claude_api(session, prompt, retry=False)
                    return None
        except Exception as e:
            logging.error(f"Error in API call: {e}")
            if retry:
                await asyncio.sleep(REQUEST_INTERVAL)
                return await call_claude_api(session, prompt, retry=False)
            return None
        finally:
            await asyncio.sleep(REQUEST_INTERVAL)


async def create_digest(messages_by_channel: dict, start_date: datetime, end_date: datetime):
    """
    Returns a dict:
    {
        "date_range": "...",
        "big_news": [{"headline": "...", "summary": "...", "link": "..."}, ...],
        "minor_news": [{"headline": "...", "link": "..."}, ...]
    }
    """
    total = sum(len(v) for v in messages_by_channel.values())
    if total == 0:
        return None

    date_str = f"{start_date.strftime('%Y-%m-%d %H:%M')} - {end_date.strftime('%Y-%m-%d %H:%M')} UTC"
    combined = ""
    for channel, msgs in messages_by_channel.items():
        combined += f"\n\n### Channel: @{channel}\n" + "\n".join(msgs)

    prompt = f"""You are creating a structured Hebrew daily news digest from Telegram channel messages.

Date range: {date_str}
Total messages: {total}

Classify every story into one of four sections:
- "conflict": Middle East conflicts, Gaza war, Lebanon, Iran, military operations, hostages
- "politics": Israeli domestic politics, government, Knesset, legal system, parties
- "world": global news, international events, economy, tech, anything else
- "deep": long articles, analyses, or investigative pieces sent as full text — do NOT summarize these; preserve the original text and link them as-is for further reading

Within each section, classify as:
- "big_news": significant stories — include headline + 2-3 sentence summary (max 5 items total across all sections)
- "minor_news": smaller updates — headline only (all remaining items)

Rules:
- Write ALL text in Hebrew.
- Be concise for conflict/politics/world items. Headlines max 12 words. Summaries max 40 words.
- Keep original text and phrasing as much as possible. Rephrase only if necessary for clarity or length.
- Preserve the original t.me message link for each item.
- If multiple messages cover the same story, merge them into one item.
- "deep" section items: preserve the original headline/title exactly; do not quote or copy the article body.
- Every item must include "source" (the @channel handle it came from) and "time" (HH:MM from the message timestamp).

Return ONLY a valid JSON object, no markdown fences, no preamble:
{{
  "date_range": "{date_str}",
  "big_news": [
    {{"headline": "...", "summary": "...", "link": "https://t.me/...", "section": "conflict", "source": "@channel", "time": "HH:MM"}},
    {{"headline": "...", "summary": "...", "link": "https://t.me/...", "section": "politics", "source": "@channel", "time": "HH:MM"}},
    {{"headline": "...", "summary": "...", "link": "https://t.me/...", "section": "world", "source": "@channel", "time": "HH:MM"}},
    {{"headline": "...", "summary": "...", "link": "https://t.me/...", "section": "deep", "source": "@channel", "time": "HH:MM"}}
  ],
  "minor_news": [
    {{"headline": "...", "link": "https://t.me/...", "section": "conflict", "source": "@channel", "time": "HH:MM"}},
    {{"headline": "...", "link": "https://t.me/...", "section": "politics", "source": "@channel", "time": "HH:MM"}},
    {{"headline": "...", "link": "https://t.me/...", "section": "world", "source": "@channel", "time": "HH:MM"}},
    {{"headline": "...", "link": "https://t.me/...", "section": "deep", "source": "@channel", "time": "HH:MM"}}
  ]
}}

Messages:
{combined}"""

    async with aiohttp.ClientSession() as session:
        raw = await call_claude_api(session, prompt)

    if not raw:
        return None

    try:
        clean = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw.strip())
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse Claude JSON: {e}\nRaw: {raw[:500]}")
        return None



# ---------------------------------------------------------------------------
# Telegraph publishing
# ---------------------------------------------------------------------------

TOKEN_FILE = "telegraph_token.txt"


def _meta_text(item):
    parts = []
    if item.get("source"):
        parts.append(item["source"])
    if item.get("time"):
        parts.append(item["time"])
    return " | ".join(parts)


def _deep_item_node(item):
    meta = _meta_text(item)
    headline = item.get("headline", "")
    link = item.get("link", "")
    label = f"כתבה מ-{meta}: " if meta else ""
    children = [label + headline]
    if link:
        children += [" — ", {"tag": "a", "attrs": {"href": link}, "children": ["לקריאה"]}]
    return {"tag": "p", "children": children}


def _section_nodes(items_big, items_minor, is_deep=False):
    nodes = []
    if is_deep:
        return [_deep_item_node(i) for i in items_big + items_minor]
    for item in items_big:
        nodes.append({"tag": "h4", "children": [item.get("headline", "")]})
        meta = _meta_text(item)
        if meta:
            nodes.append({"tag": "p", "children": [{"tag": "i", "children": [meta]}]})
        if item.get("summary"):
            nodes.append({"tag": "p", "children": [item["summary"]]})
        if item.get("link"):
            nodes.append({"tag": "p", "children": [
                {"tag": "a", "attrs": {"href": item["link"]}, "children": ["קישור למקור"]}
            ]})
    if items_minor:
        li_nodes = []
        for item in items_minor:
            meta = _meta_text(item)
            children = [item.get("headline", "")]
            if meta:
                children += [f" ({meta})"]
            if item.get("link"):
                children += [" — ", {"tag": "a", "attrs": {"href": item["link"]}, "children": ["קישור"]}]
            li_nodes.append({"tag": "li", "children": children})
        nodes.append({"tag": "ul", "children": li_nodes})
    return nodes


def publish_to_telegraph(digest: dict) -> str:
    from telegraph import Telegraph

    token_path = Path(TOKEN_FILE)
    if token_path.exists():
        t = Telegraph(access_token=token_path.read_text().strip())
    else:
        t = Telegraph()
        t.create_account(short_name="daily-digest", author_name="דיג'סט יומי")
        token_path.write_text(t.get_access_token())

    sections = [
        ("עדכוני לחימה והסכסוך", "conflict", False),
        ("פוליטיקה ישראלית", "politics", False),
        ("כותרות נוספות", "world", False),
        ("לקריאה נוספת", "deep", True),
    ]

    content = []
    for heading, key, is_deep in sections:
        big = [i for i in digest.get("big_news", []) if i.get("section") == key]
        minor = [i for i in digest.get("minor_news", []) if i.get("section") == key]
        if not big and not minor:
            continue
        content.append({"tag": "h3", "children": [heading]})
        content.extend(_section_nodes(big, minor, is_deep=is_deep))

    title = f"דיג'סט יומי — {digest['date_range']}"
    page = t.create_page(title=title, content=content, author_name="דיג'סט יומי")
    return page['url']


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

async def fetch_messages(channel_username: str, start_date: datetime, end_date: datetime) -> list:
    messages = []
    try:
        channel = await client.get_entity(channel_username)
        logging.info(f"Fetching from: {channel.title} (@{channel_username})")
        async for message in client.iter_messages(channel, offset_date=end_date, limit=None):
            if message.date < start_date:
                break
            if message.text and start_date <= message.date <= end_date:
                link = f"https://t.me/{channel_username}/{message.id}"
                messages.append(f"[{message.date.strftime('%H:%M')}] {message.text}\nLink: {link}")
        messages.reverse()
        logging.info(f"Fetched {len(messages)} messages from @{channel_username}")
    except Exception as e:
        logging.error(f"Error fetching from @{channel_username}: {e}")
    return messages


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description='Generate daily Telegram digest as Telegraph page.')
    parser.add_argument('--startdate', type=str, help='Start datetime YYYY-MM-DD or YYYY-MM-DD HH:MM (UTC)')
    parser.add_argument('--enddate', type=str, help='End datetime YYYY-MM-DD or YYYY-MM-DD HH:MM (UTC)')
    args = parser.parse_args()

    def parse_dt(s):
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        raise ValueError(f"Unrecognized date format: {s}")

    if args.startdate and args.enddate:
        start_date = parse_dt(args.startdate)
        end_date = parse_dt(args.enddate)
        if len(args.enddate) == 10:
            end_date = end_date.replace(hour=23, minute=59, second=59)
    else:
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(hours=24)

    logging.info(f"Digest period: {start_date} -> {end_date}")

    await client.start(phone=PHONE_NUMBER)
    logging.info("Connected to Telegram")

    messages_by_channel = {}
    for username in CHANNEL_USERNAMES:
        msgs = await fetch_messages(username, start_date, end_date)
        if msgs:
            messages_by_channel[username] = msgs

    if not messages_by_channel:
        logging.error("No messages fetched from any channel.")
        await client.disconnect()
        return

    logging.info("Generating digest via Claude...")
    digest = await create_digest(messages_by_channel, start_date, end_date)

    if not digest:
        logging.error("Failed to generate digest.")
        await client.disconnect()
        return

    page_url = publish_to_telegraph(digest)
    logging.info(f"Telegraph page: {page_url}")

    target = int(TARGET_CHANNEL) if TARGET_CHANNEL.lstrip('-').isdigit() else TARGET_CHANNEL
    date_str = start_date.strftime('%d.%m.%Y')
    await client.send_message(target, f"📰 דיג'סט יומי — {date_str}\n{page_url}")

    await client.disconnect()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
