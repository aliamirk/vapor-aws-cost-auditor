"""Vapor LangGraph pipeline builder.

Constructs and compiles the StateGraph with:
- 7 collector nodes in parallel fan-out from START
- All collectors converge to 'aggregate'
- Linear pipeline: aggregate → analyze → render → END
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from vapor.graph.nodes.aggregate import aggregate
from vapor.graph.nodes.analyze import analyze
from vapor.graph.nodes.collect_ebs import collect_ebs
from vapor.graph.nodes.collect_ec2 import collect_ec2
from vapor.graph.nodes.collect_eip import collect_eip
from vapor.graph.nodes.collect_cost_explorer import collect_cost_explorer
from vapor.graph.nodes.collect_lambda import collect_lambda
from vapor.graph.nodes.collect_rds import collect_rds
from vapor.graph.nodes.collect_s3 import collect_s3
from vapor.graph.nodes.render import render
from vapor.graph.state import VaporState

# All collector node names for fan-out/convergence wiring
_COLLECTORS = [
    "collect_ec2",
    "collect_rds",
    "collect_s3",
    "collect_lambda",
    "collect_ebs",
    "collect_eip",
    "collect_cost_explorer",
]

# Mapping of node names to their implementation functions
_NODE_FUNCTIONS = {
    "collect_ec2": collect_ec2,
    "collect_rds": collect_rds,
    "collect_s3": collect_s3,
    "collect_lambda": collect_lambda,
    "collect_ebs": collect_ebs,
    "collect_eip": collect_eip,
    "collect_cost_explorer": collect_cost_explorer,
    "aggregate": aggregate,
    "analyze": analyze,
    "render": render,
}


def build_graph() -> CompiledStateGraph:
    """Construct and compile the Vapor LangGraph pipeline.

    The graph implements a static parallel fan-out pattern:
        START → [7 collectors] → aggregate → analyze → render → END

    Returns:
        A compiled LangGraph StateGraph ready for invocation.
    """
    graph = StateGraph(VaporState)

    # Register all 10 nodes
    for name, func in _NODE_FUNCTIONS.items():
        graph.add_node(name, func)

    # Parallel fan-out: START → each collector
    for collector in _COLLECTORS:
        graph.add_edge(START, collector)

    # Convergence: each collector → aggregate
    for collector in _COLLECTORS:
        graph.add_edge(collector, "aggregate")

    # Linear pipeline: aggregate → analyze → render → END
    graph.add_edge("aggregate", "analyze")
    graph.add_edge("analyze", "render")
    graph.add_edge("render", END)

    return graph.compile()
