import os
import datetime
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'
USER_TIMEZONE = 'Asia/Kolkata'

def get_calendar_service():
    """Authenticates using the Service Account file."""
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build('calendar', 'v3', credentials=creds)
    raise FileNotFoundError("credentials.json not found!")

# --- CORE TOOLS (Simplified to avoid hallucination) ---

def get_current_time():
    """
    Returns the current date and time in USER_TIMEZONE.
    Critical for LLM to understand relative dates like 'tomorrow'.
    """
    tz = pytz.timezone(USER_TIMEZONE)
    now = datetime.datetime.now(tz)
    return now.strftime("%A, %Y-%m-%d %H:%M:%S %Z")

def list_upcoming_events(max_results=5):
    """
    Lists upcoming events on the calendar.
    Returns RAW ISO timestamps - let the LLM format them naturally.
    """
    try:
        service = get_calendar_service()
        calendar_id = os.getenv("CALENDAR_ID", "primary")
        
        # Get 'now' in UTC for API query
        now_utc = datetime.datetime.utcnow().isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now_utc,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return "No upcoming events found."
        
        result_strings = []
        for event in events:
            # Return RAW ISO timestamp - don't format it!
            start = event['start'].get('dateTime', event['start'].get('date'))
            result_strings.append(f"Event: {event['summary']} at {start}")
        
        return "\n".join(result_strings)
    
    except Exception as e:
        return f"Error: {str(e)}"

def check_specific_slot(start_iso: str, duration_minutes: int = 60):
    """
    Checks if a specific slot is free.
    Takes start time in ISO format, checks for conflicts.
    """
    try:
        service = get_calendar_service()
        calendar_id = os.getenv("CALENDAR_ID", "primary")
        
        start_dt = datetime.datetime.fromisoformat(start_iso)
        end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return "Available"
        
        # Return simple conflict info
        conflicts = [f"{e['summary']}" for e in events]
        return f"Conflict with: {', '.join(conflicts)}"
    
    except Exception as e:
        return f"Error: {str(e)}"

def find_nearest_slots(start_search_iso: str, duration_minutes: int = 60):
    """
    Finds 3 free slots starting from search time.
    Returns slots with ISO timestamps for LLM to parse.
    """
    try:
        service = get_calendar_service()
        calendar_id = os.getenv("CALENDAR_ID", "primary")
        
        start_dt = datetime.datetime.fromisoformat(start_search_iso)
        # Ensure timezone awareness
        if start_dt.tzinfo is None:
            tz = pytz.timezone(USER_TIMEZONE)
            start_dt = tz.localize(start_dt)
        
        end_search_dt = start_dt + datetime.timedelta(hours=48)
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_dt.isoformat(),
            timeMax=end_search_dt.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Build busy times list
        busy_times = []
        for e in events:
            e_start = e['start'].get('dateTime')
            e_end = e['end'].get('dateTime')
            if e_start and e_end:
                busy_times.append((
                    datetime.datetime.fromisoformat(e_start),
                    datetime.datetime.fromisoformat(e_end)
                ))
        
        # Find free slots
        free_slots = []
        current = start_dt
        
        while len(free_slots) < 3 and current < end_search_dt:
            slot_end = current + datetime.timedelta(minutes=duration_minutes)
            is_busy = False
            
            for b_start, b_end in busy_times:
                if (current < b_end) and (slot_end > b_start):
                    is_busy = True
                    break
            
            if not is_busy:
                # Only suggest business hours (9 AM - 6 PM)
                if 9 <= current.hour < 18:
                    # Return ISO timestamp - let LLM format naturally
                    free_slots.append(current.isoformat())
            
            current += datetime.timedelta(minutes=30)
        
        if not free_slots:
            return "No free slots found in next 48 hours."
        
        # Return ISO timestamps separated by commas
        return "Available slots: " + ", ".join(free_slots)
    
    except Exception as e:
        return f"Error: {str(e)}"

def book_meeting(summary: str, start_iso: str, duration_minutes: int = 60):
    """
    Books a meeting at the specified time.
    """
    try:
        service = get_calendar_service()
        calendar_id = os.getenv("CALENDAR_ID", "primary")
        
        start_dt = datetime.datetime.fromisoformat(start_iso)
        end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
        
        event = {
            'summary': summary,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': USER_TIMEZONE
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': USER_TIMEZONE
            }
        }
        
        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event
        ).execute()
        
        # Return simple confirmation with ISO timestamp
        return f"Meeting '{summary}' booked successfully at {start_iso}"
    
    except Exception as e:
        return f"Booking failed: {str(e)}"
