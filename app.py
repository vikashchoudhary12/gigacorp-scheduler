"""
Enhanced GigaCorp Scheduling Assistant
Professional UI with modern features!
"""

import uuid
import json
import os
from datetime import datetime, timedelta

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

import db
from graph import build_graph

# Page config
st.set_page_config(
    page_title="GigaCorp Scheduler",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database
db.init_db()
CHECKPOINT_DB = "scheduler_state.sqlite"


def get_llm(provider: str, model: str, api_key: str):
    if provider == "OpenAI":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=0.2, api_key=api_key)
    elif provider == "Groq (free)":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            temperature=0.2,
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
    else:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, temperature=0.2, api_key=api_key)


# --- Sidebar ---
st.sidebar.title("⚙️ Settings")

# LLM Provider
provider = st.sidebar.selectbox("LLM Provider", ["Groq (free)", "Anthropic", "OpenAI"], index=0)
default_models = {
    "Anthropic": "claude-3-5-haiku-20241022",
    "OpenAI": "gpt-4o-mini",
    "Groq (free)": "llama-3.3-70b-versatile",
}
model = st.sidebar.text_input("Model", value=default_models[provider])

# API Key
secret_key_names = {
    "Anthropic": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "Groq (free)": "GROQ_API_KEY",
}
secret_key_name = secret_key_names[provider]
try:
    api_key = st.secrets.get(secret_key_name, "")
except Exception:
    api_key = ""
api_key = st.sidebar.text_input(
    f"{provider} API Key", value=api_key, type="password",
    help="Falls back to Streamlit secrets if left blank."
)



# Thread ID
query_params = st.query_params
if "thread_id" not in query_params:
    new_id = str(uuid.uuid4())[:8]
    st.query_params["thread_id"] = new_id
thread_id = query_params["thread_id"]
st.sidebar.divider()
st.sidebar.caption(f"Conversation ID: `{thread_id}`")
if st.sidebar.button("🗑️ New Conversation"):
    st.query_params["thread_id"] = str(uuid.uuid4())[:8]
    st.rerun()


# --- Main UI ---
st.title("📅 GigaCorp Scheduling Assistant")
st.markdown("Your professional AI-powered booking companion!")

# Quick Info Section
with st.expander("📋 Quick Info", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**🕒 Business Hours**")
        st.write(", ".join(db.BUSINESS_HOURS))
    with col2:
        st.markdown("**📦 Available Services**")
        for service in db.SERVICE_TYPES:
            st.write(f"- {service}")

# Tabs
tab1, tab2 = st.tabs(["💬 Chat Assistant", "📊 My Bookings"])

with tab1:
    config = {"configurable": {"thread_id": thread_id}}

    # Load history
    try:
        with SqliteSaver.from_conn_string(CHECKPOINT_DB) as checkpointer:
            temp_graph = build_graph(get_llm(provider, model, api_key or "placeholder"), checkpointer)
            existing_state = temp_graph.get_state(config)
            history = existing_state.values.get("messages", []) if existing_state.values else []
    except Exception:
        history = []

    # Display chat history
    for msg in history:
        if isinstance(msg, HumanMessage):
            with st.chat_message("user"):
                st.markdown(msg.content)
        elif isinstance(msg, AIMessage) and msg.content:
            with st.chat_message("assistant"):
                st.markdown(msg.content)

    # User input
    user_input = st.chat_input("How can I help you? (e.g., 'Book a strategy session tomorrow at 2pm')")
    if user_input:
        if not api_key:
            st.error("Please enter your API key in the sidebar!")
            st.stop()

        with st.chat_message("user"):
            st.markdown(user_input)

        try:
            with SqliteSaver.from_conn_string(CHECKPOINT_DB) as checkpointer:
                llm = get_llm(provider, model, api_key)
                graph = build_graph(llm, checkpointer)

                with st.spinner("Thinking..."):
                    result = graph.invoke(
                        {"messages": [HumanMessage(content=user_input)], "route": ""},
                        config=config,
                    )

            new_messages = result["messages"]
            turn_start = max(
                i for i, m in enumerate(new_messages)
                if isinstance(m, HumanMessage) and m.content == user_input
            )
            # Check for tool results to show alerts
            latest_booking = None
            for msg in new_messages[turn_start + 1:]:
                if isinstance(msg, ToolMessage):
                    try:
                        tool_result = json.loads(msg.content)
                        if msg.name == "reserve_slot" and tool_result.get("success"):
                            latest_booking = tool_result
                            st.success(f"""
                            ✅ Booking Confirmed!
                            - Booking ID: {tool_result.get('booking_id')}
                            - Date: {tool_result.get('date')}
                            - Time: {tool_result.get('time')}
                            - Service: {tool_result.get('service_type')}
                            - Email: {tool_result.get('email')}
                            """)
                        elif msg.name in ["cancel_booking_tool", "reschedule_booking_tool"] and tool_result.get("success"):
                            st.success(f"✅ {tool_result.get('message')}")
                    except:
                        pass
            # Show download button if we have a new booking
            if latest_booking:
                ics = generate_ics(latest_booking)
                st.download_button(
                    label="📅 Add This Booking to Your Calendar",
                    data=ics,
                    file_name=f"gigacorp-booking-{latest_booking['booking_id']}.ics",
                    mime="text/calendar"
                )
            # Now display all messages
            for msg in new_messages[turn_start + 1:]:
                if isinstance(msg, AIMessage) and msg.content:
                    with st.chat_message("assistant"):
                        st.markdown(msg.content)
                elif isinstance(msg, ToolMessage):
                    with st.expander(f"🔧 Tool: {msg.name}", expanded=False):
                        st.json(msg.content)
        except Exception as e:
            st.error(f"Error: {e}")

def generate_ics(booking):
    """Generate an ICS calendar file for a booking"""
    from datetime import datetime, timedelta
    import uuid
    
    date_str = booking["date"]
    time_str = booking["time"]
    dt_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt_end = dt_start + timedelta(hours=1)  # Default 1-hour duration
    
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//GigaCorp Scheduler//EN
BEGIN:VEVENT
UID:{uuid.uuid4()}@gigacorp-scheduler
DTSTAMP:{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}
DTSTART:{dt_start.strftime("%Y%m%dT%H%M%S")}
DTEND:{dt_end.strftime("%Y%m%dT%H%M%S")}
SUMMARY:{booking['service_type']}
DESCRIPTION:Booking ID: {booking['id']}
ATTENDEE;CN={booking['email']}:mailto:{booking['email']}
END:VEVENT
END:VCALENDAR"""
    return ics_content

with tab2:
    st.subheader("📊 View Your Bookings")
    email = st.text_input("Enter your email to view bookings:", placeholder="you@example.com")
    if email:
        bookings = db.get_user_bookings(email)
        if bookings:
            for booking in bookings:
                status_color = "green" if booking["status"] == "confirmed" else "red"
                with st.container(border=True):
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.markdown(f"**ID:** {booking['id']}")
                        st.markdown(f"**Service:** {booking['service_type']}")
                        st.markdown(f"**Date:** {booking['date']}")
                        st.markdown(f"**Time:** {booking['time']}")
                        st.markdown(f"**Status:** :{status_color}[{booking['status'].upper()}]")
                    with col_b:
                        if booking["status"] == "confirmed":
                            # Download ICS button
                            ics = generate_ics(booking)
                            st.download_button(
                                label="📅 Add to Calendar",
                                data=ics,
                                file_name=f"gigacorp-booking-{booking['id']}.ics",
                                mime="text/calendar",
                                key=f"ics_{booking['id']}"
                            )
                            if st.button(f"❌ Cancel #{booking['id']}", key=f"cancel_{booking['id']}"):
                                success, message = db.cancel_booking(booking["id"], email)
                                if success:
                                    st.success(message)
                                    st.rerun()
                                else:
                                    st.error(message)
        else:
            st.info("No bookings found for this email!")
