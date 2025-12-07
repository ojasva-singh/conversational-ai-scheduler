import asyncio
import pyaudio
from dotenv import load_dotenv
from google import genai
from google.genai import types

import tools
import scheduler_logic

load_dotenv()

# --- AUDIO CONFIGURATION ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

# --- GLOBAL QUEUES ---
audio_queue_mic = asyncio.Queue(maxsize=5)
audio_queue_output = asyncio.Queue()

# --- CLIENT SETUP ---
client = genai.Client(http_options={'api_version': 'v1alpha'})
MODEL = "gemini-2.5-flash-native-audio-preview-09-2025"

# --- COMPLETE TOOL DECLARATIONS ---

tool_get_current_time_declaration = {
    "name": "get_current_time",
    "description": "Returns the current date and time in Asia/Kolkata timezone. Use this to understand 'now' and calculate relative times.",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}

tool_list_events_declaration = {
    "name": "list_upcoming_events",
    "description": "Lists the next 5 upcoming events on the calendar with ISO timestamps",
    "parameters": {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return (default: 5)",
                "default": 5
            }
        }
    }
}

tool_check_specific_slot_declaration = {
    "name": "check_specific_slot",
    "description": "Checks if a specific time slot is free. Returns 'Available' or conflict details.",
    "parameters": {
        "type": "object",
        "properties": {
            "start_iso": {
                "type": "string",
                "description": "ISO format datetime string (e.g., 2025-12-10T14:00:00+05:30)"
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Meeting duration in minutes (default: 60)",
                "default": 60
            }
        },
        "required": ["start_iso"]
    }
}

tool_find_nearest_slots_declaration = {
    "name": "find_nearest_slots",
    "description": "Finds up to 3 free time slots starting from a given time, within the next 48 hours during business hours (9 AM - 6 PM)",
    "parameters": {
        "type": "object",
        "properties": {
            "start_search_iso": {
                "type": "string",
                "description": "ISO format datetime to start searching from"
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Required duration in minutes (default: 60)",
                "default": 60
            }
        },
        "required": ["start_search_iso"]
    }
}

tool_smart_check_declaration = {
    "name": "smart_check_availability",
    "description": "Smart availability checker - checks if a slot is free, and if busy, automatically suggests 3 alternative times",
    "parameters": {
        "type": "object",
        "properties": {
            "start_iso": {
                "type": "string",
                "description": "ISO format datetime string (e.g., 2025-12-10T14:00:00+05:30)"
            },
            "duration": {
                "type": "integer",
                "description": "Meeting duration in minutes (default: 60)",
                "default": 60
            }
        },
        "required": ["start_iso"]
    }
}

tool_book_meeting_declaration = {
    "name": "book_meeting",
    "description": "Books a meeting at the specified time. Only call this after user confirmation.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Meeting title/summary"
            },
            "start_iso": {
                "type": "string",
                "description": "ISO format datetime string"
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Meeting duration in minutes (default: 60)",
                "default": 60
            }
        },
        "required": ["summary", "start_iso"]
    }
}

# --- TOOL MAPPING ---
tools_map = {
    "get_current_time": lambda: tools.get_current_time(),
    "list_upcoming_events": lambda max_results=5: tools.list_upcoming_events(max_results),
    "check_specific_slot": lambda start_iso, duration_minutes=60: tools.check_specific_slot(start_iso, duration_minutes),
    "find_nearest_slots": lambda start_search_iso, duration_minutes=60: tools.find_nearest_slots(start_search_iso, duration_minutes),
    "smart_check_availability": lambda start_iso, duration=60: scheduler_logic.smart_check_availability(start_iso, duration),
    "book_meeting": lambda summary, start_iso, duration_minutes=60: tools.book_meeting(summary, start_iso, duration_minutes)
}

# --- ASYNC TASKS ---
async def listen_mic():
    """Captures audio from hardware and puts it in the queue."""
    pya = pyaudio.PyAudio()
    mic_info = pya.get_default_input_device_info()
    stream = await asyncio.to_thread(
        pya.open,
        format=FORMAT,
        channels=CHANNELS,
        rate=SEND_SAMPLE_RATE,
        input=True,
        input_device_index=mic_info["index"],
        frames_per_buffer=CHUNK_SIZE,
    )
    print(f"🎤 Mic Active (16kHz). Speak now!")
    try:
        while True:
            data = await asyncio.to_thread(
                stream.read, CHUNK_SIZE, exception_on_overflow=False
            )
            await audio_queue_mic.put(
                types.Blob(data=data, mime_type="audio/pcm;rate=16000")
            )
    except asyncio.CancelledError:
        stream.stop_stream()
        stream.close()
        pya.terminate()

async def play_speaker():
    """Takes audio from queue and plays it on hardware."""
    pya = pyaudio.PyAudio()
    stream = await asyncio.to_thread(
        pya.open,
        format=FORMAT,
        channels=CHANNELS,
        rate=RECEIVE_SAMPLE_RATE,
        output=True,
    )
    try:
        while True:
            bytestream = await audio_queue_output.get()
            await asyncio.to_thread(stream.write, bytestream)
            audio_queue_output.task_done()
    except asyncio.CancelledError:
        stream.stop_stream()
        stream.close()
        pya.terminate()

async def send_to_gemini(session):
    """Takes mic data from queue and sends it to Gemini."""
    while True:
        audio_blob = await audio_queue_mic.get()
        await session.send_realtime_input(audio=audio_blob)

async def receive_from_gemini(session):
    """Listens to Gemini's responses (Audio + Tool Calls)."""
    while True:
        try:
            turn = session.receive()
            async for response in turn:
                # 1. Handle interruptions
                if response.server_content and response.server_content.interrupted:
                    print("🛑 Interrupted - clearing audio queue")
                    while not audio_queue_output.empty():
                        audio_queue_output.get_nowait()
                    continue
                
                # 2. Handle Audio output
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data and isinstance(part.inline_data.data, bytes):
                            audio_queue_output.put_nowait(part.inline_data.data)
                
                # 3. Handle Tool Calls
                if response.tool_call:
                    function_responses = []
                    for fc in response.tool_call.function_calls:
                        print(f"⚡ Tool Call: {fc.name} | Args: {fc.args}")
                        func = tools_map.get(fc.name)
                        if func:
                            try:
                                result = func(**fc.args)
                                print(f"   ✓ Result: {result}")
                                
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": result}
                                )
                                function_responses.append(function_response)
                            except Exception as e:
                                print(f"   ✗ Error: {e}")
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"error": str(e)}
                                )
                                function_responses.append(function_response)
                        else:
                            print(f"   ✗ Tool not found: {fc.name}")
                    
                    if function_responses:
                        await session.send_tool_response(function_responses=function_responses)
                        
        except Exception as e:
            print(f"❌ Receive Error: {e}")
            break

# --- MAIN ORCHESTRATOR ---
async def run_agent():
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        tools=[{
            "function_declarations": [
                tool_get_current_time_declaration,
                tool_list_events_declaration,
                tool_check_specific_slot_declaration,
                tool_find_nearest_slots_declaration,
                tool_smart_check_declaration,
                tool_book_meeting_declaration
            ]
        }],
        system_instruction=f"""You are Ojasva's Executive Scheduler AI. Timezone: Asia/Kolkata.
Current Time: {tools.get_current_time()}

=== AVAILABLE TOOLS ===
1. get_current_time() - Get current date/time to calculate relative dates
2. list_upcoming_events(max_results=5) - See upcoming calendar events with ISO timestamps
3. check_specific_slot(start_iso, duration_minutes) - Check if ONE specific slot is free
4. find_nearest_slots(start_search_iso, duration_minutes) - Find 3 free slots starting from a time
5. smart_check_availability(start_iso, duration) - Check slot + auto-suggest alternatives if busy
6. book_meeting(summary, start_iso, duration_minutes) - Book the meeting (needs confirmation first)

=== MANDATORY BOOKING WORKFLOW (NEVER SKIP STEPS) ===
**CRITICAL RULE: You MUST check availability before every booking. NO EXCEPTIONS.**

Step 1: User requests a meeting time
Step 2: ALWAYS call smart_check_availability OR check_specific_slot for that exact time
Step 3a: If tool returns "Available" → Ask for meeting title (if not provided)
Step 3b: If tool returns "Busy" → Offer the suggested alternatives
Step 4: After user confirms → ONLY THEN call book_meeting
Step 5: Read confirmation naturally

=== COMPLEX TIME CALCULATIONS ===
When user says "1 hour after my interview":
1. Call list_upcoming_events to find the interview
2. Parse the ISO timestamp (e.g., 2025-12-08T18:00:00+05:30)
3. Add 1 hour → 2025-12-08T19:00:00+05:30
4. MUST call smart_check_availability with this calculated time
5. Wait for result before proceeding

When user says "before my 5 PM meeting on Friday":
1. Calculate the time (e.g., 4 PM Friday)
2. MUST check availability first
3. Never assume it's free

=== ISO TIMESTAMP PARSING ===
Tool responses contain ISO timestamps like "2025-12-08T18:00:00+05:30"
Parse these to understand WHEN events occur:
- Extract year, month, day, hour, minute
- Compare with current time to determine relative timing
- NEVER hallucinate times - ONLY use data from tool responses

=== SPEAKING NATURALLY ===
Convert ISO timestamps when speaking:
- "2025-12-08T18:00:00+05:30" → "tomorrow at 6 PM" or "December 8th at 6 PM"
- "2025-12-07T19:00:00+05:30" → "today at 7 PM"
- Use ordinal numbers: 1st, 2nd, 3rd, 8th, 21st
- Say "tomorrow" if tomorrow, "today" if today
- Keep responses conversational (1-2 sentences)

=== TIME CONVERSION ===
Convert user's relative time to ISO format (YYYY-MM-DDTHH:MM:SS+05:30):
- "tomorrow at 2pm" → 2025-12-08T14:00:00+05:30
- "Monday morning" → 2025-12-09T09:00:00+05:30
- "1 hour after X event" → [X event time] + 01:00:00

Use get_current_time() to calculate correct dates.

=== ADDITIONAL EXAMPLES ===

USER: "Schedule a meeting for tomorrow at 3 PM"
YOU: [Call smart_check_availability('2025-12-08T15:00:00+05:30', 60)]
TOOL: "Available"
YOU: "Tomorrow at 3 PM is free! What should I call this meeting?"
USER: "Product Review"
YOU: [Call book_meeting('Product Review', '2025-12-08T15:00:00+05:30', 60)]

USER: "Find a time next week for a 30-minute call"
YOU: [Call find_nearest_slots('2025-12-09T09:00:00+05:30', 30)]
TOOL: "Available slots: 2025-12-09T09:00:00+05:30, 2025-12-09T09:30:00+05:30..."
YOU: "I found slots next Monday: 9 AM, 9:30 AM, and 10 AM. Which works?"
USER: "9 AM"
YOU: [Call smart_check_availability('2025-12-09T09:00:00+05:30', 30)] (double-check)
TOOL: "Available"
YOU: "Great! What's this call about?"

**WRONG EXAMPLE (NEVER DO THIS):**
User: "Book a meeting 1 hour after my interview tomorrow"
You: [Calculates time as 7 PM] [Calls book_meeting directly] WRONG!

**CORRECT EXAMPLE:**
User: "Book a meeting 1 hour after my interview tomorrow"
You: [Calls list_upcoming_events to find interview time]
Tool: "Event: Gen AI Interview at 2025-12-08T18:00:00+05:30"
You: [Calculates 1 hour after = 2025-12-08T19:00:00+05:30]
     [Calls smart_check_availability with start_iso='2025-12-08T19:00:00+05:30']
Tool: "Busy. Alternatives: 2025-12-09T09:00:00+05:30, 2025-12-09T09:30:00+05:30"
You: "7 PM tomorrow is already booked. How about Monday at 9 AM or 9:30 AM instead?"

REMEMBER: Never book without checking availability first. This prevents double-booking!"""
    )
    
    print("🔌 Connecting to Gemini Live...")
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        print("✅ Connected! Start speaking...")
        
        tasks = [
            asyncio.create_task(listen_mic()),
            asyncio.create_task(play_speaker()),
            asyncio.create_task(send_to_gemini(session)),
            asyncio.create_task(receive_from_gemini(session)),
        ]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
