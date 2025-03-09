from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def access_google_sheets():
    # Service account key file path
    SERVICE_ACCOUNT_FILE = 'kamsi-200302-718b8e66bbfd.json'
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    SPREADSHEET_ID = '1mbO96co-uwzwcpX6UUGnmeZ0-YIl8gan7iA6-2iZ_68'
    RANGE_NAME = 'Sheet2!A2:E3'  # Adjust this range based on your actual needs

    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API to read data
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
    values = result.get('values', [])

    if not values:
        print('No data found.')
    else:
        for row in values:
            print(row)

    # Example to write data to the sheet (Here you should adjust what you want to write and where)
    update_values = [
        ['Update1', 'Update2', 'Update3'],  # Data to write
    ]
    body = {
        'values': update_values
    }
    result = sheet.values().update(
        spreadsheetId=SPREADSHEET_ID, range='Sheet2!C3',  # Change the range to where you want to write
        valueInputOption='RAW', body=body).execute()
    print(f"{result.get('updatedCells')} cells updated.")

if __name__ == '__main__':
    access_google_sheets()
