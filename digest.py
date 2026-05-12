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
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem
from reportlab.lib.enums import TA_LEFT, TA_CENTER

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

    prompt = f"""You are creating a structured daily news digest from Telegram channel messages.

Date range: {date_str}
Total messages: {total}

Classify each story as either:
- "big_news": significant, impactful stories worth a headline + 2-3 sentence summary (3-7 items max)
- "minor_news": smaller updates, worth a headline only (remaining items)

Write in the same language as the majority of the messages.

Return ONLY a valid JSON object, no markdown fences, no preamble, no explanation:
{{
  "date_range": "{date_str}",
  "big_news": [
    {{"headline": "...", "summary": "...", "link": "https://t.me/..."}},
    ...
  ],
  "minor_news": [
    {{"headline": "...", "link": "https://t.me/..."}},
    ...
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
# PDF generation
# ---------------------------------------------------------------------------

def build_pdf(digest: dict, output_path: str) -> str:
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    base = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DigestTitle',
        parent=base['Normal'],
        fontSize=22,
        leading=28,
        textColor=colors.HexColor('#1a1a2e'),
        alignment=TA_CENTER,
        spaceAfter=4 * mm,
        fontName='Helvetica-Bold',
    )
    date_style = ParagraphStyle(
        'DateRange',
        parent=base['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#888888'),
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
        fontName='Helvetica',
    )
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=base['Normal'],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#444444'),
        fontName='Helvetica-Bold',
        spaceBefore=6 * mm,
        spaceAfter=3 * mm,
    )
    big_headline_style = ParagraphStyle(
        'BigHeadline',
        parent=base['Normal'],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#1a1a2e'),
        fontName='Helvetica-Bold',
        spaceBefore=5 * mm,
        spaceAfter=2 * mm,
    )
    summary_style = ParagraphStyle(
        'Summary',
        parent=base['Normal'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#333333'),
        fontName='Helvetica',
        spaceAfter=1 * mm,
    )
    link_style = ParagraphStyle(
        'Link',
        parent=base['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#0077cc'),
        fontName='Helvetica',
        spaceAfter=4 * mm,
    )
    minor_item_style = ParagraphStyle(
        'MinorItem',
        parent=base['Normal'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#333333'),
        fontName='Helvetica',
    )

    story = []

    story.append(Paragraph("Daily Digest", title_style))
    story.append(Paragraph(digest.get("date_range", ""), date_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#dddddd')))

    big_news = digest.get("big_news", [])
    if big_news:
        story.append(Paragraph("Top Stories", section_style))
        for item in big_news:
            story.append(Paragraph(item.get("headline", ""), big_headline_style))
            if item.get("summary"):
                story.append(Paragraph(item["summary"], summary_style))
            if item.get("link"):
                story.append(Paragraph(
                    f'<a href="{item["link"]}" color="#0077cc">{item["link"]}</a>',
                    link_style
                ))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#eeeeee')))

    minor_news = digest.get("minor_news", [])
    if minor_news:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Also Today", section_style))
        items = []
        for item in minor_news:
            headline = item.get("headline", "")
            link = item.get("link", "")
            text = f'<a href="{link}" color="#0077cc">{headline}</a>' if link else headline
            items.append(ListItem(
                Paragraph(text, minor_item_style),
                leftIndent=10,
                bulletColor=colors.HexColor('#888888')
            ))
        story.append(ListFlowable(items, bulletType='bullet', leftIndent=15, bulletFontSize=8))

    doc.build(story)
    logging.info(f"PDF written to {output_path}")
    return output_path


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
    parser = argparse.ArgumentParser(description='Generate daily Telegram digest as PDF.')
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

    pdf_path = f"digest_{start_date.strftime('%Y-%m-%d')}.pdf"
    build_pdf(digest, pdf_path)

    target = int(TARGET_CHANNEL) if TARGET_CHANNEL.lstrip('-').isdigit() else TARGET_CHANNEL
    caption = f"Daily Digest — {digest.get('date_range', '')}"
    await client.send_file(target, pdf_path, caption=caption)
    logging.info(f"PDF sent to {TARGET_CHANNEL}")

    await client.disconnect()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
