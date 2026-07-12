"""
graph.py — the multi-agent LangGraph workflow.

Two agents:
  * Triage: classifies each incoming message as "booking" or "general".
    General messages get answered directly. Booking-intent messages are
    routed to the Booking Specialist.
  * Booking Specialist: a tool-calling agent bound to check_availability,
    reserve_slot, and send_booking_notification. It loops with a ToolNode
    until it has a final reply with no more tool calls.

Input normalization: before the Booking Specialist ever sees the message,
we run dateparser over it to resolve any relative date phrase ("tomorrow",
"next Monday") into an absolute YYYY-MM-DD, and hand that resolution to the
agent as a grounding fact — so it isn't relying on the LLM's own date math.
"""

from datetime import datetime
from typing import Annotated, Literal, TypedDict

from dateparser.search import search_dates
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from tools import ALL_TOOLS, BUSINESS_HOURS as _BUSINESS_HOURS  # noqa: F401 (re-export for app.py)


class SchedulerState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: str


TRIAGE_CLASSIFY_PROMPT = (
    "You are a routing classifier for a scheduling assistant. Read the user's "
    "latest message and decide if they are trying to schedule, check, reschedule, "
    "or book an appointment (route: BOOKING), or if it's a general question/greeting "
    "unrelated to booking an appointment (route: GENERAL).\n\n"
    "Reply with exactly one word: BOOKING or GENERAL. Nothing else."
)

TRIAGE_GENERAL_PROMPT = (
    "You are a friendly front-desk assistant for a scheduling service. Answer the "
    "user's general question helpfully and briefly. If they seem to want to book, "
    "check, or manage an appointment, let them know they can just ask to book one."
)


def _last_human_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return m.content
    return ""


def make_triage_node(llm):
    def triage_node(state: SchedulerState):
        last_text = _last_human_text(state["messages"])
        classify_messages = [
            SystemMessage(content=TRIAGE_CLASSIFY_PROMPT),
            HumanMessage(content=last_text),
        ]
        classification = llm.invoke(classify_messages).content.strip().upper()

        if "BOOKING" in classification:
            return {"route": "booking"}

        general_messages = [SystemMessage(content=TRIAGE_GENERAL_PROMPT)] + state["messages"]
        reply = llm.invoke(general_messages)
        return {"messages": [reply], "route": "general"}

    return triage_node


def _resolve_dates_note(text: str) -> str:
    today = datetime.now()
    try:
        found = search_dates(text, settings={"RELATIVE_BASE": today})
    except Exception:
        found = None
    if not found:
        return ""
    parts = [f'"{phrase}" -> {dt.strftime("%Y-%m-%d %H:%M")}' for phrase, dt in found]
    return "Resolved date/time phrases found in the user's message: " + "; ".join(parts)


def make_booking_node(llm_with_tools):
    def booking_node(state: SchedulerState):
        today_str = datetime.now().strftime("%Y-%m-%d (%A)")
        last_text = _last_human_text(state["messages"])
        date_note = _resolve_dates_note(last_text)

        system_prompt = (
            "You are the Booking Specialist for a scheduling service. "
            f"Today's date is {today_str}. Business hours slots are: "
            f"{', '.join(_BUSINESS_HOURS)} (24h format), Monday-Sunday.\n\n"
            "Your job: collect a date, a time, and an email from the user, then book "
            "the appointment. Rules:\n"
            "1. Never call reserve_slot with a relative date like 'tomorrow' — always "
            "resolve it to an absolute YYYY-MM-DD first. "
            + (date_note + "\n" if date_note else "")
            + "2. Before reserving, call check_availability for the date if you haven't "
            "already confirmed the slot is free in this conversation.\n"
            "3. If reserve_slot fails because the slot was just taken, do NOT give up — "
            "look at the alternative_slots_same_day it returns and offer one or two of "
            "them to the user, or ask if they'd like a different date. Never fail silently.\n"
            "4. Once a slot is successfully reserved, call send_booking_notification to "
            "confirm it, then tell the user their appointment is booked with the date, "
            "time, and confirmation.\n"
            "5. If you're missing the date, time, or email, ask the user for exactly "
            "what's missing — don't guess."
        )
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        reply = llm_with_tools.invoke(messages)
        return {"messages": [reply]}

    return booking_node


def route_after_triage(state: SchedulerState) -> Literal["booking_agent", "__end__"]:
    return "booking_agent" if state.get("route") == "booking" else END


def build_graph(llm, checkpointer):
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    graph = StateGraph(SchedulerState)
    graph.add_node("triage", make_triage_node(llm))
    graph.add_node("booking_agent", make_booking_node(llm_with_tools))
    graph.add_node("tools", ToolNode(ALL_TOOLS))

    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route_after_triage, {"booking_agent": "booking_agent", END: END})
    graph.add_conditional_edges("booking_agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "booking_agent")

    return graph.compile(checkpointer=checkpointer)
