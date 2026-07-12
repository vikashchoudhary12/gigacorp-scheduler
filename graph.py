"""
graph.py — enhanced multi-agent LangGraph workflow.

Features: service types, cancellations, rescheduling, and more!
"""

from datetime import datetime
from typing import Annotated, Literal, TypedDict

from dateparser.search import search_dates
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from tools import ALL_TOOLS, BUSINESS_HOURS as _BUSINESS_HOURS, SERVICE_TYPES as _SERVICE_TYPES  # noqa: F401


class SchedulerState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: str


TRIAGE_CLASSIFY_PROMPT = (
    "You are a routing classifier for a scheduling assistant. Read the user's "
    "latest message and decide if they are trying to schedule, check, reschedule, cancel, "
    "or book an appointment, or view their bookings (route: BOOKING), or if it's a general "
    "question/greeting (route: GENERAL).\n\n"
    "Reply with exactly one word: BOOKING or GENERAL. Nothing else."
)

TRIAGE_GENERAL_PROMPT = (
    "You are a friendly front-desk assistant for a professional scheduling service. "
    "Answer the user's general questions helpfully and briefly. If they seem to want to "
    "book, check, reschedule, cancel, or view their appointments, guide them to do so."
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
            "You are the Booking Specialist for a professional scheduling service. "
            f"Today's date is {today_str}.\n"
            f"Business hours slots: {', '.join(_BUSINESS_HOURS)} (24h format, Mon-Sun).\n"
            f"Available service types: {', '.join(_SERVICE_TYPES)}.\n\n"
            "Your responsibilities:\n"
            "1. Book new appointments (need date, time, email, service type)\n"
            "2. View existing bookings (by email)\n"
            "3. Reschedule existing bookings\n"
            "4. Cancel existing bookings\n\n"
            "Rules:\n"
            "- Never use relative dates for tools; always resolve to YYYY-MM-DD first\n"
        )
        if date_note:
            system_prompt += date_note + "\n"
        system_prompt += (
            "- Always check availability before booking\n"
            "- If a slot is taken, offer alternatives from alternative_slots_same_day\n"
            "- After booking/rescheduling/canceling, give a CLEAR, DETAILED confirmation message right here in the chat (include date, time, service type, booking ID, and email)\n"
            "- When canceling/rescheduling, verify the booking_id and email match\n"
            "- If missing info, ask the user clearly for exactly what's needed\n"
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
