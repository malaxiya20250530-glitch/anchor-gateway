import json, os, urllib.request
from hallucination_detector import FactExtractor, AnchorEngine

KEY = os.environ["DEEPSEEK_API_KEY"]
URL = "https://api.deepseek.com/v1/chat/completions"

def ask(prompt, tokens=100):
    data = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": tokens, "temperature": 0.3, "stream": False,
    }).encode()
    req = urllib.request.Request(URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {KEY}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

extractor = FactExtractor()
engine = AnchorEngine(enable_web=False, enable_feedback=False, enable_graph=False)

tests = [
    "月球比地球大吗？",
    "月球直径是地球的多少？",
    "珠穆朗玛峰有多高？",
    "朱元璋发明了火锅吗？",
]

for p in tests:
    resp = ask(p)
    print(f"\nQ: {p}")
    print(f"A: {resp.strip()[:180]}")
    claims = extractor.extract(resp)
    print(f"  claims={len(claims)}")
    for c in claims:
        if c.is_verifiable:
            r = engine.verify(c)
            icon = {"verified":"OK","contradicted":"HALL","uncertain":"?","unverifiable":"-"}
            print(f"  [{icon.get(r.verdict,'?')}] {c.text[:90]}")
print("\nDone")
