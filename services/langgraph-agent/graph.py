from langgraph.graph import StateGraph, END

from state import PropertyState
from nodes import (
    intake_node,
    classifier_node,
    confidence_node,
    rag_node,
    pricing_node,
    clarify_node,
    analyst_node,
    output_node,
    route_after_confidence,
)


def build_graph() -> StateGraph:
    graph = StateGraph(PropertyState)

    graph.add_node("intake_node",     intake_node)
    graph.add_node("classifier_node", classifier_node)
    graph.add_node("confidence_node", confidence_node)
    graph.add_node("rag_node",        rag_node)
    graph.add_node("pricing_node",    pricing_node)
    graph.add_node("clarify_node",    clarify_node)
    graph.add_node("analyst_node",    analyst_node)
    graph.add_node("output_node",     output_node)

    graph.set_entry_point("intake_node")

    graph.add_edge("intake_node",     "classifier_node")
    graph.add_edge("classifier_node", "confidence_node")

    graph.add_conditional_edges(
        "confidence_node",
        route_after_confidence,
        {
            "rag_node":     "rag_node",
            "clarify_node": "clarify_node",
        },
    )

    graph.add_edge("rag_node",     "pricing_node")
    graph.add_edge("pricing_node", "analyst_node")
    graph.add_edge("analyst_node", "output_node")
    graph.add_edge("clarify_node", "output_node")
    graph.add_edge("output_node",  END)

    return graph.compile()


# Singleton compiled graph
app = build_graph()
