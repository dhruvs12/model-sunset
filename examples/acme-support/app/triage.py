"""Classify an incoming support ticket. The rest of the app parses this JSON."""
from openai import OpenAI

client = OpenAI()

SYSTEM = (
    "You triage support tickets for Acme. Reply with JSON only: "
    '{"category": "billing|bug|refund|other", "priority": "low|normal|high", "needs_human": true|false}'
)


def triage(ticket: str) -> str:
    response = client.chat.completions.create(
        model="gpt-5-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": ticket}],
    )
    return response.choices[0].message.content
