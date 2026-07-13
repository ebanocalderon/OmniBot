"""
Cal.com API client for fetching slots and creating bookings.
"""
import logging
import httpx
from datetime import datetime, timedelta, timezone

from app.config import settings

logger = logging.getLogger(__name__)

CAL_API_URL = "https://api.cal.com/v2"

def _get_headers() -> dict:
    if not settings.cal_api_key:
        logger.warning("CAL_API_KEY is not set.")
    return {
        "Authorization": f"Bearer {settings.cal_api_key}",
        "cal-api-version": "2024-08-13",
        "Content-Type": "application/json"
    }

async def fetch_slots(date_str: str) -> str:
    """
    Fetch available slots for a specific date (YYYY-MM-DD).
    Returns a formatted string of available slots to present to the LLM.
    """
    if not settings.cal_event_type_id:
        return "Error: CAL_EVENT_TYPE_ID is not configured."

    # Search for slots covering the requested date
    try:
        # Convert date to start and end of that day (UTC)
        start_time = f"{date_str}T00:00:00Z"
        end_time = f"{date_str}T23:59:59Z"
        
        url = f"{CAL_API_URL}/slots/available"
        params = {
            "eventTypeId": settings.cal_event_type_id,
            "startTime": start_time,
            "endTime": end_time
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=_get_headers(), params=params)
            resp.raise_for_status()
            data = resp.json()
            
            slots_data = data.get("data", {}).get("slots", {})
            if not slots_data:
                return f"No available slots found for {date_str}."
            
            # Format the output for the LLM
            # We will just collect all unique start times
            available_times = []
            
            if isinstance(slots_data, dict):
                for day, times in slots_data.items():
                    for slot in times:
                        if "time" in slot:
                            utc_str = slot["time"]
                            try:
                                # Parse UTC string (e.g. "2026-07-14T13:00:00.000Z")
                                dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                                # Convert to Eastern Time (UTC-4)
                                dt_est = dt.astimezone(timezone(timedelta(hours=-4)))
                                formatted_time = dt_est.strftime("%I:%M %p EST")
                                available_times.append(f"{formatted_time} (Use '{utc_str}' when booking)")
                            except Exception:
                                available_times.append(utc_str)
            elif isinstance(slots_data, list):
                for slot in slots_data:
                    if "time" in slot:
                        utc_str = slot["time"]
                        try:
                            dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                            dt_est = dt.astimezone(timezone(timedelta(hours=-4)))
                            formatted_time = dt_est.strftime("%I:%M %p EST")
                            available_times.append(f"{formatted_time} (Use '{utc_str}' when booking)")
                        except Exception:
                            available_times.append(utc_str)
                        
            if not available_times:
                return f"No available slots found for {date_str}."
                
            formatted = f"Available slots for {date_str} (UTC):\n" + "\n".join([f"- {t}" for t in available_times])
            return formatted
            
    except httpx.HTTPError as e:
        logger.error("Failed to fetch Cal.com slots: %s", e)
        return f"API Error checking slots: {str(e)}"
    except Exception as e:
        logger.exception("Unexpected error fetching slots")
        return f"Error: {str(e)}"


async def create_booking(name: str, email: str, start_time_iso: str) -> str:
    """
    Create a booking in Cal.com.
    start_time_iso must be a valid ISO 8601 string (e.g., '2026-07-15T09:00:00Z').
    """
    if not settings.cal_api_key or not settings.cal_event_type_id:
        return "Error: Cal.com credentials are not configured on the server."

    url = f"{CAL_API_URL}/bookings"
    payload = {
        "eventTypeId": settings.cal_event_type_id,
        "start": start_time_iso,
        "attendee": {
            "name": name,
            "email": email,
            "timeZone": "UTC",
            "language": "en"
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=_get_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            booking_id = data.get("data", {}).get("id", "Unknown")
            return f"Successfully booked appointment. Booking ID: {booking_id}"
    except httpx.HTTPError as e:
        logger.error("Failed to create Cal.com booking: %s", e)
        # Try to read the error response body if available
        error_details = ""
        if hasattr(e, "response") and e.response is not None:
            try:
                error_details = e.response.json()
            except Exception:
                error_details = e.response.text
        return f"API Error booking appointment: {str(e)} - {error_details}"
    except Exception as e:
        logger.exception("Unexpected error creating booking")
        return f"Error: {str(e)}"
