# -*- coding: utf-8 -*-
"""E2E: upload a docx into run 9 (zhangsan project 5) + negative cases."""
import httpx

BASE = "http://127.0.0.1:8100"

token = httpx.post(f"{BASE}/auth/login", json={"username": "zhangsan"}).json()[
    "access_token"
]
H = {"Authorization": f"Bearer {token}"}

runs = httpx.get(f"{BASE}/projects/5/stage-runs", headers=H).json()
run9 = next((r for r in runs if r["id"] == 9), None)
print("run9:", run9["status"], run9["session_id"] is not None)

# 1) real docx
with open("upload-test.docx", "rb") as f:
    r = httpx.post(
        f"{BASE}/stage-runs/9/chat-upload",
        headers=H,
        files={"file": ("信贷需求书-测试.docx", f)},
        data={"text": "这是既有系统的需求书，请阅读后告诉我主要功能点。"},
    )
print("docx upload ->", r.status_code)
print(r.text.encode("unicode_escape").decode()[:300])

# 2) corrupt docx
r2 = httpx.post(
    f"{BASE}/stage-runs/9/chat-upload",
    headers=H,
    files={"file": ("broken.docx", b"not a real docx")},
)
print("corrupt ->", r2.status_code, r2.text.encode("unicode_escape").decode()[:200])

# 3) legacy .doc
r3 = httpx.post(
    f"{BASE}/stage-runs/9/chat-upload",
    headers=H,
    files={"file": ("legacy.doc", b"\xd0\xcf\x11\xe0fake")},
)
print("doc ->", r3.status_code, r3.text.encode("unicode_escape").decode()[:250])
