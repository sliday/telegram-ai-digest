# Project: Telegram Daily Digest → Telegraph (Instant View)

## What this project does
`digest.py` fetches messages from Telegram channels via Telethon (user account, not bot),
summarizes them with the Claude API, and publishes the result as a Telegraph page.
The Telegraph URL is then sent to a private Telegram channel, where it opens as Instant View.

## Current state of digest.py
The script works end-to-end with the following flow:
1. Connects to Telegram using Telethon (user session, phone auth)
2. Fetches last 24h of messages from one or more channels
3. Calls Claude API (claude-haiku-4-5-20251001) to produce a structured JSON digest
4. Currently builds a PDF with reportlab and sends it via `client.send_file()`

## Your task
Replace steps 4 (PDF generation and send_file) with Telegraph publishing.
Do NOT change any other function. Specifically:

### Remove
- All reportlab imports and `build_pdf()` function
- `client.send_file()` call
- `reportlab` from requirements.txt

### Add: `publish_to_telegraph(digest: dict) -> str`
Publish the digest as a Telegraph page and return the page URL.

Use the `telegraph` Python library (sync):
```
pip install telegraph
```

**Account setup:**
- On first run, create a Telegraph account and save the access token to a file `telegraph_token.txt`
- On subsequent runs, load the token from that file
- Account short_name: `"daily-digest"`, author_name: `"דיג'סט יומי"`

**Page title:** `f"דיג'סט יומי — {digest['date_range']}"`

**Page content** must be built as a list of Telegraph Node objects (dicts).
Telegraph supports these HTML-equivalent tags: `p`, `h3`, `h4`, `a`, `br`, `ul`, `li`, `blockquote`.
Content is RTL Hebrew — add `dir="rtl"` where possible, but note Telegraph node dicts
do not support arbitrary HTML attributes. Structure the content clearly using headings and lists.

Build the content in this exact order:

```
[h3] עדכוני לחימה והסכסוך
  for each big_news item where section == "conflict":
    [h4] {headline}
    [p]  {summary}
    [p]  [a href=link] קישור למקור
  [ul] minor_news items where section == "conflict"
    [li] {headline} — [a href=link] קישור

[h3] פוליטיקה ישראלית
  ... same pattern, section == "politics"

[h3] כותרות נוספות
  ... same pattern, section == "world"
```

Telegraph Node format:
```python
{"tag": "h3", "children": ["some text"]}
{"tag": "p", "children": ["some text"]}
{"tag": "a", "attrs": {"href": "https://..."}, "children": ["קישור למקור"]}
{"tag": "ul", "children": [{"tag": "li", "children": [...]}]}
```
Nested example (link inside paragraph):
```python
{"tag": "p", "children": [
    {"tag": "a", "attrs": {"href": url}, "children": ["קישור למקור"]}
]}
```

### Update: `main()`
Replace:
```python
pdf_path = f"digest_{start_date.strftime('%Y-%m-%d')}.pdf"
build_pdf(digest, pdf_path)
target = int(TARGET_CHANNEL) if TARGET_CHANNEL.lstrip('-').isdigit() else TARGET_CHANNEL
caption = f"Daily Digest — {digest.get('date_range', '')}"
await client.send_file(target, pdf_path, caption=caption)
```
With:
```python
page_url = publish_to_telegraph(digest)
logging.info(f"Telegraph page: {page_url}")
target = int(TARGET_CHANNEL) if TARGET_CHANNEL.lstrip('-').isdigit() else TARGET_CHANNEL
date_str = start_date.strftime('%d.%m.%Y')
await client.send_message(target, f"📰 דיג'סט יומי — {date_str}\n{page_url}")
```

### Update: `create_digest()` prompt
Replace the existing prompt string with this exact prompt:

```
You are creating a structured Hebrew daily news digest from Telegram channel messages.

Date range: {date_str}
Total messages: {total}

Classify every story into one of three sections:
- "conflict": Middle East conflicts, Gaza war, Lebanon, Iran, military operations, hostages
- "politics": Israeli domestic politics, government, Knesset, legal system, parties
- "world": global news, international events, economy, tech, anything else

Within each section, classify as:
- "big_news": significant stories — include headline + 2-3 sentence summary (max 5 items total across all sections)
- "minor_news": smaller updates — headline only (all remaining items)

Rules:
- Write ALL text in Hebrew.
- Be concise. Headlines max 12 words. Summaries max 40 words.
- Preserve the original t.me message link for each item.
- If multiple messages cover the same story, merge them into one item.

Return ONLY a valid JSON object, no markdown fences, no preamble:
{
  "date_range": "<date_str>",
  "big_news": [
    {"headline": "...", "summary": "...", "link": "https://t.me/...", "section": "conflict"},
    {"headline": "...", "summary": "...", "link": "https://t.me/...", "section": "politics"},
    {"headline": "...", "summary": "...", "link": "https://t.me/...", "section": "world"}
  ],
  "minor_news": [
    {"headline": "...", "link": "https://t.me/...", "section": "conflict"},
    {"headline": "...", "link": "https://t.me/...", "section": "politics"},
    {"headline": "...", "link": "https://t.me/...", "section": "world"}
  ]
}

Messages:
{combined}
```

## .env variables (no changes needed)
```
API_ID=
API_HASH=
PHONE_NUMBER=
CHANNEL_USERNAMES=channel_one,channel_two
TARGET_CHANNEL=-1001234567890
CLAUDE_API_KEY=
```

## requirements.txt (final state)
```
aiohttp
telethon
pytz
anthropic
telegraph
```

## Done when
- `python digest.py` runs without errors
- A Telegraph page is created with Hebrew content structured in three sections
- The page URL is sent as a plain message to the Telegram channel
- Opening the URL in Telegram triggers Instant View
- `telegraph_token.txt` is created on first run and reused on subsequent runs
