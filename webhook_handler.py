from flask import Flask, request, jsonify
import re
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import os
import json
import logging
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
import requests
from collections import OrderedDict
import time
from deepgram import Deepgram

app = Flask(__name__)

# Load environment variables
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
CRON_SECRET = os.environ.get('CRON_SECRET')

if not VERIFY_TOKEN:
    app.logger.error("VERIFY_TOKEN not set in environment variables!")
    VERIFY_TOKEN = "your_verify_token_here"  # fallback for development

# Configure Deepgram
DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY')
if DEEPGRAM_API_KEY:
    deepgram = Deepgram(DEEPGRAM_API_KEY)
    app.logger.info("Deepgram API key configured successfully")
else:
    app.logger.error("DEEPGRAM_API_KEY not set in environment variables!")

# Configure logging
logging.basicConfig(level=logging.INFO)
# Create logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')
# Add file handler
file_handler = RotatingFileHandler('logs/webhook.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Webhook startup')

# Constants
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']  # Full access to read and write
SHEET_ID = os.environ.get('SHEET_ID', "1mbO96co-uwzwcpX6UUGnmeZ0-YIl8gan7iA6-2iZ_68")
SHEET_NAME = "Weekly Plan"

# Constants for mood tracking
MOOD_SHEET_NAME = "Mood Tracker"
MOOD_HEADERS = [
    "Date",
    "Time",
    "Voice Note Transcription",
    "Mood Score",
    "Primary Emotion",
    "Secondary Emotions",
    "Key Topics",
    "Energy Level",
    "Action Items",
    "Follow-up Needed"
]

# WhatsApp API credentials
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')
RECIPIENT_PHONE_NUMBER = os.environ.get('RECIPIENT_PHONE_NUMBER')

# Log startup information
app.logger.info(f"Starting with VERIFY_TOKEN: {VERIFY_TOKEN}")
app.logger.info("WhatsApp configuration:")
app.logger.info(f"WHATSAPP_TOKEN set: {bool(WHATSAPP_TOKEN)}")
app.logger.info(f"PHONE_NUMBER_ID set: {bool(PHONE_NUMBER_ID)}")
app.logger.info(f"RECIPIENT_PHONE_NUMBER set: {bool(RECIPIENT_PHONE_NUMBER)}")

# Define the column headers
HEADERS = ["Day", "Date", "Task 1", "Task 1 Status", "Task 2", "Task 2 Status", "Task 3", "Task 3 Status"]

# Add a simple message cache to prevent duplicate processing
# Using OrderedDict as a simple LRU cache
MESSAGE_CACHE = OrderedDict()
MESSAGE_CACHE_MAX_SIZE = 100
MESSAGE_CACHE_TTL = 300  # 5 minutes in seconds

# Add to the constants at the top of the file
CHECKIN_CACHE = OrderedDict()
CHECKIN_CACHE_TTL = 300  # 5 minutes

def is_duplicate_message(message_id):
    """Check if a message has been recently processed."""
    current_time = time.time()
    
    # Clean old entries
    for mid, timestamp in list(MESSAGE_CACHE.items()):
        if current_time - timestamp > MESSAGE_CACHE_TTL:
            MESSAGE_CACHE.pop(mid)
    
    # Check if message is in cache
    if message_id in MESSAGE_CACHE:
        return True
    
    # Add to cache
    MESSAGE_CACHE[message_id] = current_time
    
    # Maintain cache size
    if len(MESSAGE_CACHE) > MESSAGE_CACHE_MAX_SIZE:
        MESSAGE_CACHE.popitem(last=False)
    
    return False

def get_google_sheets_service():
    """Get or create Google Sheets service with proper authentication."""
    try:
        # For Railway deployment, use service account credentials from environment variable
        if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON'):
            import json
            from google.oauth2 import service_account
            
            # Get credentials from environment variable
            creds_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
            creds_dict = json.loads(creds_json)
            
            # Create credentials from dictionary
            creds = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=SCOPES
            )
            app.logger.info("Successfully loaded Google credentials from environment variable")
        else:
            # Local development fallback
            credentials_file = 'kamsi-200302-89f3b687f719.json'
            if not os.path.exists(credentials_file):
                raise FileNotFoundError(
                    f"Credentials file '{credentials_file}' not found and "
                    "GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not set. "
                    "Please configure Google credentials properly."
                )
            
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        app.logger.error(f"Error in get_google_sheets_service: {str(e)}")
        raise

def initialize_sheet_headers(service):
    """Initialize the sheet with headers if they don't exist."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_NAME}!A1:H1"  # Updated to include all 8 columns
        ).execute()
        
        values = result.get('values', [])
        
        if not values or values[0] != HEADERS:
            body = {
                'values': [HEADERS]
            }
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range=f"{SHEET_NAME}!A1:H1",  # Updated to include all 8 columns
                valueInputOption='RAW',
                body=body
            ).execute()
            app.logger.info("Sheet headers initialized successfully")
            
    except Exception as e:
        app.logger.error(f"Error initializing headers: {str(e)}")
        raise

def parse_tasks(message_text):
    """Parse the tasks from the message text into a structured format."""
    try:
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        tasks = {}
        
        # Log the incoming message
        app.logger.info(f"Parsing message: {message_text}")
        
        # Split the message into lines and process each line
        lines = message_text.strip().split('\n')
        for line in lines:
            for day in days:
                if line.lower().startswith(day.lower()):
                    # Extract tasks after the colon
                    tasks_part = line.split(':', 1)[1] if ':' in line else ''
                    # Split tasks by comma and clean them
                    day_tasks = [task.strip() for task in tasks_part.split(',') if task.strip()]
                    tasks[day] = day_tasks
                    app.logger.debug(f"Parsed tasks for {day}: {day_tasks}")
                    break
        
        if not tasks:
            app.logger.warning("No tasks were parsed from the message")
        
        return tasks
    except Exception as e:
        app.logger.error(f"Error parsing tasks: {str(e)}")
        raise

def get_monday_date():
    """Get the date of the next or current Monday."""
    today = datetime.now()
    days_until_monday = (0 - today.weekday()) % 7
    return today + timedelta(days=days_until_monday)

def save_tasks_to_sheets(tasks):
    """Save the parsed tasks to Google Sheets by appending to existing data."""
    try:
        service = get_google_sheets_service()
        
        # Initialize headers if needed
        initialize_sheet_headers(service)
        
        # Get the current sheet data to find the last row
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_NAME}!A:H"  # Get all rows
        ).execute()
        
        values = result.get('values', [])
        next_row = len(values) + 1  # Next available row (1-indexed)
        
        # Prepare the data for Google Sheets
        monday = get_monday_date()
        rows = []
        
        for day, day_tasks in tasks.items():
            current_date = monday + timedelta(days=['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'].index(day))
            date_str = current_date.strftime('%Y-%m-%d')
            
            # Create row with tasks and empty status columns
            row = [day, date_str]  # Start with day and date
            
            # Add each task with its status column
            for i in range(3):
                if i < len(day_tasks):
                    row.extend([day_tasks[i], ''])  # Task and empty status
                else:
                    row.extend(['', ''])  # Empty task and status
            
            rows.append(row)
            app.logger.debug(f"Prepared row for {day}: {row}")
        
        # Prepare the update
        body = {
            'values': rows
        }
        
        # Calculate the range for the new rows
        start_row = next_row
        end_row = next_row + len(rows) - 1
        range_name = f"{SHEET_NAME}!A{start_row}:H{end_row}"
        
        # Append the new rows
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()
        
        app.logger.info(f"Successfully appended {len(rows)} days of tasks to sheet starting at row {start_row}")
        return True
    except Exception as e:
        app.logger.error(f"Error saving to sheets: {str(e)}")
        return False

@app.route('/')
def home():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """Handle webhook verification from WhatsApp."""
    # Log all request parameters for debugging
    app.logger.info("Received webhook verification request")
    app.logger.info(f"Query parameters: {request.args}")
    
    # Get verification parameters
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    app.logger.info(f"Mode: {mode}")
    app.logger.info(f"Token received: {token}")
    app.logger.info(f"Challenge: {challenge}")
    app.logger.info(f"Expected token: {VERIFY_TOKEN}")

    if not mode or not token:
        app.logger.error("Missing mode or token")
        return 'Missing parameters', 400

    if mode == 'subscribe' and token == VERIFY_TOKEN:
        app.logger.info("Webhook verified successfully")
        if not challenge:
            app.logger.error("Missing challenge parameter")
            return 'Missing challenge', 400
        return challenge
    else:
        app.logger.warning(f"Webhook verification failed. Mode: {mode}, Token match: {token == VERIFY_TOKEN}")
        return 'Forbidden', 403

# Add a test endpoint to verify the VERIFY_TOKEN
@app.route('/test-webhook-token')
def test_webhook_token():
    """Test endpoint to verify the webhook token configuration."""
    return jsonify({
        'status': 'configured',
        'verify_token': VERIFY_TOKEN,
        'environment': os.environ.get('RAILWAY_ENVIRONMENT', 'development')
    })

def parse_status_update(message_text):
    """Parse the status update message into a structured format."""
    try:
        # Check if this is a status update message
        if not message_text.strip().startswith('Status Update:'):
            return None
            
        app.logger.info("Parsing status update message")
        
        # Split the message into lines and process each line
        lines = message_text.strip().split('\n')
        updates = []
        
        for line in lines[1:]:  # Skip the "Status Update:" header
            line = line.strip()
            if not line:  # Skip empty lines
                continue
                
            # Match the format: "1. Task: [emoji] - note"
            match = re.match(r'(\d+)\.\s*([^:]+):\s*([✅🟡❌])\s*-?\s*(.*)', line)
            if match:
                task_num = int(match.group(1))
                task = match.group(2).strip()
                status = match.group(3)
                note = match.group(4).strip()
                
                status_map = {
                    '✅': 'completed',
                    '🟡': 'in_progress',
                    '❌': 'not_done'
                }
                
                updates.append({
                    'task_num': task_num,
                    'task': task,
                    'status': status_map.get(status, 'unknown'),
                    'note': note
                })
                app.logger.debug(f"Parsed status update: {updates[-1]}")
        
        return updates if updates else None
        
    except Exception as e:
        app.logger.error(f"Error parsing status update: {str(e)}")
        return None

def save_status_updates(updates):
    """Save the status updates to Google Sheets."""
    try:
        if not updates:
            return False
            
        service = get_google_sheets_service()
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        # Get all sheet data
        range_name = f"{SHEET_NAME}!A:H"  # Get all rows
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        if not values:
            app.logger.warning('No data found in sheet')
            return False
            
        # Find today's rows and get the most recent one
        today_rows = [(i, row) for i, row in enumerate(values) if len(row) >= 2 and row[1] == today]
        if not today_rows:
            app.logger.error(f"Could not find row for date {today}")
            return False
            
        # Use the most recent row for today
        row_index, _ = today_rows[-1]
        
        # Update status columns (columns 4, 6, and 8 are status columns)
        for update in updates:
            task_num = update['task_num']
            status_col = (task_num - 1) * 2 + 3  # Calculate status column
            
            # Ensure row has enough columns
            while len(values[row_index]) <= status_col:
                values[row_index].append('')
                
            # Update status and note
            status_text = f"{update['status'].upper()}"
            if update['note']:
                status_text += f" - {update['note']}"
            values[row_index][status_col] = status_text
            
        # Update the sheet with all values
        body = {
            'values': values
        }
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()
        
        app.logger.info("Status updates saved successfully")
        return True
        
    except Exception as e:
        app.logger.error(f"Error saving status updates: {str(e)}")
        return False

def send_checkin_prompt():
    """Send a message prompting the user to send a voice note check-in."""
    message = """🎙️ Voice Check-in Time!

I'm here to listen. Send me a voice note telling me about:
• How you're feeling right now
• What's on your mind
• Your energy levels
• Anything you need help with

Take your time, I'm here to listen and understand. 🤗"""
    
    return send_message(message)

@app.route('/request-checkin')
def trigger_checkin_prompt():
    """Endpoint to manually trigger a check-in prompt."""
    try:
        if send_checkin_prompt():
            return jsonify({
                'status': 'success',
                'message': 'Check-in prompt sent successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send check-in prompt'
            }), 400
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests from WhatsApp."""
    try:
        data = request.get_json()
        app.logger.info(f"Received webhook data: {data}")
        
        # Extract the message from the WhatsApp webhook payload
        changes = data.get('entry', [{}])[0].get('changes', [{}])[0]
        value = changes.get('value', {})
        message = value.get('messages', [{}])[0] if value.get('messages') else {}
        
        if not message:
            return jsonify({'status': 'success', 'message': 'No message in webhook'}), 200
        
        # Check for duplicate message
        message_id = message.get('id')
        if message_id and is_duplicate_message(message_id):
            app.logger.info(f"Skipping duplicate message {message_id}")
            return jsonify({
                'status': 'success',
                'message': 'Duplicate message skipped'
            }), 200
        
        # Handle different message types
        message_type = message.get('type')
        
        if message_type == 'text':
            message_text = message.get('text', {}).get('body', '').lower()
            
            # Check if this is a morning check-in response
            if is_morning_checkin_response(message_id):
                energy_level = detect_energy_level(message_text)
                today_data = get_todays_tasks()
                
                if today_data and today_data['tasks']:
                    response = get_energy_response(energy_level, today_data['tasks'])
                    send_message(response)
                    return jsonify({
                        'status': 'success',
                        'message': 'Energy response sent'
                    }), 200
            
            # Check if this is a request for voice check-in
            if 'check in' in message_text or 'checkin' in message_text:
                if send_checkin_prompt():
                    return jsonify({
                        'status': 'success',
                        'message': 'Check-in prompt sent'
                    }), 200
            
            # Handle other text messages as before
            if message_text.strip().startswith('status update:'):
                updates = parse_status_update(message_text)
                if updates and save_status_updates(updates):
                    app.logger.info("Status updates saved successfully")
                    confirmation = "Thanks for the update! I've saved your progress. Keep up the great work! 💪"
                    if send_message(confirmation):
                        app.logger.info("Status confirmation sent")
                    return jsonify({
                        'status': 'success',
                        'message': 'Status updates saved successfully'
                    }), 200
            
            # Handle weekly planning
            tasks = parse_tasks(message_text)
            if tasks and save_tasks_to_sheets(tasks):
                app.logger.info("Tasks saved successfully")
                confirmation_message = "Great job planning your week!✅  I'll remind you about these each morning."
                if send_message(confirmation_message):
                    app.logger.info("Confirmation message sent successfully")
                return jsonify({
                    'status': 'success',
                    'message': 'Tasks saved successfully'
                }), 200
        
        # Handle voice messages
        elif message_type == 'voice':
            if handle_voice_checkin(message):
                return jsonify({
                    'status': 'success',
                    'message': 'Voice check-in processed successfully'
                }), 200
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Failed to process voice check-in'
                }), 400
        
        # Handle interactive messages (button responses)
        elif message_type == 'interactive' and message.get('interactive', {}).get('type') == 'button_reply':
            button_reply = message['interactive']['button_reply']
            button_id = button_reply.get('id', '')
            
            if button_id.startswith('task_'):
                parts = button_id.split('_')
                if len(parts) == 3:
                    task_num = int(parts[1])
                    status = parts[2]
                    
                    status_emoji = {
                        'complete': '✅',
                        'progress': '🟡',
                        'incomplete': '❌'
                    }.get(status)
                    
                    if status_emoji:
                        today_data = get_todays_tasks()
                        if today_data and task_num <= len(today_data['tasks']):
                            task = today_data['tasks'][task_num - 1]
                            updates = [{
                                'task_num': task_num,
                                'task': task,
                                'status': status,
                                'note': ''
                            }]
                            
                            if save_status_updates(updates):
                                confirmation = f"Updated status for Task {task_num} to {status_emoji}"
                                send_message(confirmation)
                                return jsonify({
                                    'status': 'success',
                                    'message': 'Status update saved'
                                }), 200
            
            return jsonify({
                'status': 'error',
                'message': 'Invalid button response'
            }), 400
        
        app.logger.warning("Invalid message format received")
        return jsonify({
            'status': 'error',
            'message': 'Invalid message format'
        }), 400
    
    except Exception as e:
        app.logger.error(f"Webhook error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/debug/date')
def debug_date():
    """Debug endpoint to check date handling."""
    now = datetime.now(timezone.utc)
    return jsonify({
        'utc_now': now.isoformat(),
        'utc_date': now.strftime('%Y-%m-%d'),
        'server_now': datetime.now().isoformat(),
        'server_date': datetime.now().strftime('%Y-%m-%d'),
        'weekday': now.weekday(),
        'weekday_name': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][now.weekday()]
    })

def get_todays_tasks():
    """Get tasks for today from Google Sheets."""
    try:
        service = get_google_sheets_service()
        
        # Get all sheet data
        range_name = f"{SHEET_NAME}!A:H"  # Get all rows
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        if not values:
            app.logger.warning('No data found in sheet')
            return None

        # Use UTC time
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        app.logger.info(f"Looking for tasks for date: {today}")
        
        # Log all rows for debugging
        app.logger.info("Available dates in sheet:")
        for row in values[1:]:  # Skip header
            if len(row) >= 2:
                app.logger.info(f"Date in sheet: {row[1]}")
        
        # Find all rows for today and get the most recent one
        today_rows = [row for row in values[1:] if len(row) >= 2 and row[1] == today]
        if today_rows:
            row = today_rows[-1]  # Get the last (most recent) entry for today
            day = row[0]  # Day name
            
            # Get all tasks (columns 3, 5, and 7 are task columns)
            tasks = []
            if len(row) > 2 and row[2].strip():  # Task 1
                tasks.append(row[2])
            if len(row) > 4 and row[4].strip():  # Task 2
                tasks.append(row[4])
            if len(row) > 6 and row[6].strip():  # Task 3
                tasks.append(row[6])
            
            app.logger.info(f"Found {len(tasks)} tasks for today ({today})")
            app.logger.debug(f"Tasks found: {tasks}")
            return {
                'day': day,
                'tasks': tasks
            }
        
        app.logger.info(f"No tasks found for today ({today})")
        return None

    except Exception as e:
        app.logger.error(f"Error getting today's tasks: {str(e)}")
        return None

def detect_energy_level(message_text):
    """Analyze message text to determine energy level."""
    text = message_text.lower()
    
    # High energy indicators
    high_energy = {
        'pumped', 'excited', 'ready', 'motivated', 'energized', 'focused', 
        "let's go", 'feeling great', 'on top of things', 'productive', 
        'inspired', 'crushing it'
    }
    
    # Neutral energy indicators
    neutral_energy = {
        'okay', 'fine', 'alright', 'meh', 'not bad', 'decent', 
        'hanging in there', 'could be better', 'managing', 'doing my best'
    }
    
    # Low energy indicators
    low_energy = {
        'tired', 'exhausted', 'drained', 'burnt out', 'overwhelmed', 
        'stressed', 'anxious', 'struggling', "can't focus", 'not feeling it',
        'heavy', 'unmotivated', 'foggy', 'no energy'
    }
    
    # Distress signals
    distress = {
        'hopeless', 'defeated', 'stuck', 'numb', "can't do anything",
        "what's the point", 'done with everything', 'just want to sleep',
        'empty'
    }
    
    # Count matches in each category
    words = set(text.split())
    high_matches = len(words.intersection(high_energy))
    neutral_matches = len(words.intersection(neutral_energy))
    low_matches = len(words.intersection(low_energy))
    distress_matches = len(words.intersection(distress))
    
    # Determine energy level
    if distress_matches > 0:
        return 'distress'
    elif high_matches > low_matches and high_matches > neutral_matches:
        return 'high'
    elif low_matches > 0:
        return 'low'
    else:
        return 'neutral'

def get_energy_response(energy_level, tasks):
    """Get appropriate response based on energy level."""
    if energy_level == 'high':
        response = "Love that energy! 🌟 Here's your task list for today. Want to add a challenge?\n\n"
        # Show all tasks
        for i, task in enumerate(tasks, 1):
            response += f"{i}. {task}\n"
        response += "\nYou've got this! 💪"
        
    elif energy_level == 'neutral':
        response = "Got it! Let's tackle these tasks one at a time. Need help prioritizing?\n\n"
        # Show all tasks but with a gentler tone
        for i, task in enumerate(tasks, 1):
            response += f"{i}. {task}\n"
        response += "\nRemember to take breaks when needed! 😊"
        
    elif energy_level == 'low':
        # Show only the first task or the smallest task
        response = "Sounds like today's a bit tough. Let's focus on just one small task for now:\n\n"
        response += f"• {tasks[0]}\n\n"
        response += "No pressure—you're doing your best. Take it one step at a time. 💛"
        
    else:  # distress
        response = """I hear you. 💜 It's completely okay to take care of yourself today.

Some gentle suggestions:
• Take a few deep breaths
• Have some water
• Rest if you need to
• Remember: you don't have to be productive right now

Your tasks will be here when you're ready. Want to talk about what's on your mind?"""
    
    return response

def send_morning_checkin():
    """Send morning energy check-in message."""
    message = """Good morning! 🌅

How are you feeling today? 

Just reply naturally - are you feeling energized, okay, tired, or something else? I'll adjust today's plan based on your energy levels."""
    
    return send_message(message)

def send_daily_reminder():
    """Send daily reminder based on tasks from Google Sheets."""
    try:
        app.logger.info("Starting send_daily_reminder function")
        
        # Log WhatsApp credentials status
        app.logger.info("Checking WhatsApp credentials:")
        app.logger.info(f"WHATSAPP_TOKEN present: {bool(WHATSAPP_TOKEN)}")
        app.logger.info(f"PHONE_NUMBER_ID present: {bool(PHONE_NUMBER_ID)}")
        app.logger.info(f"RECIPIENT_PHONE_NUMBER present: {bool(RECIPIENT_PHONE_NUMBER)}")
        
        # Get today's tasks
        app.logger.info("Fetching today's tasks...")
        today_data = get_todays_tasks()
        
        if not today_data:
            app.logger.info("No tasks scheduled for today")
            return False

        tasks = today_data['tasks']
        day = today_data['day']
        
        app.logger.info(f"Found tasks for {day}: {tasks}")
        
        if tasks:
            # Create a more engaging message
            message = f"Good morning! 🌅 Here are your tasks for {day}:\n\n"
            for i, task in enumerate(tasks, 1):
                message += f"{i}. {task}\n"
            
            message += "\nHave a productive day! 💪"
            
            app.logger.info(f"Prepared message to send: {message}")
            
            # Send the message
            app.logger.info("Attempting to send message via WhatsApp...")
            if send_message(message):
                app.logger.info("Daily reminder sent successfully")
                return True
            else:
                app.logger.error("Failed to send daily reminder message via send_message function")
                return False
        else:
            app.logger.info("No tasks found for today")
            return False

    except Exception as e:
        app.logger.error(f"Error in send_daily_reminder: {str(e)}")
        app.logger.exception("Full traceback:")
        return False

@app.route('/send-reminder')
def trigger_reminder():
    """Endpoint to manually trigger daily reminder."""
    try:
        if send_daily_reminder():
            return jsonify({
                'status': 'success',
                'message': 'Daily reminder sent successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send daily reminder'
            }), 400
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/cron/daily-reminder', methods=['POST'])
def cron_daily_reminder():
    """Secure endpoint for Railway cron job to trigger daily reminder."""
    try:
        # Log all headers for debugging
        app.logger.info("Received cron request")
        app.logger.info(f"Headers: {dict(request.headers)}")
        
        # Verify the request is from Railway
        secret = request.headers.get('X-Railway-Secret')
        if not secret or secret != CRON_SECRET:
            app.logger.warning("Unauthorized cron job attempt")
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized'
            }), 401

        # Check if we have WhatsApp credentials
        if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE_NUMBER]):
            app.logger.error("Missing WhatsApp configuration")
            return jsonify({
                'status': 'error',
                'message': 'WhatsApp configuration missing'
            }), 400

        app.logger.info("Proceeding with morning check-in")
        
        # First send the morning check-in
        if send_morning_checkin():
            # Store the message ID in cache to track the response
            message_id = str(int(time.time()))  # Simple timestamp-based ID
            CHECKIN_CACHE[message_id] = time.time()
            
            return jsonify({
                'status': 'success',
                'message': 'Morning check-in sent successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send morning check-in'
            }), 400

    except Exception as e:
        app.logger.error(f"Cron job error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def send_message(message_text):
    """Send a message using the WhatsApp API."""
    try:
        app.logger.info("Starting send_message function")
        
        if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE_NUMBER]):
            app.logger.error("Missing WhatsApp configuration:")
            app.logger.error(f"WHATSAPP_TOKEN: {'*' * 8 if WHATSAPP_TOKEN else 'MISSING'}")
            app.logger.error(f"PHONE_NUMBER_ID: {PHONE_NUMBER_ID if PHONE_NUMBER_ID else 'MISSING'}")
            app.logger.error(f"RECIPIENT_PHONE_NUMBER: {RECIPIENT_PHONE_NUMBER if RECIPIENT_PHONE_NUMBER else 'MISSING'}")
            return False

        url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
        app.logger.info(f"Sending to WhatsApp API URL: {url}")
        
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": RECIPIENT_PHONE_NUMBER,
            "type": "text",
            "text": {"body": message_text}
        }
        
        app.logger.info("Sending request to WhatsApp API with data:")
        app.logger.info(f"To: {RECIPIENT_PHONE_NUMBER}")
        app.logger.info(f"Message length: {len(message_text)} characters")
        
        response = requests.post(url, headers=headers, json=data)
        
        app.logger.info(f"WhatsApp API Response Status: {response.status_code}")
        app.logger.info(f"WhatsApp API Response: {response.text}")
        
        if response.status_code == 200:
            app.logger.info("WhatsApp message sent successfully")
            return True
        else:
            app.logger.error(f"Failed to send WhatsApp message. Status: {response.status_code}")
            app.logger.error(f"Error Response: {response.text}")
            app.logger.error("Request details:")
            app.logger.error(f"URL: {url}")
            app.logger.error(f"Headers: Authorization: Bearer [REDACTED], Content-Type: {headers['Content-Type']}")
            app.logger.error(f"Data: {json.dumps(data)}")
            return False
            
    except Exception as e:
        app.logger.error(f"Error sending WhatsApp message: {str(e)}")
        app.logger.exception("Full traceback:")
        return False

def send_sunday_planning_message():
    """Send the Sunday planning message requesting tasks for the week."""
    try:
        message = """🌟 Weekly Planning Time! 

Let's plan your tasks for the upcoming week. Please reply with your tasks in this format:

Monday: Task 1, Task 2, Task 3
Tuesday: Task 1, Task 2, Task 3
Wednesday: Task 1, Task 2, Task 3
Thursday: Task 1, Task 2, Task 3
Friday: Task 1, Task 2, Task 3"""

        if send_message(message):
            app.logger.info("Sunday planning message sent successfully")
            return True
        else:
            app.logger.error("Failed to send Sunday planning message")
            return False

    except Exception as e:
        app.logger.error(f"Error sending Sunday planning message: {str(e)}")
        return False

@app.route('/send-sunday-planning')
def trigger_sunday_planning():
    """Endpoint to manually trigger Sunday planning message."""
    try:
        if send_sunday_planning_message():
            return jsonify({
                'status': 'success',
                'message': 'Sunday planning message sent successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send Sunday planning message'
            }), 400
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/cron/sunday-planning', methods=['POST'])
def cron_sunday_planning():
    """Secure endpoint for Railway cron job to trigger Sunday planning message."""
    try:
        # Log all headers for debugging
        app.logger.info("Received Sunday planning cron request")
        app.logger.info(f"Headers: {dict(request.headers)}")
        
        # Verify the request is from Railway
        secret = request.headers.get('X-Railway-Secret')
        if not secret or secret != CRON_SECRET:
            app.logger.warning("Unauthorized cron job attempt")
            app.logger.warning(f"Expected secret: {CRON_SECRET}, Got: {secret}")
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized'
            }), 401

        # Check if we have WhatsApp credentials
        if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE_NUMBER]):
            app.logger.error("Missing WhatsApp configuration")
            app.logger.error(f"WHATSAPP_TOKEN set: {bool(WHATSAPP_TOKEN)}")
            app.logger.error(f"PHONE_NUMBER_ID set: {bool(PHONE_NUMBER_ID)}")
            app.logger.error(f"RECIPIENT_PHONE_NUMBER set: {bool(RECIPIENT_PHONE_NUMBER)}")
            return jsonify({
                'status': 'error',
                'message': 'WhatsApp configuration missing'
            }), 400

        # Only send on Sundays
        current_day = datetime.now().weekday()
        app.logger.info(f"Current day is {current_day} (0=Monday, 6=Sunday)")
        
        # if current_day == 6:  # Sunday
        app.logger.info("Proceeding with planning message")
        if send_sunday_planning_message():
            return jsonify({
                'status': 'success',
                'message': 'Sunday planning message sent successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send Sunday planning message'
            }), 400
        # else:
        #     app.logger.info("Not Sunday, skipping planning message")
        #     return jsonify({
        #         'status': 'success',
        #         'message': 'Skipped - not Sunday'
        #     })

    except Exception as e:
        app.logger.error(f"Sunday planning cron error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def send_interactive_message(header_text, body_text, buttons):
    """Send an interactive message with buttons using the WhatsApp API."""
    try:
        app.logger.info("Attempting to send WhatsApp interactive message")
        
        if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE_NUMBER]):
            app.logger.error("Missing WhatsApp configuration")
            app.logger.error(f"WHATSAPP_TOKEN set: {bool(WHATSAPP_TOKEN)}")
            app.logger.error(f"PHONE_NUMBER_ID set: {bool(PHONE_NUMBER_ID)}")
            app.logger.error(f"RECIPIENT_PHONE_NUMBER set: {bool(RECIPIENT_PHONE_NUMBER)}")
            return False

        url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
        
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": RECIPIENT_PHONE_NUMBER,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "text",
                    "text": header_text
                },
                "body": {
                    "text": body_text
                },
                "action": {
                    "buttons": buttons
                }
            }
        }
        
        app.logger.info("Sending request to WhatsApp API")
        app.logger.debug(f"Request data: {json.dumps(data)}")
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            app.logger.info("WhatsApp interactive message sent successfully")
            app.logger.debug(f"WhatsApp API response: {response.text}")
            return True
        else:
            app.logger.error(f"Failed to send WhatsApp message. Status: {response.status_code}")
            app.logger.error(f"Response: {response.text}")
            return False
            
    except Exception as e:
        app.logger.error(f"Error sending WhatsApp interactive message: {str(e)}")
        app.logger.exception("Full traceback:")
        return False

def send_status_request():
    """Send end-of-day status request for tasks."""
    try:
        app.logger.info("Starting send_status_request function")
        
        # Check WhatsApp credentials first
        if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE_NUMBER]):
            app.logger.error("Missing WhatsApp credentials:")
            app.logger.error(f"WHATSAPP_TOKEN present: {bool(WHATSAPP_TOKEN)}")
            app.logger.error(f"PHONE_NUMBER_ID present: {bool(PHONE_NUMBER_ID)}")
            app.logger.error(f"RECIPIENT_PHONE_NUMBER present: {bool(RECIPIENT_PHONE_NUMBER)}")
            return False

        # Get today's tasks
        app.logger.info("Fetching today's tasks...")
        today_data = get_todays_tasks()
        
        if not today_data:
            app.logger.info("No tasks found for today to request status updates")
            return False

        tasks = today_data['tasks']
        day = today_data['day']
        
        app.logger.info(f"Found {len(tasks)} tasks for {day}")
        app.logger.debug(f"Tasks: {tasks}")
        
        if tasks:
            # Send one message per task
            for i, task in enumerate(tasks, 1):
                header_text = f"Task {i} Status Update"
                body_text = f"How did you do on this task?\n\n{task}"
                
                # Create buttons for this task
                buttons = [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"task_{i}_complete",
                            "title": "✅ Done"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"task_{i}_progress",
                            "title": "🟡 In Progress"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"task_{i}_incomplete",
                            "title": "❌ Stuck"
                        }
                    }
                ]
                
                if not send_interactive_message(header_text, body_text, buttons):
                    app.logger.error(f"Failed to send status request for task {i}")
                    return False
                
            app.logger.info("All task status requests sent successfully")
            return True
        else:
            app.logger.info("No tasks to request status for")
            return False

    except Exception as e:
        app.logger.error(f"Error sending status request: {str(e)}")
        app.logger.exception("Full traceback:")
        return False

@app.route('/send-status-request')
def trigger_status_request():
    """Endpoint to manually trigger status request."""
    try:
        if send_status_request():
            return jsonify({
                'status': 'success',
                'message': 'Status request sent successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send status request'
            }), 400
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def initialize_mood_tracker_sheet(service):
    """Initialize the mood tracker sheet with headers if it doesn't exist."""
    try:
        # Check if the sheet exists
        sheet_metadata = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
        sheets = sheet_metadata.get('sheets', '')
        sheet_exists = any(sheet.get("properties", {}).get("title") == MOOD_SHEET_NAME for sheet in sheets)
        
        if not sheet_exists:
            # Create new sheet
            body = {
                'requests': [{
                    'addSheet': {
                        'properties': {
                            'title': MOOD_SHEET_NAME
                        }
                    }
                }]
            }
            service.spreadsheets().batchUpdate(
                spreadsheetId=SHEET_ID,
                body=body
            ).execute()
            app.logger.info(f"Created new sheet: {MOOD_SHEET_NAME}")
        
        # Check/Set headers
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{MOOD_SHEET_NAME}!A1:J1"
        ).execute()
        
        values = result.get('values', [])
        
        if not values or values[0] != MOOD_HEADERS:
            body = {
                'values': [MOOD_HEADERS]
            }
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range=f"{MOOD_SHEET_NAME}!A1:J1",
                valueInputOption='RAW',
                body=body
            ).execute()
            app.logger.info("Mood tracker sheet headers initialized successfully")
            
    except Exception as e:
        app.logger.error(f"Error initializing mood tracker sheet: {str(e)}")
        raise

def download_voice_note(media_id):
    """Download voice note from WhatsApp servers."""
    try:
        # Get media URL
        url = f"https://graph.facebook.com/v17.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get media URL: {response.text}")
        
        media_url = response.json().get('url')
        if not media_url:
            raise Exception("Media URL not found in response")
        
        # Download media
        response = requests.get(media_url, headers=headers)
        if response.status_code != 200:
            raise Exception("Failed to download media")
        
        return response.content
        
    except Exception as e:
        app.logger.error(f"Error downloading voice note: {str(e)}")
        raise

async def transcribe_voice_note(audio_data):
    """Transcribe voice note using Deepgram."""
    try:
        # Configure transcription options
        options = {
            "punctuate": True,
            "model": "general",
            "language": "en",
            "smart_format": True
        }
        
        # Send the audio to Deepgram
        response = await deepgram.transcription.prerecorded(
            {"buffer": audio_data, "mimetype": "audio/ogg"},
            options
        )
        
        # Extract the transcript
        transcript = response["results"]["channels"][0]["alternatives"][0]["transcript"]
        
        return transcript
        
    except Exception as e:
        app.logger.error(f"Error transcribing voice note: {str(e)}")
        raise

def analyze_mood_from_text(text):
    """Analyze mood and emotions from transcribed text."""
    try:
        # Simple rule-based sentiment analysis
        # You can make this more sophisticated or integrate with a sentiment analysis service
        positive_words = {'happy', 'good', 'great', 'awesome', 'excellent', 'excited', 'joy', 'wonderful', 'fantastic'}
        negative_words = {'sad', 'bad', 'terrible', 'awful', 'worried', 'stressed', 'angry', 'frustrated', 'tired'}
        energy_words = {
            'high': {'energetic', 'active', 'motivated', 'excited', 'pumped'},
            'low': {'tired', 'exhausted', 'drained', 'sleepy', 'lazy'}
        }
        
        words = set(text.lower().split())
        
        # Calculate mood score
        positive_count = len(words.intersection(positive_words))
        negative_count = len(words.intersection(negative_words))
        total_sentiment_words = positive_count + negative_count
        
        if total_sentiment_words > 0:
            mood_score = round((positive_count / total_sentiment_words) * 10)
        else:
            mood_score = 5  # Neutral score if no sentiment words found
        
        # Determine energy level
        high_energy_count = len(words.intersection(energy_words['high']))
        low_energy_count = len(words.intersection(energy_words['low']))
        
        if high_energy_count > low_energy_count:
            energy_level = 'High'
        elif low_energy_count > high_energy_count:
            energy_level = 'Low'
        else:
            energy_level = 'Medium'
        
        # Extract potential action items (sentences with action verbs)
        action_verbs = {'need', 'want', 'going', 'plan', 'will', 'must', 'should'}
        sentences = text.split('.')
        action_items = []
        for sentence in sentences:
            words = sentence.lower().split()
            if any(verb in words for verb in action_verbs):
                action_items.append(sentence.strip())
        
        return {
            'mood_score': mood_score,
            'primary_emotion': 'Positive' if mood_score > 5 else 'Negative' if mood_score < 5 else 'Neutral',
            'secondary_emotions': 'Varied',
            'key_topics': extract_key_topics(text),
            'energy_level': energy_level,
            'action_items': '. '.join(action_items) if action_items else '',
            'follow_up_needed': 'Yes' if action_items else 'No'
        }
        
    except Exception as e:
        app.logger.error(f"Error analyzing mood: {str(e)}")
        return {
            'mood_score': 5,
            'primary_emotion': 'Neutral',
            'secondary_emotions': '',
            'key_topics': '',
            'energy_level': 'Medium',
            'action_items': '',
            'follow_up_needed': 'No'
        }

def extract_key_topics(text):
    """Extract key topics from text using simple keyword extraction."""
    # Common topics to look for in check-ins
    topic_keywords = {
        'work': {'work', 'project', 'meeting', 'deadline', 'task', 'job', 'client'},
        'health': {'health', 'exercise', 'workout', 'sleep', 'rest', 'tired', 'energy'},
        'mood': {'feeling', 'mood', 'emotion', 'stress', 'anxiety', 'happy', 'sad'},
        'relationships': {'family', 'friend', 'relationship', 'social', 'people', 'team'},
        'goals': {'goal', 'plan', 'future', 'achieve', 'progress', 'improvement'}
    }
    
    words = set(text.lower().split())
    found_topics = []
    
    for topic, keywords in topic_keywords.items():
        if words.intersection(keywords):
            found_topics.append(topic)
    
    return ', '.join(found_topics) if found_topics else 'General check-in'

def save_mood_data(transcription, analysis):
    """Save mood tracking data to Google Sheets."""
    try:
        service = get_google_sheets_service()
        
        # Initialize sheet if needed
        initialize_mood_tracker_sheet(service)
        
        # Prepare row data
        now = datetime.now()
        row = [
            now.strftime('%Y-%m-%d'),
            now.strftime('%H:%M:%S'),
            transcription,
            analysis.get('mood_score', ''),
            analysis.get('primary_emotion', ''),
            analysis.get('secondary_emotions', ''),
            analysis.get('key_topics', ''),
            analysis.get('energy_level', ''),
            analysis.get('action_items', ''),
            analysis.get('follow_up_needed', '')
        ]
        
        # Get next available row
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{MOOD_SHEET_NAME}!A:J"
        ).execute()
        
        values = result.get('values', [])
        next_row = len(values) + 1
        
        # Update sheet
        body = {
            'values': [row]
        }
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f"{MOOD_SHEET_NAME}!A{next_row}:J{next_row}",
            valueInputOption='RAW',
            body=body
        ).execute()
        
        app.logger.info("Mood tracking data saved successfully")
        return True
        
    except Exception as e:
        app.logger.error(f"Error saving mood data: {str(e)}")
        return False

def handle_voice_checkin(message):
    """Handle voice note check-in."""
    try:
        # Get voice note media ID
        media = message.get('voice', {})
        media_id = media.get('id')
        
        if not media_id:
            app.logger.error("No media ID found in voice message")
            return False
        
        # Download voice note
        audio_data = download_voice_note(media_id)
        
        # Transcribe voice note
        import asyncio
        transcription = asyncio.run(transcribe_voice_note(audio_data))
        
        # Analyze mood
        analysis = analyze_mood_from_text(transcription)
        
        # Save to sheet
        if save_mood_data(transcription, analysis):
            # Send confirmation with mood insights
            confirmation = f"""Thanks for checking in! 🎯

I heard you and here's what I gathered:
• Mood: {analysis['mood_score']}/10
• Overall feeling: {analysis['primary_emotion']}
• Energy level: {analysis['energy_level']}
• Topics discussed: {analysis['key_topics']}

{f"Action items noted: {analysis['action_items']}" if analysis.get('action_items') else ''}
{f"I'll make sure to follow up with you on this." if analysis.get('follow_up_needed') == 'Yes' else ''}

Keep taking care of yourself! 🌟"""
            
            send_message(confirmation)
            return True
            
        return False
        
    except Exception as e:
        app.logger.error(f"Error handling voice check-in: {str(e)}")
        return False

def is_morning_checkin_response(message_id):
    """Check if this message is a response to morning check-in."""
    current_time = time.time()
    
    # Clean old entries
    for mid, timestamp in list(CHECKIN_CACHE.items()):
        if current_time - timestamp > CHECKIN_CACHE_TTL:
            CHECKIN_CACHE.pop(mid)
    
    return message_id in CHECKIN_CACHE

if __name__ == '__main__':
    # Get port from environment variable for Railway
    port = int(os.environ.get('PORT', 5000))
    # In production, host should be '0.0.0.0' to accept all incoming connections
    host = '0.0.0.0' if os.environ.get('RAILWAY_ENVIRONMENT') else '127.0.0.1'
    
    app.run(host=host, port=port) 