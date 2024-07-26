from llama_index.core.tools import FunctionTool

# create an agent
def get_current_weather(location: str, unit: str) -> str:
    """Returns the secret fact."""
    if location.lower() == "seattle":
        return "Its chillin"
    else:
        return "I only help seattle ppl"

def get_current_traffic(location: str) -> str:
    """Returns the secret fact."""
    if location.lower() == "seattle":
        return "just take the bus lil bro"
    else:
        return "I only help seattle ppl and traffic probably sucks where you are"

functions = {
    "get_current_weather": FunctionTool.from_defaults(fn=get_current_weather), 
    "get_current_traffic": FunctionTool.from_defaults(fn=get_current_weather)
}