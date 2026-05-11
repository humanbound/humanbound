from langchain.tools import tool


@tool
def search_flights(query: str) -> str:
    """Search for flights."""
    return "results"
