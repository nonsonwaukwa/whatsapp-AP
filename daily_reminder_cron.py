import os
import logging
import requests
from datetime import datetime
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def trigger_energy_checkin():
    """Trigger the morning energy level check-in."""
    try:
        # Get the app URL and cron secret from environment
        app_url = os.environ.get('APP_URL', '').rstrip('/')  # Remove trailing slashes
        cron_secret = os.environ.get('CRON_SECRET')
        
        if not app_url or not cron_secret:
            logger.error("Missing required environment variables (APP_URL or CRON_SECRET)")
            return False
            
        # Construct proper URL
        webhook_url = urljoin(app_url, '/send-energy-checkin')
        logger.info(f"Sending request to: {webhook_url}")
        
        # Make the request to the webhook
        response = requests.get(
            webhook_url,
            headers={"X-Railway-Secret": cron_secret},
            timeout=30  # 30 second timeout
        )
        
        if response.status_code == 200:
            logger.info("Energy check-in triggered successfully")
            return True
        else:
            logger.error(f"Failed to trigger energy check-in. Status code: {response.status_code}")
            logger.error(f"Response: {response.text}")
            # Print more detailed error information
            logger.error(f"Request URL: {webhook_url}")
            logger.error("Headers sent: X-Railway-Secret: [REDACTED]")
            try:
                error_data = response.json()
                logger.error(f"Detailed error: {error_data}")
            except:
                logger.error(f"Raw response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error triggering energy check-in: {str(e)}")
        return False

if __name__ == "__main__":
    # Skip execution during build time
    if os.environ.get('RAILWAY_ENVIRONMENT') == 'nixpacks':
        logger.info("Build environment detected, skipping execution")
        exit(0)
    
    # Check if we have the required environment variables
    if not os.environ.get('APP_URL'):
        logger.error("APP_URL environment variable is not set")
        exit(1)
    if not os.environ.get('CRON_SECRET'):
        logger.error("CRON_SECRET environment variable is not set")
        exit(1)
    
    # First trigger the energy check-in
    success = trigger_energy_checkin()
    # Exit with appropriate status code
    exit(0 if success else 1) 