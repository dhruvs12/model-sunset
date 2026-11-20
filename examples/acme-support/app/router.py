"""Decide which backend tool a customer message needs."""
from openai import OpenAI

client = OpenAI()
ROUTER_MODEL = "o3"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_order",
        "description": "Fetch an order by id",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
}]


def route(message: str):
    return client.chat.completions.create(
        model=ROUTER_MODEL, tools=TOOLS, messages=[{"role": "user", "content": message}],
    )
