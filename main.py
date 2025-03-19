import logging
from logging.handlers import RotatingFileHandler
from seleniumbase import SB
from selenium.webdriver.common.by import By
import platform
import requests
import os
import json
import subprocess
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("gmgnscraper.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"),  # 1MB
    ],
)
logger = logging.getLogger(__name__)


class GmgnScraper:
    def __init__(self):
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.url = "https://gmgn.ai/defi/quotation/v1/rank/sol/pump/1h?soaring=true"
        self.cache_file = "sent_tokens.json"
        self.load_cache()

    def load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                logger.debug(f"Loading cache from {self.cache_file}")
                with open(self.cache_file, "r") as f:
                    self.sent_tokens = json.load(f)
                # Clean up old entries (older than 24 hours)
                current_time = datetime.now().timestamp()
                old_count = len(self.sent_tokens)
                self.sent_tokens = {
                    token: timestamp
                    for token, timestamp in self.sent_tokens.items()
                    if current_time - timestamp < 24 * 3600
                }
                logger.debug(f"Cleaned up cache: removed {old_count - len(self.sent_tokens)} old entries")
            else:
                logger.debug("Cache file not found, creating new cache")
                self.sent_tokens = {}
        except Exception as e:
            logger.error(f"Error loading cache from {self.cache_file}: {str(e)}", exc_info=True)
            self.sent_tokens = {}

    def save_cache(self):
        try:
            logger.debug(f"Saving {len(self.sent_tokens)} entries to cache")
            with open(self.cache_file, "w") as f:
                json.dump(self.sent_tokens, f)
            logger.debug("Cache saved successfully")
        except Exception as e:
            logger.error(f"Error saving cache to {self.cache_file}: {str(e)}", exc_info=True)

    def was_token_sent_recently(self, token_address):
        current_time = datetime.now().timestamp()
        if token_address in self.sent_tokens:
            # Check if token was sent in the last 24 hours
            return current_time - self.sent_tokens[token_address] < 24 * 3600
        return False

    def mark_token_as_sent(self, token_address):
        self.sent_tokens[token_address] = datetime.now().timestamp()
        self.save_cache()

    def send_to_telegram(self, coin_data):
        token_address = "https://dexscreener.com/solana/" + coin_data["address"]
        logger.info(f"Preparing to send Telegram message for token {coin_data['symbol']} ({token_address})")
        message_format = """
        🔥 <b>The Next 100x</b>

💎 <b>Coin:</b> {}
💰 <b>Market Cap:</b> {}
🔗 <b>Contract Address: </b> <a href="{}">{}</a>
"""
        send_message_url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        params = {
            "chat_id": self.telegram_chat_id,
            "text": message_format.format(
                coin_data["symbol"],
                coin_data["usd_market_cap"],
                token_address,
                coin_data["address"],
            ),
            "parse_mode": "HTML",
        }
        try:
            response = requests.get(send_message_url, params=params)
            response.raise_for_status()
            logger.info(f"Successfully sent Telegram message for {coin_data['symbol']}")
            self.mark_token_as_sent(token_address)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram message for {coin_data['symbol']}: {str(e)}", exc_info=True)

    def cleanup_temp_files(self):
        try:
            if platform.system() == "Linux":
                try:
                    subprocess.run(["pkill", "-f", "chrome"], check=False)
                    subprocess.run(["pkill", "-f", "chromedriver"], check=False)
                    logger.debug("Cleaned up Chrome processes")
                except Exception as e:
                    logger.error(f"Error cleaning up Chrome processes: {str(e)}", exc_info=True)

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)

    def scrape(self):
        logger.info("Starting scraping process")
        try:
            with SB(uc=True, incognito=True, xvfb=True, undetectable=True, page_load_strategy="eager") as sb:
                try:
                    logger.info(f"Opening URL: {self.url}")
                    sb.uc_open_with_reconnect(self.url, 5)

                    logger.info("Handling captcha based on platform")
                    if platform.system() == "Linux":
                        logger.debug("Linux platform detected, using uc_gui_click_captcha")
                        sb.uc_gui_click_captcha()
                    else:
                        logger.debug("Non-Linux platform detected, using uc_gui_handle_captcha")
                        sb.uc_gui_handle_captcha()

                    json_response = sb.find_element(f"body > pre").text
                    json_response = json.loads(json_response)
                    coins_data = json_response["data"]["rank"][:4]

                    for coin in coins_data:
                        self.send_to_telegram(coin)

                finally:
                    try:
                        sb.clear_session_storage()
                        sb.delete_all_cookies()
                        sb.driver.quit()
                    except Exception as e:
                        logger.error(f"Error during browser cleanup: {e}")

        except Exception as e:
            logger.error(f"Scraping failed: {str(e)}", exc_info=True)
            raise
        finally:
            self.cleanup_temp_files()


if __name__ == "__main__":
    try:
        scraper = GmgnScraper()
        scraper.scrape()
    except Exception as e:
        logger.error(f"Application failed: {str(e)}", exc_info=True)
    finally:
        if "scraper" in locals():
            scraper.cleanup_temp_files()
