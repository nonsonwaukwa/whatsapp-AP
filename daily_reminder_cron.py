import os
import logging
import requests
from datetime import datetime
from urllib.parse import urljoin
from flask import Flask

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app for health check
app = Flask(__name__)

@app.route('/health')
def health_check():
    return {"status": "healthy"}, 200

def trigger_daily_reminder():
    """Trigger the daily reminder by calling the webhook endpoint."""
    try:
        # Log startup
        logger.info("Starting daily reminder cron job")
        
        # Get and log environment variables (without exposing secrets)
        app_url = os.environ.get('APP_URL', '').rstrip('/')
        has_cron_secret = bool(os.environ.get('CRON_SECRET'))
        logger.info(f"Environment check - APP_URL exists: {bool(app_url)}, CRON_SECRET exists: {has_cron_secret}")
        
        if not app_url or not has_cron_secret:
            logger.error("Missing required environment variables (APP_URL or CRON_SECRET)")
            return False
        
        # Temporarily commenting out weekend check for testing
        # if datetime.now().weekday() >= 5:  # 5 and 6 are Saturday and Sunday
        #     logger.info("Skipping reminder - it's the weekend")
        #     return True
            
        # Construct proper URL
        webhook_url = urljoin(app_url, '/cron/daily-reminder')
        logger.info(f"Constructed webhook URL: {webhook_url}")
        
        # Make the request to the webhook
        logger.info("Attempting to send request...")
        response = requests.get(
            webhook_url,
            headers={"X-Railway-Secret": os.environ.get('CRON_SECRET')},
            timeout=30
        )
        
        logger.info(f"Response received - Status code: {response.status_code}")
        
        if response.status_code == 200:
            logger.info("Daily reminder triggered successfully")
            logger.info(f"Response content: {response.text}")
            return True
        else:
            logger.error(f"Failed to trigger daily reminder. Status code: {response.status_code}")
            logger.error(f"Response content: {response.text}")
            logger.error(f"Request URL: {webhook_url}")
            logger.error("Headers sent: X-Railway-Secret: [REDACTED]")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        return False

if __name__ == "__main__":
    try:
        logger.info("=== Daily Reminder Cron Starting ===")
        
        # Log environment
        logger.info(f"Python version: {os.sys.version}")
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"Files in current directory: {os.listdir('.')}")
        
        # Skip execution during build time
        if os.environ.get('RAILWAY_ENVIRONMENT') == 'nixpacks':
            logger.info("Build environment detected, skipping execution")
            exit(0)
        
        # Check environment variables
        if not os.environ.get('APP_URL'):
            logger.error("APP_URL environment variable is not set")
            exit(1)
        if not os.environ.get('CRON_SECRET'):
            logger.error("CRON_SECRET environment variable is not set")
            exit(1)
        
        # Start Flask app for health checks
        port = int(os.environ.get('PORT', 3000))
        app.run(host='0.0.0.0', port=port)
        
        success = trigger_daily_reminder()
        logger.info("=== Daily Reminder Cron Finished ===")
        # Exit with appropriate status code
        exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"Critical error in main: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        exit(1) 