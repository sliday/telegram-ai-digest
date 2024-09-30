
# Telegram AI Digest Generator

![telegram-ai-digest-generator](https://github.com/user-attachments/assets/f35701c3-55de-4f5d-b287-8012b901a2eb)

_Sponsored by [t.me/aizvestia](https://t.me/aizvestia)_

Python script fetches Telegram channel messages, processes them into a digest via Claude AI, generates an image with Replicate API, and sends both to user's saved Telegram messages.

## Features

- **Telegram API**: Fetches messages from a Telegram channel.
- **Claude AI**: Generates a digest from the combined messages.
- **Replicate API**: Generates an image based on the digest (FLUX + LoRa).
- **Asyncio**: Utilizes asynchronous programming to handle API requests efficiently.

## Requirements

The following Python libraries are required to run the script:

- `aiohttp`
- `telethon`
- `pytz`
- `replicate`
- `requests`
- `argparse`
- `logging`

You can install the required libraries by running:

```bash
pip install -r requirements.txt
```

## Setup

1. Clone the repository and navigate to the project directory.

2. Create a `.env` file in the root directory to store your environment variables.

Example `.env` file:

```
API_ID=<your_telegram_api_id>
API_HASH=<your_telegram_api_hash>
PHONE_NUMBER=<your_phone_number>
CHANNEL_USERNAME=<your_telegram_channel_username>
CLAUDE_API_KEY=<your_claude_api_key>
REPLICATE_API_TOKEN=<your_replicate_api_token>
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

To run the script, use the following command:

```bash
python digest.py
```

### Date Range Arguments

This script enables custom date ranges for digests via `start_date` and `end_date` arguments in `YYYY-MM-DD` format, defining the message fetch period. Without arguments, it defaults to the last 7 days, allowing for various timeframes like weekly reports or project milestones.

Example usage with date range:

```bash
python digest.py --start_date 2023-09-01 --end_date 2023-09-07
```

In this example, the script fetches messages from the specified Telegram channel between September 1-7, 2023. Without these arguments, it generates a digest for the last 7 days by default.

The script will:
1. Load the environment variables from the `.env` file.
2. Fetch messages from the specified Telegram channel.
3. Process the messages into a digest using the Claude AI API.
4. Generate an image using the Replicate API.
5. Send the digest (with the generated image) to your saved messages on Telegram.

## Environment Variables

The script requires the following environment variables to be set in a `.env` file:

- `API_ID`: Your Telegram API ID.
- `API_HASH`: Your Telegram API hash.
- `PHONE_NUMBER`: Your phone number registered with Telegram.
- `CHANNEL_USERNAME`: The username of the Telegram channel to fetch messages from.
- `CLAUDE_API_KEY`: API key for Claude AI to generate text digest.
- `REPLICATE_API_TOKEN`: API token for Replicate API to generate images.

## How to Obtain API Tokens

### Telegram API Credentials

1. Go to [Telegram's my.telegram.org](https://my.telegram.org/) and log in with your Telegram account.
2. Navigate to the "API development tools" section.
3. Create a new application and you will receive your `API_ID` and `API_HASH`.
4. Use your Telegram-registered phone number for the `PHONE_NUMBER` value.
5. Find the username of the Telegram channel you wish to fetch messages from and add it to `CHANNEL_USERNAME`.

### Claude AI API Key

1. Register or sign in to Claude AI (from Anthropic) via their developer console.
2. Go to the API section and generate your API key.
3. Use this key as `CLAUDE_API_KEY` in your `.env` file.

### Replicate API Token

1. Sign up or log in at [Replicate](https://replicate.com/).
2. Navigate to the account settings and find your API token.
3. Use the API token as `REPLICATE_API_TOKEN` in your `.env` file.

## Logging

The script uses the built-in `logging` library to provide detailed logs about the execution. Logs are displayed in the console, including warnings and errors related to missing environment variables or failed API requests.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
