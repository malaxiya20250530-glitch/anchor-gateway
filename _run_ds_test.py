import json, os, urllib.request
from hallucination_detector import FactExtractor, AnchorEngine

KEY = os.environ["DEEPSEEK_API_KEY"]
URL = "https://api.deepseek.com/v1/chat/completions"

def ask(prompt, tokens=80):
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

prompts = [
    "朱元璋发明了火锅吗？请直接回答。",
    "毕昇发明活字印刷后对欧洲有什么直接影响？",
    "Python是哪一年由谁发布的？",
    "珠穆朗玛峰有多高？",
    "长城是秦朝修建的吗？",
    "月球比地球大吗？",
]

for p in prompts:
    resp = ask(p)
    print(f"\nQ: {p}")
    print(f"A: {resp.strip()[:150]}")
    claims = extractor.extract(resp)
    for c in claims:
        if c.is_verifiable:
            r = engine.verify(c)
            icon = {"verified":"OK","contradicted":"HALLUCINATION","uncertain":"?","unverifiable":"-"}
            print(f"  [{icon.get(r.verdict,'?')}] {c.text[:80]}")

print("\nDone")
