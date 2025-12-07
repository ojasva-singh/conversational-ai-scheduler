# 🗓️ Smart Scheduler AI - Voice-Enabled Calendar Assistant

An intelligent, voice-powered AI scheduling assistant built with Google's Gemini 2.5 Flash Live API that understands natural language, manages your Google Calendar, and handles complex scheduling scenarios through conversational interactions.

## 🎯 Purpose

Smart Scheduler AI eliminates the friction of calendar management by providing:

- **Natural Voice Conversations**: Speak naturally to check availability, book meetings, and resolve conflicts
- **Intelligent Conflict Resolution**: Automatically suggests alternatives when requested times are unavailable
- **Multi-Modal Interaction**: Use voice (CLI) or web-based UI
- **Complex Time Parsing**: Understands relative time expressions like "tomorrow afternoon" or "1 hour after my interview"
- **Real-Time Calendar Integration**: Direct integration with Google Calendar for accurate, up-to-date scheduling

## ✨ Key Features

### Core Capabilities
- ✅ **Voice-Native Interaction** - Bidirectional audio streaming with <800ms latency
- ✅ **Smart Availability Checking** - Automatically checks conflicts before booking
- ✅ **Alternative Suggestions** - Uses LangGraph to intelligently suggest alternative slots
- ✅ **Natural Language Understanding** - Handles complex temporal queries
- ✅ **Google Calendar Integration** - Full read/write access to your calendar
- ✅ **Agentic Architecture** - Multi-step reasoning with tool calling

### Advanced Features
- Context-aware scheduling (e.g., "book 1 hour after my next interview")
- Conflict detection with automatic alternatives
- ISO 8601 timestamp handling with timezone awareness
- Support for variable meeting durations

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Interface                          │
│  ┌──────────────────┐          ┌─────────────────────┐     │
│  │  CLI (main.py)   │          │  Web UI (ui.py)     │     │
│  │  -  PyAudio       │          │  -  FastAPI          │     │
│  │  -  Native Audio  │          │  -  WebSockets       │     │
│  └────────┬─────────┘          └──────────┬──────────┘     │
└───────────┼────────────────────────────────┼────────────────┘
            │                                │
            └────────────┬───────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Gemini 2.5 Flash Live API                       │
│  -  Native Audio Processing (16kHz → 24kHz)                   │
│  -  Real-time Function Calling                                │
│  -  Context Management & Tool Orchestration                   │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Tool Layer (tools.py)                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  -  get_current_time()                                │   │
│  │  -  list_upcoming_events()                            │   │
│  │  -  check_specific_slot()                             │   │
│  │  -  find_nearest_slots()                              │   │
│  │  -  book_meeting()                                    │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│        LangGraph Workflow (scheduler_logic.py)               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  smart_check_availability()                          │   │
│  │  ├─→ Check Availability Node                         │   │
│  │  ├─→ Route: Available / Busy                         │   │
│  │  └─→ Suggest Alternatives Node                       │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│              Google Calendar API                             │
│  -  OAuth 2.0 Service Account Authentication                  │
│  -  Events API (list, insert, query)                          │
│  -  Timezone: Asia/Kolkata (IST)                              │
└─────────────────────────────────────────────────────────────┘
```

## 📋 Prerequisites

- **Python**: 3.9 or higher
- **Operating System**: macOS, Linux, or Windows
- **Google Cloud Project** with Calendar API enabled
- **Microphone** and **speakers/headphones** for voice mode
- **Google API Key** for Gemini API

## 🚀 Installation

### Step 1: Clone the Repository

```
git clone https://github.com/yourusername/smart-scheduler-ai.git
cd smart-scheduler-ai
```

### Step 2: Create Virtual Environment

```
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Step 3: Install Dependencies

```
pip install -r requirements.txt
```

**System Dependencies (for PyAudio):**

**macOS:**
```
brew install portaudio
```

**Ubuntu/Debian:**
```
sudo apt-get install portaudio19-dev python3-pyaudio
```

**Windows:**
```
# PyAudio wheels are available via pip
pip install pipwin
pipwin install pyaudio
```

### Step 4: Set Up Google Calendar API

#### 4.1 Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable **Google Calendar API**:
   - Navigate to **APIs & Services** → **Library**
   - Search for "Google Calendar API"
   - Click **Enable**

#### 4.2 Create Service Account

1. Navigate to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **Service Account**
3. Fill in service account details
4. Grant role: **Project** → **Editor**
5. Click **Done**

#### 4.3 Generate Service Account Key

1. Click on the created service account
2. Go to **Keys** tab
3. Click **Add Key** → **Create New Key**
4. Choose **JSON** format
5. Download and save as `credentials.json` in project root

#### 4.4 Share Calendar with Service Account

1. Open [Google Calendar](https://calendar.google.com)
2. Click on your calendar's settings (⚙️)
3. Select **Share with specific people**
4. Add the service account email (found in `credentials.json` as `client_email`)
5. Grant **Make changes to events** permission

### Step 5: Get Gemini API Key

1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Click **Get API Key**
3. Create or select a project
4. Copy the generated API key

### Step 6: Configure Environment Variables

Create a `.env` file in the project root:

```
cp example.env .env
```

Edit `.env`:

```
# Google Gemini API
GOOGLE_API_KEY=your_gemini_api_key_here

# Google Calendar (Optional - defaults to 'primary')
CALENDAR_ID=primary
```

## 🎮 Usage

### Option 1: CLI Voice Mode (Recommended)

Run the terminal-based voice interface:

```
python3 main.py
```

**Stop:** Press `Ctrl+C` to end the session

### Option 2: Web UI Mode

Launch the web interface:

```
python3 ui.py
```

**UI Features:**
- Click **Start Conversation** to begin
- Animated waveform shows when AI is speaking
- Activity log displays tool calls in real-time
- Click **End Call** to stop

## 🗣️ Supported Commands

### Query Commands
- "When is my next meeting?"
- "What's on my calendar for tomorrow?"
- "Am I free on Friday afternoon?"
- "Show me my schedule for next week"

### Scheduling Commands
- "Book a meeting tomorrow at 2 PM"
- "Schedule a 30-minute call on Monday morning"
- "Find me a free slot next week"
- "Book a meeting 1 hour after my interview tomorrow"

### Complex Queries
- "Find a time between 2 PM and 5 PM tomorrow"
- "Schedule something before my 6 PM meeting on Friday"
- "Book the next available slot after 3 PM"

## 🛠️ Configuration

### Timezone Configuration

Edit `tools.py`:

```
USER_TIMEZONE = 'America/New_York'  # Change as needed
```

Supported timezones: [IANA Time Zone Database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

### Audio Settings

Edit `main.py`:

```
SEND_SAMPLE_RATE = 16000  # Microphone input
RECEIVE_SAMPLE_RATE = 24000  # AI output
CHUNK_SIZE = 1024  # Buffer size
```

## 🧪 Testing Scenarios

### Basic Scheduling
```
User: "Schedule a meeting tomorrow at 3 PM"
Expected: Checks availability → Asks for title → Books meeting
```

### Conflict Resolution
```
User: "Book something at 6 PM tomorrow"
Scenario: Slot is busy
Expected: Returns alternatives automatically
```

### Complex Time Parsing
```
User: "Find a slot 2 hours before my Friday meeting"
Expected: Lists events → Calculates time → Checks availability
```

### Relative Scheduling
```
User: "Book 30 minutes the day after tomorrow morning"
Expected: Calculates date → Finds morning slots → Confirms
```