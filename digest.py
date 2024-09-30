import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from pathlib import Path
from telethon import TelegramClient
from pytz import UTC
import replicate
import requests
from io import BytesIO
import re
import subprocess
import argparse
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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

# Telegram API credentials
try:
    API_ID = int(get_env_variable('API_ID'))
    API_HASH = get_env_variable('API_HASH')
    PHONE_NUMBER = get_env_variable('PHONE_NUMBER')
    CHANNEL_USERNAME = get_env_variable('CHANNEL_USERNAME')
    CLAUDE_API_KEY = get_env_variable('CLAUDE_API_KEY')
    REPLICATE_API_TOKEN = get_env_variable('REPLICATE_API_TOKEN')
except ValueError as e:
    logging.error(f"Environment variable error: {str(e)}")
    raise

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN
logging.info(f"Replicate API token: {REPLICATE_API_TOKEN[:5]}...{REPLICATE_API_TOKEN[-5:]}")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

logging.debug(f"API_ID is set: {'Yes' if API_ID else 'No'}")
logging.debug(f"API_HASH is set: {'Yes' if API_HASH else 'No'}")
logging.debug(f"PHONE_NUMBER is set: {'Yes' if PHONE_NUMBER else 'No'}")
logging.debug(f"CHANNEL_USERNAME: {CHANNEL_USERNAME}")

required_vars = ['API_ID', 'API_HASH', 'PHONE_NUMBER', 'CHANNEL_USERNAME', 'CLAUDE_API_KEY', 'REPLICATE_API_TOKEN']
missing_vars = [var for var in required_vars if not globals().get(var)]

if missing_vars:
    raise ValueError(f"The following required environment variables are not set: {', '.join(missing_vars)}")

MAX_REQUESTS_PER_MINUTE = 30
REQUEST_INTERVAL = 60 / MAX_REQUESTS_PER_MINUTE

semaphore = asyncio.Semaphore(MAX_REQUESTS_PER_MINUTE)

client = TelegramClient('session', API_ID, API_HASH)

async def call_claude_api(session, prompt, retry=True):
    headers = {
        "Content-Type": "application/json",
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": "claude-3-5-sonnet-20240620",
        "max_tokens": 4092,
        "messages": [{"role": "user", "content": prompt}]
    }

    async with semaphore:
        try:
            logging.debug(f"Calling Claude API with prompt length: {len(prompt)}")
            async with session.post(CLAUDE_API_URL, json=payload, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    logging.debug("Claude API call successful")
                    return result['content'][0]['text']
                else:
                    error_text = await response.text()
                    logging.error(f"API call failed with status {response.status}: {error_text}")
                    if retry:
                        logging.info("Retrying API call...")
                        await asyncio.sleep(REQUEST_INTERVAL)
                        return await call_claude_api(session, prompt, retry=False)
                    return None
        except Exception as e:
            logging.error(f"Error in API call: {str(e)}")
            if retry:
                logging.info("Retrying API call...")
                await asyncio.sleep(REQUEST_INTERVAL)
                return await call_claude_api(session, prompt, retry=False)
            return None
        finally:
            await asyncio.sleep(REQUEST_INTERVAL)

def format_date_range(start_date, end_date):
    months_ru = [
        'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
    ]
    
    if start_date.month == end_date.month and start_date.year == end_date.year:
        return f"{start_date.day}-{end_date.day} {months_ru[end_date.month - 1]}"
    else:
        return f"{start_date.day} {months_ru[start_date.month - 1]} - {end_date.day} {months_ru[end_date.month - 1]}"

async def create_digest(messages, start_date, end_date):
    if not messages:
        logging.error("No messages to create digest from")
        return "No messages were found to create a digest."
    
    date_range = format_date_range(start_date, end_date)
    logging.debug(f"Formatted date range: {date_range}")
    
    async with aiohttp.ClientSession() as session:
        prompt = f"""Create a digest for Telegram messages from {date_range}. Summarize key points, include original post links, apply links to the key word in the original post. DO NOT use "learn more" or "подробнее". Use Russian language.
Format:
- Title: "Дайджест ИИзвестий за неделю {date_range}"
- Jump to content, no intro, no outro, no "Here's the digest in the requested format:" kind of text. 
- Brief intro (2-3 sentences)
- Sections with emojis (e.g., LLM, Генеративные модели, Подборки курсов, Всякая-всячина)
- Use dash (-) for news items, NO extra line breaks between items:
```
EMOJI Title
- News1
- News2
- News3
```
- Include key aspects and brief comments (2-3 sentences max)
- Link keywords to original posts
- End with: "#ИИзвестия\n\n@aizvestia"

Use Telegram Markdown:
**bold**, _italic_, __underline__, ~strikethrough~, ||spoiler||, [inline URL](http://www.example.com/), `code`, ```block code```

Messages to summarize:
"{messages}"

Output pure markdown, be concise, MUST start with content, no intro. Avoid extra line breaks between list items. Use bold for section titles instead of #."""
        digest_markdown = await call_claude_api(session, prompt)
        return digest_markdown

def get_previous_week_range():
    today = datetime.now(UTC)
    if today.weekday() == 6:  # If today is Sunday
        most_recent_monday = today - timedelta(days=6)
        end_date = today
    else:
        most_recent_monday = today - timedelta(days=today.weekday() + 1)
        end_date = most_recent_monday + timedelta(days=6)
    
    start_date = most_recent_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start_date, end_date

async def generate_image_prompt(digest):
    async with aiohttp.ClientSession() as session:
        prompt = f"""Based on this AI news digest, WRITE a concise image prompt for FLUX 1 PRO. The prompt should:
- Be in basic telegraphic English
- Describe a retrofuturistic poster
- Limit description to roughly 512 characters
- Description should NOT include quoted text.
- Include as many characters/objects from the digest as possible
- Incorporate elements of collage and creative papercut application
- Evoke a sense of potpourri (a mixture of diverse elements)
- Mention retrofuturism and techno-optimism
- Be really concise, comma-separate objects from digest.

Sample output, DO NOT, use as reference, borrow structure or ideas, just write your own:
```A retrofuturistic magazine poster, retro-styled, no text, no words, collage, paper-cut, humanoid robot (Unitree G1), AI-generated avatars, stylized brain with circuit patterns, musical notes from headphones, a scientist with AI ideas, people with oversized smartphones, a film reel turning into binary, investment charts, art supplies merging with tech, and a graduation cap with an AI chip.```

AI news digest:
===
{digest}
===

Focus on visual elements and their arrangement. No words, no quotes, no text. Be weird, unorthodox, funny, creative and vivid in your description. Output only the image prompt."""

        image_prompt = await call_claude_api(session, prompt)
        return image_prompt.strip()

def generate_and_save_image(prompt):
    try:
        logging.info(f"Generating image with prompt: {prompt}")
        
        # output = replicate.run(
        #     "black-forest-labs/flux-pro",
        #     input={
        #         "prompt": prompt,
        #         "steps": 28,
        #         "width": 1024,
        #         "aspect_ratio": "4:5",
        #         "height": 1024
        #     }
        # )

        output = replicate.run(
            "lucataco/flux-dev-lora:613a21a57e8545532d2f4016a7c3cfa3c7c63fded03001c2e69183d557a929db",
            input={
                "image": "https://dl.dropboxusercontent.com/scl/fi/nboue50qrkr9iqbbev2wd/TM-1989-Dec-HQ-OCR.jpg?rlkey=p5iiym7m412p4wrrgx5plybeo&dl=0",
                "prompt": prompt,
                "hf_lora": "Fihade/Retro-Collage-Art-Flux-Dev",
                # "hf_lora": "glif/Brain-Melt-Acid-Art",
                "lora_scale": 0.8,
                "num_outputs": 1,
                "aspect_ratio": "4:5",
                "output_format": "webp",
                "guidance_scale": 3.5,
                "output_quality": 80,
                "prompt_strength": 0.91,
                "num_inference_steps": 32
            }
        )     
        
        logging.info(f"Replicate output: {output}")
        
        if isinstance(output, list) and len(output) > 0:
            image_url = output[0]
        elif isinstance(output, str):
            image_url = output
        else:
            logging.error(f"Unexpected output format from Replicate: {output}")
            return None

        # Download the image
        response = requests.get(image_url)
        response.raise_for_status()
        
        # Save the original webp image
        with open("digest_illustration_original.webp", "wb") as f:
            f.write(response.content)
        
        # Convert webp to png using ImageMagick
        try:
            subprocess.run(["convert", "digest_illustration_original.webp", "digest_illustration.png"], check=True)
            logging.info("Image converted successfully")
            return "digest_illustration.png"
        except subprocess.CalledProcessError as e:
            logging.error(f"Error converting image: {e}")
            return "digest_illustration_original.webp"  # Return the original webp if conversion fails
        
    except replicate.exceptions.ReplicateError as e:
        logging.error(f"Replicate API error: {str(e)}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error downloading image: {str(e)}")
    except Exception as e:
        logging.error(f"Error in generate_and_save_image: {str(e)}")
    return None

def remove_extra_line_breaks(text):
    # Remove extra line breaks between list items
    text = re.sub(r'(\n- .+?)\n+(?=\n-)', r'\1', text, flags=re.DOTALL)
    
    # Remove extra line breaks between sections
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text

async def main():
    parser = argparse.ArgumentParser(description='Generate digest for a specific date range.')
    parser.add_argument('--startdate', type=str, required=True, help='Start date in YYYY-MM-DD format')
    parser.add_argument('--enddate', type=str, required=True, help='End date in YYYY-MM-DD format')
    args = parser.parse_args()

    start_date = datetime.strptime(args.startdate, '%Y-%m-%d').replace(tzinfo=UTC)
    end_date = datetime.strptime(args.enddate, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=UTC)

    logging.info(f"Using phone number: {PHONE_NUMBER}")
    await client.start(phone=PHONE_NUMBER)
    logging.info("Connected to Telegram")

    channel = await client.get_entity(CHANNEL_USERNAME)
    logging.info(f"Retrieved channel entity: {channel.title}")

    logging.info(f"Fetching messages from {start_date.strftime('%Y-%m-%d %H:%M:%S')} to {end_date.strftime('%Y-%m-%d %H:%M:%S')}")

    messages = []
    message_count = 0
    async for message in client.iter_messages(channel, offset_date=end_date, limit=None):
        if message.date < start_date:
            break
        if start_date <= message.date <= end_date:
            message_link = None
            if message.text:
                message_link = f"https://t.me/{channel.username}/{message.id}"
                messages.append(f"{message.date.strftime('%Y-%m-%d %H:%M')} - {message.text}\nMessage link: {message_link}")
                message_count += 1
                logging.debug(f"Fetched message: Date={message.date}, Has text: True, Message link: {message_link}")
            else:
                logging.debug(f"Skipped message: Date={message.date}, Has text: False")

    messages.reverse()
    logging.info(f"Total messages fetched: {message_count}")

    if not messages:
        logging.error("No messages were fetched from the channel for the specified week")
        return

    combined_messages = "\n\n".join(messages)
    logging.debug(f"Combined messages length: {len(combined_messages)}")

    logging.info("Creating digest using Claude AI...")
    logging.debug(f"Start date: {start_date}, End date: {end_date}")
    digest_markdown = await create_digest(combined_messages, start_date, end_date)

    if digest_markdown:
        # Apply post-processing to remove extra line breaks
        digest_markdown = remove_extra_line_breaks(digest_markdown)
        
        logging.debug(f"Processed digest start: {digest_markdown[:500]}")

        image_prompt = await generate_image_prompt(digest_markdown)
        logging.info(f"Generated image prompt: {image_prompt}")

        logging.info(f"Using Replicate API token: {REPLICATE_API_TOKEN[:5]}...{REPLICATE_API_TOKEN[-5:]}")
        
        image_path = generate_and_save_image(image_prompt)
        
        if image_path:
            logging.info(f"Generated image saved at: {image_path}")

            try:
                # Send the image with the digest text as caption
                await client.send_file('me', image_path, caption=digest_markdown, parse_mode='md')
                logging.info("Digest image with text caption sent to Saved Messages")
            except Exception as e:
                logging.error(f"Error sending image with caption: {str(e)}")
                logging.warning("Sending digest as text only.")
                await client.send_message('me', digest_markdown, parse_mode='md')
                logging.info("Digest sent to Saved Messages as text only")
        else:
            logging.error("Failed to generate or save image")
            logging.warning("Sending digest as text only.")
            await client.send_message('me', digest_markdown, parse_mode='md')
            logging.info("Digest sent to Saved Messages as text only")

    else:
        logging.error("Failed to create digest")

    await client.disconnect()

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())