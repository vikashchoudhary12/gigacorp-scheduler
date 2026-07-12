"""
GigaCorp Scheduling Assistant
------------------------------
Streamlit UI around a two-agent LangGraph workflow: a Triage Agent that
routes between general chit-chat and booking intent, and a Booking
Specialist that calls tools to check availability, reserve a slot, and
send a mock confirmation notification.

Conversation state is persisted per-thread in a local SQLite database via
LangGraph's SqliteSaver, keyed by a thread_id stored in the page's URL query
params — so refreshing the page keeps the same conversation.
"""

import uuid

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

import db
from graph import build_graph

st.set_page_config(page_title="GigaCorp Scheduler", page_icon="📅", layout="centered")

db.init_db()

CHECKPOINT_DB = "scheduler_state.sqlite"


# ---------------------------------------------------------------------------
# LLM setup — same three free/paid provider options as the support assistant
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ Configuration")

provider = st.sidebar.selectbox("LLM Provider", ["Groq (free)", "Anthropic", "OpenAI"])

default_models = {
    "Anthropic": "claude-3-5-haiku-20241022",
    "OpenAI": "gpt-4o-mini",
    "Groq (free)": "llama-3.3-70b-versatile",
}
model = st.sidebar.text_input("Model", value=default_models[provider])

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
    help="Falls back to Streamlit secrets if left blank and a secret is configured.",
)

st.sidebar.divider()
webhook_url = st.sidebar.text_input(
    "Notification webhook URL (optional)",
    value="",
    placeholder="https://webhook.site/your-unique-url",
    help="Leave blank to use the default mock endpoint (httpbin.org/post). "
         "Paste your own https://webhook.site URL to watch confirmations arrive live.",
)
if webhook_url:
    import os as _os
    _os.environ["WEBHOOK_URL"] = webhook_url

st.sidebar.divider()
st.sidebar.markdown(
    "**Tools available to the Booking Specialist:**\n"
    "- `check_availability(date)`\n"
    "- `reserve_slot(date, time, email)`\n"
    "- `send_booking_notification(email, details)`"
)

# Thread ID lives in the URL so a page refresh keeps the same conversation.
query_params = st.query_params
if "thread_id" not in query_params:
    new_id = str(uuid.uuid4())[:8]
    st.query_params["thread_id"] = new_id
thread_id = st.query_params["thread_id"]
st.sidebar.divider()
st.sidebar.caption(f"Conversation ID: `{thread_id}` (kept in the URL — refresh-safe)")
if st.sidebar.button("🗑️ Start a new conversation"):
    st.query_params["thread_id"] = str(uuid.uuid4())[:8]
    st.rerun()


# ---------------------------------------------------------------------------
# Main chat UI
# ---------------------------------------------------------------------------
st.title("📅 GigaCorp Scheduling Assistant")
st.caption("Ask a general question, or say something like \"book me an appointment tomorrow at 10am, my email is jane@example.com\".")

config = {"configurable": {"thread_id": thread_id}}

# Render existing history for this thread (pulled straight from the
# checkpointer — this is what makes it survive a refresh).
try:
    with SqliteSaver.from_conn_string(CHECKPOINT_DB) as checkpointer:
        temp_graph = build_graph(get_llm(provider, model, api_key or "placeholder"), checkpointer)
        existing_state = temp_graph.get_state(config)
        history = existing_state.values.get("messages", []) if existing_state.values else []
except Exception:
    history = []

for m in history:
    if isinstance(m, HumanMessage):
        with st.chat_message("user"):
            st.markdown(m.content)
    elif isinstance(m, AIMessage) and m.content:
        with st.chat_message("assistant"):
            st.markdown(m.content)
    # ToolMessages and tool-call-only AIMessages are intermediate steps —
    # not rendered directly, to keep the chat readable.

user_input = st.chat_input("Type a message...")

if user_input:
    if not api_key:
        st.error(f"Please enter your {provider} API key in the sidebar to continue.")
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

            # Show every AI message produced this turn that has visible content
            # (tool-call-only messages are silent intermediate steps).
            new_messages = result["messages"]
            # Find where this turn's messages start (after the human message we just sent)
            turn_start = max(
                i for i, m in enumerate(new_messages)
                if isinstance(m, HumanMessage) and m.content == user_input
            )
            for m in new_messages[turn_start + 1:]:
                if isinstance(m, AIMessage) and m.content:
                    with st.chat_message("assistant"):
                        st.markdown(m.content)
                elif isinstance(m, ToolMessage):
                    with st.expander(f"🔧 Tool call: {m.name}", expanded=False):
                        st.code(m.content, language="json")

    except Exception as e:
        st.error(f"Something went wrong: {e}")
