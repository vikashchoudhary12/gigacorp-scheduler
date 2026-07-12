# GigaCorp Scheduling Assistant

A multi-agent appointment-scheduling assistant built with **LangGraph**. A Triage Agent
routes each message; a Booking Specialist calls real (mocked) tools to check
availability, reserve a slot, and send a confirmation — negotiating alternatives if a
slot's taken, instead of failing silently. Conversation state persists in SQLite, keyed
to a thread ID kept in the URL, so it survives a page refresh.

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

- **Triage Agent** (`graph.py: make_triage_node`): one LLM call classifies the latest
  user message as `BOOKING` or `GENERAL`. General messages get a direct, friendly reply
  and the graph ends there — the Booking Specialist and its tools are never touched.
  Booking-intent messages are routed onward.
- **Booking Specialist** (`graph.py: make_booking_node`): a tool-calling agent bound to
  three tools via `llm.bind_tools(...)`. It's given today's date and the business-hour
  slot list in its system prompt, and instructed to check availability before reserving,
  to negotiate alternatives on conflict, and to confirm via notification once booked.
- **Input normalization**: before the Booking Specialist runs, `dateparser.search.search_dates`
  scans the user's message for relative date/time phrases ("tomorrow at 3pm") and resolves
  them to an absolute date, which is injected into the system prompt as a grounding fact —
  so the agent isn't relying on its own arithmetic for "tomorrow."
- **Negotiation**: `reserve_slot` uses a SQLite `UNIQUE(date, time)` constraint. A
  conflicting reservation fails cleanly and returns the day's remaining open slots, which
  the agent is instructed to offer the user rather than giving up.
- **State persistence**: `langgraph.checkpoint.sqlite.SqliteSaver` checkpoints the full
  graph state (all messages) to `scheduler_state.sqlite`, keyed by `thread_id`. The
  Streamlit app stores `thread_id` in the page's URL query params (`st.query_params`), so
  reloading the page reconnects to the same conversation and its full history.

## Tools (mocked but functional)

| Tool | What it actually does |
|---|---|
| `check_availability(date)` | Queries the local `scheduler.db` SQLite `bookings` table and returns open slots from a fixed business-hours list. |
| `reserve_slot(date, time, email)` | Inserts into `bookings`; a `UNIQUE(date, time)` constraint makes double-booking fail predictably (caught and turned into a negotiation response with alternatives). |
| `send_booking_notification(email, details)` | POSTs a JSON payload to a webhook URL — defaults to `https://httpbin.org/post` (public, free, no signup, just echoes the payload back to prove it fired). Point it at your own `https://webhook.site` URL (sidebar field) to watch confirmations arrive live in your browser. |

## Project structure

```
gigacorp-scheduler/
├── app.py                          # Streamlit UI
├── graph.py                        # LangGraph state machine (both agents + routing)
├── tools.py                        # The three tools
├── db.py                           # SQLite helpers (bookings table)
├── requirements.txt
├── runtime.txt                     # pins Python 3.11 for host compatibility
├── .streamlit/secrets.toml.example
└── README.md
```

## Run it locally

```bash
cd gigacorp-scheduler
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and add a key for whichever provider you'll use

streamlit run app.py
```

Pick a provider in the sidebar — **Groq (free)** requires no payment method at all: get a
key at [console.groq.com](https://console.groq.com) → API Keys.

### Try it
- **General**: "What are your business hours?" — answered directly, no tools touched.
- **Booking**: "Book me an appointment tomorrow at 10am, my email is jane@example.com" —
  the Booking Specialist checks availability, reserves the slot, and sends a
  notification. Expand the "🔧 Tool call" sections to see exactly what each tool
  returned.
- **Negotiation**: book the same date/time twice (e.g. from two browser tabs, or just ask
  again) — the second attempt will hit the conflict and the agent will offer you an
  alternative slot instead of failing.
- **Refresh-safe memory**: refresh the page — your conversation and thread ID (visible in
  the URL) stay intact, pulled straight from `scheduler_state.sqlite`.

## Deploy for free

Same process as the support-assistant project — push to GitHub, then deploy on
**Streamlit Community Cloud** (share.streamlit.io): New app → pick this repo → main file
`app.py` → Advanced settings → Python 3.11 → add your API key secret → Deploy.

Note: Streamlit Community Cloud's filesystem is ephemeral on redeploys/reboots — the
SQLite files (`scheduler.db`, `scheduler_state.sqlite`) will reset if the app restarts.
For this assignment's purposes that's expected; for real production use you'd point these
at a persistent database instead.
