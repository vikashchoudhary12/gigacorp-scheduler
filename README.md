# 📅 Enhanced GigaCorp Scheduling Assistant

A professional, multi-agent appointment-scheduling assistant built with **LangGraph** and **Streamlit**. Features include service types, cancellations, rescheduling, booking history, and a beautiful modern UI!

## 🚀 New Features

- **Service Types**: Choose from 5 pre-defined service options (General Consultation, Strategy Session, etc.)
- **Cancel Bookings**: Cancel existing appointments directly
- **View Bookings**: "My Bookings" tab to view all appointments by email
- **Professional UI**: Modern interface with tabs, expandable sections, and clean layout
- **Status Tracking**: Confirmed/Cancelled statuses with color coding
- **Booking IDs**: Unique IDs for easy reference

## Architecture

```
                ┌──────────┐
   user msg --> │  Triage  │
                └────┬─────┘
                     │  LLM classifies: BOOKING or GENERAL
          ┌──────────┴──────────┐
          │                     │
     route=GENERAL         route=BOOKING
          │                     │
     answers directly     ┌─────▼──────────┐
          │           ┌──>│ Booking         │
         END           │  │ Specialist      │
                      │  └────┬───────────┘
                      │       │ tool_calls present?
                      │  ┌────▼────┐
                      └──┤  Tools  │  (ToolNode)
                         └─────────┘
                      (loops back to Booking Specialist
                       until a final reply with no more
                       tool calls, then END)
```

## Tools

| Tool | Purpose |
|---|---|
| `check_availability(date)` | Check open slots for a specific date |
| `reserve_slot(date, time, email, service_type)` | Book a new appointment |
| `cancel_booking_tool(booking_id, email)` | Cancel an existing booking |
| `reschedule_booking_tool(booking_id, email, new_date, new_time)` | Reschedule a booking |
| `get_user_bookings_tool(email)` | Retrieve all bookings for an email |
| `get_service_types()` | List available service types |
| `send_booking_notification(email, details)` | Send confirmation notifications |

## Project Structure

```
gigacorp-scheduler/
├── app.py                          # Modern Streamlit UI
├── graph.py                        # Enhanced LangGraph workflow
├── tools.py                        # All booking tools
├── db.py                           # Enhanced SQLite database layer
├── requirements.txt
├── runtime.txt
├── .streamlit/secrets.toml.example
└── README.md
```

## Run Locally

```bash
# 1. Create virtual environment
python -m venv venv

# 2. Activate
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml and add your API keys

# 5. Run
streamlit run app.py
```

## Get an API Key

- **Groq (Free, Recommended)**: https://console.groq.com/keys
- **OpenAI**: https://platform.openai.com/api-keys
- **Anthropic**: https://console.anthropic.com/settings/keys

## Usage Examples

- **Book an appointment**: "Book a strategy session tomorrow at 2pm, my email is test@example.com"
- **View bookings**: "Show me my bookings for test@example.com"
- **Cancel booking**: "Cancel booking #1 for test@example.com"
- **Ask a question**: "What services do you offer?"

## Deploy for Free

Deploy on **Streamlit Community Cloud**:
1. Push to GitHub
2. Go to https://share.streamlit.io
3. Create new app and select your repo
4. Set main file to `app.py`
5. Advanced Settings: Python 3.11, add your API keys as secrets
6. Deploy!
