import sys
import asyncio
import threading
import pyaudio
import time
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QBrush

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Import your existing logic
import tools
import scheduler_logic

load_dotenv()

# --- CONFIGURATION ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
MODEL = "gemini-2.5-flash-native-audio-preview-09-2025"

# --- BACKEND WORKER (Runs in separate thread) ---
class AgentWorker(QThread):
    # Signals to update the UI safely
    status_changed = pyqtSignal(str) # "listening", "speaking", "processing"
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.client = genai.Client(http_options={'api_version': 'v1alpha'})
        self.audio_queue_mic = asyncio.Queue(maxsize=5)
        self.audio_queue_output = asyncio.Queue()
        self.stop_event = asyncio.Event()
        self.loop = None
        
        # Initialize Tools
        self.tools_map = {
            "get_current_time": lambda: tools.get_current_time(),
            "list_upcoming_events": lambda max_results=5: tools.list_upcoming_events(max_results),
            "check_specific_slot": lambda start_iso, duration_minutes=60: tools.check_specific_slot(start_iso, duration_minutes),
            "find_nearest_slots": lambda start_search_iso, duration_minutes=60: tools.find_nearest_slots(start_search_iso, duration_minutes),
            "smart_check_availability": lambda start_iso, duration=60: scheduler_logic.smart_check_availability(start_iso, duration),
            "book_meeting": lambda summary, start_iso, duration_minutes=60: tools.book_meeting(summary, start_iso, duration_minutes)
        }
        
        self.tool_declarations = [
            {"name": "get_current_time", "description": "Returns the current date and time in Asia/Kolkata timezone. Use this to understand 'now' and calculate relative times.", "parameters": {"type": "object", "properties": {}}},
            {"name": "list_upcoming_events", "description": "Lists the next 5 upcoming events.", "parameters": {"type": "object", "properties": {"max_results": {"type": "integer", "default": 5}}}},
            {"name": "check_specific_slot", "description": "Checks if a specific time slot is free. Returns 'Available' or conflict details.", "parameters": {"type": "object", "properties": {"start_iso": {"type": "string"}, "duration_minutes": {"type": "integer", "default": 60}}, "required": ["start_iso"]}},
            {"name": "find_nearest_slots", "description": "Finds up to 3 free time slots starting from a given time, within the next 48 hours, usually between 9 AM - 6 PM , but open to find slots even early morning or late night.", "parameters": {"type": "object", "properties": {"start_search_iso": {"type": "string"}, "duration_minutes": {"type": "integer", "default": 60}}, "required": ["start_search_iso"]}},
            {"name": "smart_check_availability", "description": "Smart availability checker - checks if a slot is free, and if busy, automatically suggests 3 alternative times.", "parameters": {"type": "object", "properties": {"start_iso": {"type": "string"}, "duration": {"type": "integer", "default": 60}}, "required": ["start_iso"]}},
            {"name": "book_meeting", "description": "Books a meeting at the specified time. Only call this after user confirmation.", "parameters": {"type": "object", "properties": {"summary": {"type": "string"}, "start_iso": {"type": "string"}, "duration_minutes": {"type": "integer", "default": 60}}, "required": ["summary", "start_iso"]}}
        ]

    async def listen_mic(self):
        pya = pyaudio.PyAudio()
        try:
            mic_info = pya.get_default_input_device_info()
            stream = await asyncio.to_thread(
                pya.open, format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
                input=True, input_device_index=mic_info["index"], frames_per_buffer=CHUNK_SIZE
            )
            while not self.stop_event.is_set():
                data = await asyncio.to_thread(stream.read, CHUNK_SIZE, exception_on_overflow=False)
                if not self.audio_queue_mic.full():
                    await self.audio_queue_mic.put(types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
        except Exception as e:
            print(f"Mic Error: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            pya.terminate()

    async def play_speaker(self):
        pya = pyaudio.PyAudio()
        stream = await asyncio.to_thread(
            pya.open, format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True
        )
        try:
            while not self.stop_event.is_set():
                bytestream = await self.audio_queue_output.get()
                if bytestream is None: break 
                
                self.status_changed.emit("speaking")
                await asyncio.to_thread(stream.write, bytestream)
                self.audio_queue_output.task_done()
                
                if self.audio_queue_output.empty():
                    self.status_changed.emit("listening")
        except Exception as e:
            print(f"Speaker Error: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            pya.terminate()

    async def send_to_gemini(self, session):
        while not self.stop_event.is_set():
            try:
                audio_blob = await asyncio.wait_for(self.audio_queue_mic.get(), timeout=1.0)
                await session.send_realtime_input(audio=audio_blob)
            except asyncio.TimeoutError:
                continue

    async def receive_from_gemini(self, session):
        while not self.stop_event.is_set():
            try:
                turn = session.receive()
                async for response in turn:
                    if self.stop_event.is_set(): return

                    if response.server_content and response.server_content.interrupted:
                        while not self.audio_queue_output.empty():
                            self.audio_queue_output.get_nowait()
                        continue

                    if response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.inline_data and isinstance(part.inline_data.data, bytes):
                                await self.audio_queue_output.put(part.inline_data.data)

                    if response.tool_call:
                        self.status_changed.emit("processing")
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            func = self.tools_map.get(fc.name)
                            if func:
                                try:
                                    result = func(**fc.args)
                                    function_responses.append(types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": result}
                                    ))
                                except Exception as e:
                                    function_responses.append(types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"error": str(e)}
                                    ))
                        if function_responses:
                            await session.send_tool_response(function_responses=function_responses)
                            self.status_changed.emit("listening")

            except Exception as e:
                print(f"Receive Error: {e}")
                self.error_occurred.emit(str(e))
                break

    async def run_loop(self):
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            tools=[{"function_declarations": self.tool_declarations}],
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

IMPORTANT POINTS
- Never book without checking availability first. This prevents double-booking!
- Book a meeting regardless of it NOT falling under the business hours"""
    )
        
        async with self.client.aio.live.connect(model=MODEL, config=config) as session:
            self.status_changed.emit("listening")
            tasks = [
                asyncio.create_task(self.listen_mic()),
                asyncio.create_task(self.play_speaker()),
                asyncio.create_task(self.send_to_gemini(session)),
                asyncio.create_task(self.receive_from_gemini(session)),
            ]
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                pass

    def run(self):
        """Entry point for QThread"""
        self.stop_event.clear()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run_loop())
        self.finished.emit()

    def stop(self):
        """Force stops the worker and closes streams immediately"""
        self.stop_event.set()
        
        # 1. Force close streams to break blocking read/write
        if self.mic_stream and self.mic_stream.is_active():
            try:
                self.mic_stream.stop_stream()
                self.mic_stream.close()
            except: pass
            
        if self.spk_stream and self.spk_stream.is_active():
            try:
                self.spk_stream.stop_stream()
                self.spk_stream.close()
            except: pass

        # 2. Unblock queues so loops can cycle and check stop_event
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: self.audio_queue_output.put_nowait(None))
            
            # Cancel all tasks in the loop
            for task in asyncio.all_tasks(self.loop):
                task.cancel()

# --- CUSTOM WIDGET: ANIMATED ORB ---
class StatusOrb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 200)
        self.color = QColor("#444444")
        self.target_color = QColor("#444444")
        
    def set_status(self, status):
        if status == "listening":
            self.target_color = QColor("#ff4b4b") # Red
        elif status == "speaking":
            self.target_color = QColor("#4b9dff") # Blue
        elif status == "processing":
            self.target_color = QColor("#ffc107") # Yellow
        else:
            self.target_color = QColor("#444444") # Grey
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw Circle
        brush = QBrush(self.target_color)
        painter.setBrush(brush)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(25, 25, 150, 150)

# --- MAIN WINDOW ---
class SchedulerUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Executive Scheduler AI")
        self.setFixedSize(400, 500)
        self.setStyleSheet("background-color: #1e1e1e; color: white; font-family: Helvetica;")

        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 40, 20, 20)

        # Header
        self.header = QLabel("Ojasva's Agent")
        self.header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        self.header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.header)

        # Orb Animation
        self.orb = StatusOrb()
        layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status Text
        self.status_label = QLabel("Ready to Connect")
        self.status_label.setStyleSheet("font-size: 14px; color: #888888;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)
        
        self.start_btn = QPushButton("Start Call")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setStyleSheet("""
            QPushButton { background-color: #28a745; border-radius: 8px; padding: 12px; font-weight: bold; }
            QPushButton:hover { background-color: #218838; }
            QPushButton:disabled { background-color: #555555; color: #888; }
        """)
        self.start_btn.clicked.connect(self.start_agent)
        
        self.stop_btn = QPushButton("End Call")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton { background-color: #dc3545; border-radius: 8px; padding: 12px; font-weight: bold; }
            QPushButton:hover { background-color: #c82333; }
            QPushButton:disabled { background-color: #555555; color: #888; }
        """)
        self.stop_btn.clicked.connect(self.stop_agent)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        # Worker
        self.worker = None

    def start_agent(self):
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Connecting...")
        
        self.worker = AgentWorker()
        self.worker.status_changed.connect(self.update_status)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def stop_agent(self):
        if self.worker:
            self.status_label.setText("Disconnecting...")
            self.worker.stop()
            # We wait for the finished signal to reset UI

    @pyqtSlot(str)
    def update_status(self, status):
        text_map = {
            "listening": "Listening...",
            "speaking": "Agent Speaking...",
            "processing": "Checking Calendar...",
        }
        self.status_label.setText(text_map.get(status, status))
        self.orb.set_status(status)

    @pyqtSlot(str)
    def handle_error(self, error):
        self.status_label.setText(f"Error: {error}")
        self.stop_agent()

    @pyqtSlot()
    def on_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Call Ended")
        self.orb.set_status("idle")
        self.worker = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchedulerUI()
    window.show()
    sys.exit(app.exec())