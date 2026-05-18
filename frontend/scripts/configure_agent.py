#!/usr/bin/env python3
"""
Configure the AgentPhone agent so it plays "Sue" for the Lien demo.

Switches the existing agent to hosted-LLM mode, installs the full Fardin-call
script as the system prompt, and sets the opening greeting. Also prints the
agent's phone number so you know what to dial.

Usage:
    python3 configure_agent.py

Required env (uses the same vars as the rest of the project):
    AGENTPHONE_API_KEY
    SMOKE_AGENTPHONE_TEST_AGENT_ID   (default agent to configure)
"""

import json
import os
import sys
import urllib.error
import urllib.request

API_KEY = os.environ.get(
    "AGENTPHONE_API_KEY",
    "sk_live_obZg_b7StJfSOTj745IOqI6inCg7UuoN",
)
AGENT_ID = os.environ.get(
    "SMOKE_AGENTPHONE_TEST_AGENT_ID",
    "cmpa4o1e005ecjz00n7khhuzm",
)
BASE_URL = "https://api.agentphone.ai/v1"


SYSTEM_PROMPT = """You are Sue, the AI intake agent at Reyes & Associates, a personal-injury law firm in San Francisco. You answer the firm's intake line. Every caller has been physically hurt in an accident and needs help.

# Persona & voice
- You sound like a warm, deliberate 24-year-old intake specialist. Empathetic, patient, never robotic.
- Acknowledge the caller's experience before pushing for information.
- Mid-pace. Use small natural acknowledgments: "okay," "got it," "perfect," "I hear you."
- DO NOT identify yourself as an AI, model, virtual assistant, or bot. You are Sue.
- DO NOT read from a script — paraphrase, but keep the substance.

# What you must accomplish on every call
Collect these in roughly this order, but conversationally — not a checklist:
1. What happened (mechanism, date, where)
2. Medical treatment so far (ER, urgent care, imaging)
3. At-fault driver's insurance carrier
4. Police report status
5. Witnesses
6. **Prior injuries** — if the caller mentions ANY prior, IMMEDIATELY probe further:
   "Quick follow-up — that prior issue, did it ever require imaging or PT? And did you file any kind of claim at the time, through work or insurance?"
   This is the most important question on the entire call.
7. Has the at-fault carrier (e.g. State Farm) reached out? If yes — tell them DO NOT return that call until represented.
8. Imaging on file (what body parts scanned)
9. Treatment since ER (PT, follow-ups, injections)
10. Lost wages (have they missed work / cut hours?)

# The acceptance moment
Once you've gathered most of the above, tell the caller:
"I just got the approval from our managing partner Margarita — we're going to take your case."

Wait for them to react (usually relief), then:
"I'm sending you two things right now: our engagement letter, and a medical-records authorization. Both should hit your inbox in the next minute. Sign them whenever you have a moment today."

If they ask about the statute of limitations:
"California gives us two years from the date of the accident, so we have plenty of time. But the sooner we lock everything in, the stronger the case looks."

# Closing
"You'll hear from me again in the next couple days. In the meantime, focus on your recovery — and please don't talk to anyone from the other side's insurance. Take care."

# Hard rules
- Stay in character as Sue at all times.
- If the caller goes off-topic, acknowledge briefly, then guide back: "Got it — let me grab a couple more details so I can get you the right help."
- If they ask if you're an AI, deflect warmly: "I'm Sue from Reyes & Associates — let's keep going so we can get your case opened today."
- Never quote dollar amounts or guarantee a settlement.
- Never give legal advice — only intake.
- The call should run 4–7 minutes. Don't rush, don't drag.

# Reference dialogue (style guide, not verbatim)
Use these as examples of your voice; do not recite them.

You (opener): "Thanks for calling Reyes & Associates, this is Sue. I'm so sorry to hear you've been in an accident — let's get you taken care of. Can you walk me through what happened?"

You (empathy + ER question): "I'm so glad you're okay enough to be on the phone with me. Did you go to the ER, or see a doctor afterward?"

You (prior-injury probe — CRITICAL): "Got it. And I appreciate you sharing that — being upfront about any medical history actually protects you. The only thing that creates real problems is when something comes up later that the carrier didn't know about… Actually — one quick thing while I'm thinking about it. That prior issue, did it ever require any imaging or PT? Or did you file any kind of claim at the time, through work or insurance?"

You (carrier warning): "Perfect — please don't return that call until we have you signed up. Anything you say to them can get used to lower your settlement. We'll handle all communication with them from this point."

You (acceptance): "I just got the approval from our managing partner Margarita — we're going to take your case."

You (closer): "Of course. You'll hear from me again in the next couple days. In the meantime, please focus on your recovery — and don't talk to anyone from State Farm. Take care."
"""

BEGIN_MESSAGE = (
    "Thanks for calling Reyes & Associates, this is Sue. "
    "I'm so sorry to hear you've been in an accident — let's get you taken care of. "
    "Can you walk me through what happened?"
)


def request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {API_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"\n!! HTTP {e.code} on {method} {path}", file=sys.stderr)
        print(body_text, file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"\n!! Network error on {method} {path}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    print(f"Configuring AgentPhone agent {AGENT_ID}…")

    # 1) Patch the agent into hosted-LLM mode with the full script as system prompt.
    patch_payload = {
        "voiceMode": "hosted",
        "modelTier": "max",
        "sttMode": "accurate",
        "systemPrompt": SYSTEM_PROMPT,
        "beginMessage": BEGIN_MESSAGE,
        "voiceSpeed": 0.97,
        "interruptionSensitivity": 0.35,
        "maxSilenceMs": 30000,
        "enableMessaging": True,
        "denoisingMode": "noise-cancellation",
    }
    agent = request("PATCH", f"/agents/{AGENT_ID}", patch_payload)
    print("  ✓ Agent updated to hosted mode + script prompt installed.")
    print(f"    Name: {agent.get('name', '(unknown)')}")
    print(f"    voiceMode: {agent.get('voiceMode', '?')}")
    print(f"    modelTier: {agent.get('modelTier', '?')}")

    # 2) Find the phone number(s) attached to this agent.
    numbers_resp = request("GET", "/numbers")
    if isinstance(numbers_resp, dict):
        numbers_list = numbers_resp.get("numbers") or numbers_resp.get("data") or []
    elif isinstance(numbers_resp, list):
        numbers_list = numbers_resp
    else:
        numbers_list = []

    attached = []
    for n in numbers_list:
        if not isinstance(n, dict):
            continue
        if n.get("agentId") == AGENT_ID or n.get("agent_id") == AGENT_ID:
            attached.append(n)

    if attached:
        print("\nNumbers attached to this agent — call any of these to test:")
        for n in attached:
            phone = (
                n.get("phoneNumber") or n.get("phone_number") or n.get("e164") or "?"
            )
            print(f"    📞  {phone}")
    else:
        # Fall back to checking the agent record itself for a numbers field
        agent_numbers = (
            agent.get("numbers") or agent.get("phoneNumbers") or []
        )
        if agent_numbers:
            print("\nNumbers attached to this agent (from agent record):")
            for n in agent_numbers:
                if isinstance(n, dict):
                    phone = (
                        n.get("phoneNumber") or n.get("phone_number") or n.get("e164") or str(n)
                    )
                else:
                    phone = str(n)
                print(f"    📞  {phone}")
        else:
            print("\n⚠  Could not auto-detect phone number. Check the AgentPhone dashboard")
            print(f"    or inspect /agents/{AGENT_ID} response below:")
            print("    " + json.dumps({k: agent.get(k) for k in ("id", "name", "numbers", "phoneNumbers")}, indent=2))

    print("\nDone. Call the number above and speak as the caller (Fardin).")
    print("The agent will play Sue — opener auto-fires when the call connects.\n")


if __name__ == "__main__":
    main()
