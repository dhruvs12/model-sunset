"""A fake OpenAI-compatible server, so capture and diff can be tried with no API key.

    python -m tests.stub          # serves http://127.0.0.1:8089/v1

It answers by the shape of the request, not by understanding it:
  tools given            -> a tool call to the first tool
  response_format given  -> a small JSON object
  otherwise              -> one line of text
The model name picks the behaviour:
  stub-drift   breaks all three (drops a JSON key, answers in text instead of calling the tool, worse text)
  stub-better  same structure, text the stub judge prefers
  stub-judge   a pairwise judge that dislikes any response containing "(drift)" and likes "(better)"
  anything else, including real model ids, is the baseline "old model"
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def judge(prompt: str) -> str:
    a, b = re.search(r"Response A:\n(.*)\n\nResponse B:\n(.*)\n\nReply with JSON", prompt, re.S).groups()
    score = lambda text: ("(better)" in text) - ("(drift)" in text)
    winner = "A" if score(a) > score(b) else "B" if score(b) > score(a) else "tie"
    return json.dumps({"winner": winner, "reason": "stub judge rule"})


def answer(body: dict) -> dict:
    model, messages = body["model"], body["messages"]
    user = messages[-1]["content"]
    if model == "stub-judge":
        return {"role": "assistant", "content": judge(user)}
    if body.get("tools") and model != "stub-drift":
        call = {"id": "call_1", "type": "function",
                "function": {"name": body["tools"][0]["function"]["name"], "arguments": json.dumps({"order_id": "A-1042"})}}
        return {"role": "assistant", "content": None, "tool_calls": [call]}
    if body.get("response_format"):
        data = {"category": "refund", "priority": "high", "needs_human": False}
        if model == "stub-drift":
            del data["priority"]
        return {"role": "assistant", "content": json.dumps(data)}
    tag = {"stub-drift": " (drift)", "stub-better": " (better)"}.get(model, "")
    return {"role": "assistant", "content": f"Stub summary{tag}: {user[:60]}"}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        payload = json.dumps({"choices": [{"index": 0, "message": answer(body)}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def serve(port: int = 8089) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    serve()
    print("Stub OpenAI-compatible endpoint on http://127.0.0.1:8089/v1 (Ctrl-C to stop)")
    threading.Event().wait()
