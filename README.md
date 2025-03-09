# WhatsApp Daily Task Reminder

This Python script sends daily WhatsApp reminders based on tasks from a Google Spreadsheet.

## Setup Instructions

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Set up Google Sheets API:
   - Go to the [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the Google Sheets API
   - Create credentials (OAuth 2.0 Client ID)
   - Download the credentials and save them as `credentials.json` in the same directory as the script

3. First Run:
   - Run the script: `python whatsapp_reminder.py`
   - A browser window will open for Google authentication
   - Complete the authentication process
   - The script will save the authentication token for future use

## Usage

The script will:
1. Connect to your Google Spreadsheet
2. Look for tasks scheduled for today
3. Send a WhatsApp message with the tasks

To run the script:
```bash
python whatsapp_reminder.py
```

## Important Notes

- Make sure your Google Spreadsheet has a sheet named "Weekly Plan"
- The spreadsheet should have columns for dates and tasks
- The WhatsApp token needs to be valid and have proper permissions
- The recipient number should be in the correct format (with country code)

## Security

- Keep your `credentials.json` and `token.pickle` files secure
- Don't share your WhatsApp token
- Store sensitive information in environment variables in production 