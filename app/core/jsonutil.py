import json, re

def parse_json(text: str):
    text=text.strip()
    if text.startswith("```"):
        text=re.sub(r"^```(?:json)?\s*","",text)
        text=re.sub(r"\s*```$","",text)
    m=re.search(r"\{.*\}", text, re.S)
    if m:
        text=m.group(0)
    return json.loads(text)
