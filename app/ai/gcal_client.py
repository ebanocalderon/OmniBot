"""
Google Calendar API client for fetching slots and creating bookings.
"""
import logging
import asyncio
import os
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

def _get_calendar_service():
    """
    Initialize Google Calendar API service using token.json.
    """
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/calendar"])
        if creds and creds.expired and creds.refresh_token:
            logger.info("Google credentials expired. Refreshing token...")
            creds.refresh(Request())
            # Save the refreshed token
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        return build('calendar', 'v3', credentials=creds)
    else:
        raise Exception("Google token.json not found on the server.")

async def fetch_slots(date_str: str) -> str:
    """
    Fetch available slots for a specific date (YYYY-MM-DD).
    Checks busy times via Google Calendar FreeBusy query and yields 30-min available slots during business hours (9AM-5PM EST).
    """
    try:
        # Parse date_str: "YYYY-MM-DD"
        est = timezone(timedelta(hours=-4))
        year, month, day = map(int, date_str.split('-'))
        
        # Build list of 30-min slots from 9:00 AM to 5:00 PM EST
        slots = []
        for hour in range(9, 17):
            for minute in (0, 30):
                slot_start_est = datetime(year, month, day, hour, minute, tzinfo=est)
                slots.append(slot_start_est)
                
        # Filter out slots in the past
        now_est = datetime.now(est)
        slots = [s for s in slots if s > now_est]
        
        if not slots:
            return f"No available slots found for {date_str}."
            
        # Define day bounds in EST and convert to UTC ISO format for FreeBusy query
        day_start_est = datetime(year, month, day, 0, 0, tzinfo=est)
        day_end_est = datetime(year, month, day, 23, 59, tzinfo=est)
        
        start_iso = day_start_est.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = day_end_est.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        service = await asyncio.to_thread(_get_calendar_service)
        
        body = {
            "timeMin": start_iso,
            "timeMax": end_iso,
            "items": [{"id": "primary"}]
        }
        
        freebusy_query = service.freebusy().query(body=body)
        resp = await asyncio.to_thread(freebusy_query.execute)
        
        busy_periods = resp.get("calendars", {}).get("primary", {}).get("busy", [])
        
        # Parse busy periods into UTC datetime objects
        busy_ranges = []
        for period in busy_periods:
            # Support parsing ISO offset/Z
            p_start = period["start"].replace("Z", "+00:00")
            p_end = period["end"].replace("Z", "+00:00")
            b_start = datetime.fromisoformat(p_start)
            b_end = datetime.fromisoformat(p_end)
            busy_ranges.append((b_start, b_end))
            
        # Find slots that do not overlap with busy ranges
        available_slots = []
        for slot in slots:
            slot_start_utc = slot.astimezone(timezone.utc)
            slot_end_utc = slot_start_utc + timedelta(minutes=30)
            
            is_busy = False
            for b_start, b_end in busy_ranges:
                # Overlap: slot_start < b_end AND slot_end > b_start
                if slot_start_utc < b_end and slot_end_utc > b_start:
                    is_busy = True
                    break
            
            if not is_busy:
                formatted_time = slot.strftime("%I:%M %p EST")
                utc_str = slot_start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                available_slots.append(f"{formatted_time} (Use '{utc_str}' when booking)")
                
        if not available_slots:
            return f"No available slots found for {date_str}."
            
        # Limit to 6 slots to stay under token limits
        available_slots = available_slots[:6]
        
        formatted = f"Available slots for {date_str} (UTC):\n" + "\n".join([f"- {s}" for s in available_slots])
        return formatted
        
    except Exception as e:
        logger.exception("Error fetching Google Calendar slots")
        return f"Error checking slots: {str(e)}"

async def create_booking(name: str, email: str, start_time_iso: str) -> str:
    """
    Create a booking in Google Calendar.
    Creates an event with a Google Meet conference link.
    """
    try:
        service = await asyncio.to_thread(_get_calendar_service)
        
        # Parse start and end time
        clean_time = start_time_iso.replace("Z", "+00:00")
        dt_start = datetime.fromisoformat(clean_time)
        dt_end = dt_start + timedelta(minutes=30)
        
        start_str = dt_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = dt_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        import uuid
        request_id = str(uuid.uuid4())
        
        event = {
            'summary': f'Consultation: {name}',
            'description': 'Appointment booked via OmniBot.',
            'start': {
                'dateTime': start_str,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_str,
                'timeZone': 'UTC',
            },
            'attendees': [
                {'email': email, 'displayName': name},
            ],
            'conferenceData': {
                'createRequest': {
                    'requestId': request_id,
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            },
            'reminders': {
                'useDefault': True,
            },
        }
        
        insert_query = service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1
        )
        
        created_event = await asyncio.to_thread(insert_query.execute)
        
        event_id = created_event.get("id")
        meet_link = created_event.get("hangoutLink", "No Meet link generated")
        
        return f"Successfully booked appointment. Booking ID: {event_id}. Google Meet Link: {meet_link}"
        
    except Exception as e:
        logger.exception("Error creating Google Calendar booking")
        return f"Error booking appointment: {str(e)}"

async def check_existing_bookings(email: str) -> str:
    """
    Check if an email already has active upcoming events on Google Calendar.
    """
    try:
        service = await asyncio.to_thread(_get_calendar_service)
        
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        list_query = service.events().list(
            calendarId='primary',
            timeMin=now_iso,
            q=email,
            singleEvents=True,
            orderBy='startTime'
        )
        
        events_result = await asyncio.to_thread(list_query.execute)
        events = events_result.get('items', [])
        
        active_bookings = []
        
        for event in events:
            attendees = event.get("attendees", [])
            has_email = any(a.get("email", "").lower() == email.lower() for a in attendees)
            
            if has_email:
                start_data = event.get("start", {})
                start_str = start_data.get("dateTime") or start_data.get("date")
                
                if start_str:
                    clean_str = start_str.replace("Z", "+00:00")
                    if "+" in clean_str:
                        base, tz = clean_str.split("+")
                        if "." in base:
                            base = base.split(".")[0]
                        clean_str = f"{base}+{tz}"
                    dt = datetime.fromisoformat(clean_str)
                    
                    dt_est = dt.astimezone(timezone(timedelta(hours=-4)))
                    formatted_time = dt_est.strftime("%Y-%m-%d %I:%M %p EST")
                    
                    active_bookings.append({
                        "id": event.get("id"),
                        "time": formatted_time
                    })
                    
        if not active_bookings:
            return f"No active upcoming consultations found for {email}."
            
        formatted = f"Active consultations found for {email}:\n"
        for b in active_bookings:
            formatted += f"- {b['time']} (Booking UID: {b['id']})\n"
        return formatted
        
    except Exception as e:
        logger.exception("Error checking Google Calendar bookings")
        return f"Error checking existing bookings: {str(e)}"

async def cancel_booking(booking_uid: str) -> str:
    """
    Cancel a booking by deleting the Google Calendar event.
    """
    try:
        service = await asyncio.to_thread(_get_calendar_service)
        delete_query = service.events().delete(calendarId='primary', eventId=booking_uid)
        await asyncio.to_thread(delete_query.execute)
        return f"Successfully cancelled booking (UID: {booking_uid})."
    except Exception as e:
        logger.exception("Error cancelling Google Calendar booking")
        return f"Error cancelling booking: {str(e)}"
