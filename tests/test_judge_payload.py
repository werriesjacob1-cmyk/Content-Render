"""Zero-network: reasoning judge models get a token budget they can answer in."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
import main

def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise AssertionError(label)

p = main._chat_payload("openai/gpt-oss-120b", "q", 20, 0)
check(p["max_tokens"] >= 600, "gpt-oss judge gets room to finish reasoning")
check(p.get("reasoning_effort") == "low", "gpt-oss judge uses low reasoning effort")
p = main._chat_payload("llama-3.1-8b-instant", "q", 20, 0)
check(p["max_tokens"] == 20 and "reasoning_effort" not in p, "ordinary models are untouched")
print("ALL PASS")
