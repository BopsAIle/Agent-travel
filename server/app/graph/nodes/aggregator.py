"""Node dong bo cac nhanh chay song song."""


from app.graph.state import TripState


def data_aggregator_agent(state: TripState) -> dict:
    """A simple node to act as a synchronization point for parallel branches."""
    print("--- Aggregating Flight, Hotel, and Event data ---")
   
    return {}
