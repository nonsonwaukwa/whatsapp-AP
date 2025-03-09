import os
import json
import requests
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import sys

# Constants
TOKEN = "EAAIZBzoc3LFoBO8InaJADNy5rZC05apTlkkgFmM5c2PsyaXnpd3Ffk4db4TqwJmXGmdAZBCa5OqgNOSCFT8D9rxNrxImgyuiZBbA1eGcjaTqgrT8Xo8U068tUN5wZBhC2kie2ZBF3roTzTGiy495U9b1uIbeXy7OID8FykqctZBhmfq55eYEWEic4QA5WDWCCFmVAZDZD"
WHATSAPP_NUMBER = "556928390841439"
RECIPIENT_NO = "2348023672476"
SHEET_ID = "1mbO96co-uwzwcpX6UUGnmeZ0-YIl8gan7iA6-2iZ_68"
SHEET_NAME = "Weekly Plan"  # Explicitly define sheet name
BASE_URL = f"https://graph.facebook.com/v17.0/{WHATSAPP_NUMBER}/messages"

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']  # Full access to Sheets

def get_google_sheets_service():
    """Get or create Google Sheets service with proper authentication."""
    creds = None
    # The file token.pickle stores the user's access and refresh tokens
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Make sure you have downloaded the OAuth 2.0 Client ID credentials
            # for a Desktop application from Google Cloud Console
            credentials_file = 'credentials.json'  # Change this to your credentials file name
            if not os.path.exists(credentials_file):
                raise FileNotFoundError(
                    f"Credentials file '{credentials_file}' not found. "
                    "Please download OAuth 2.0 Client ID credentials for a Desktop application "
                    "from Google Cloud Console and save it as 'credentials.json'"
                )
            
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('sheets', 'v4', credentials=creds)

def send_message(message):
    """Send a WhatsApp message using the Facebook Graph API."""
    payload = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_NO,
        "type": "text",
        "text": {"body": message}
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(BASE_URL, json=payload, headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as error:
        print(f"Error sending message: {error}")
        return False

def send_sunday_planning_message():
    """Send the Sunday planning message requesting tasks for the week."""
    message = """Hey! It's Sunday 😊. Please set your 3 goals for each day this week (Monday–Friday). Reply in this format:

Monday: Task 1, Task 2, Task 3
Tuesday: Task 1, Task 2, Task 3
Wednesday: Task 1, Task 2, Task 3
Thursday: Task 1, Task 2, Task 3
Friday: Task 1, Task 2, Task 3"""
    
    return send_message(message)

def send_daily_reminder():
    """Send daily reminder based on tasks from Google Sheets."""
    try:
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        # Get the sheet data - explicitly reference the Weekly Plan sheet
        range_name = f"{SHEET_NAME}!A1:G"  # Include columns A through G to capture all task data
        result = sheet.values().get(
            spreadsheetId=SHEET_ID,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        if not values:
            print('No data found in sheet.')
            return

        today = datetime.now().strftime('%Y-%m-%d')
        
        # Skip header row and process data
        for row in values[1:]:
            if len(row) >= 4:  # Ensure row has enough columns
                sheet_date = row[1]  # Date column
                
                # Convert sheet_date to string format for comparison
                if isinstance(sheet_date, datetime):
                    sheet_date = sheet_date.strftime('%Y-%m-%d')
                
                if sheet_date == today:
                    # Extract tasks (next three columns after date)
                    tasks = [task for task in row[2:5] if task.strip()]
                    
                    if tasks:
                        message = f"Hey! 😊 Here are your tasks for today:\n- " + "\n- ".join(tasks) + "\n\nCheck in later! 💪"
                        send_message(message)
                    break

    except Exception as e:
        print(f"Error in send_daily_reminder: {e}")

def is_sunday():
    """Check if today is Sunday."""
    return datetime.now().weekday() == 6

if __name__ == "__main__":
    # Check if running in test mode
    if len(sys.argv) > 1 and sys.argv[1] == "--test-sunday":
        print("Running in test mode - sending Sunday planning message...")
        if send_sunday_planning_message():
            print("Successfully sent Sunday planning message!")
        else:
            print("Failed to send Sunday planning message.")
    else:
        # Normal operation mode
        if is_sunday():
            print("It's Sunday! Sending weekly planning message...")
            if send_sunday_planning_message():
                print("Successfully sent Sunday planning message!")
            else:
                print("Failed to send Sunday planning message.")
        else:
            print("Running daily reminder...")
            send_daily_reminder() 