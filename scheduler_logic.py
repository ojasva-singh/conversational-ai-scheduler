from typing import TypedDict
from langgraph.graph import StateGraph, END
import tools

class SchedulerState(TypedDict):
    request_start_iso: str
    duration: int
    final_response: str
    status: str

def check_availability_node(state: SchedulerState):
    """Check availability using tools.check_specific_slot"""
    status = tools.check_specific_slot(state['request_start_iso'], state['duration'])
    
    return {"status": status}

def handle_available_node(state: SchedulerState):
    """Handles when slot is available"""
    return {"final_response": "Available"}

def find_alternative_node(state: SchedulerState):
    """User wanted X, but X is busy. Find nearest alternatives."""
    alternatives = tools.find_nearest_slots(
        state['request_start_iso'], 
        state['duration']
    )
    
    conflict_info = state.get('status', 'Conflict detected')
    return {"final_response": f"Busy. Alternatives: {alternatives}"}

# Build the Graph
workflow = StateGraph(SchedulerState)

workflow.add_node("check", check_availability_node)
workflow.add_node("available", handle_available_node)
workflow.add_node("suggest_alternatives", find_alternative_node)

# Routing Logic: Based on status field
def route_after_check(state):
    """Route based on availability status"""
    status = state.get("status", "")
    
    # If status is exactly "Available", slot is free
    if status == "Available":
        return "available"
    else:
        # Any other status means conflict
        return "suggest_alternatives"

# Set up the graph flow
workflow.set_entry_point("check")
workflow.add_conditional_edges("check", route_after_check, {
    "available": "available",
    "suggest_alternatives": "suggest_alternatives"
})
workflow.add_edge("available", END)
workflow.add_edge("suggest_alternatives", END)

app = workflow.compile()

def smart_check_availability(start_iso: str, duration: int = 60) -> str:
    """
    Entry point for the LLM.
    Returns either 'Available' or 'Busy. Alternatives: [slots]'
    """
    result = app.invoke({
        "request_start_iso": start_iso, 
        "duration": duration
    })
    return result["final_response"]