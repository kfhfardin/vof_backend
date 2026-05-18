# Lien — Demo Script (recordable)

**Target runtime:** 5:30 — 6:00
**Recording approach:** narrate over screen recording. Use the time tags in `(t=)` as your timing references.
**Voices needed:** Narrator, Sue (AI agent), Fardin Hoque (caller), Margarita (managing partner — one line).
**Screens, in order:** Dashboard (`/`) → Live intake (`/inbox/ix_001`) → Mobile approval (`/approve/ix_001`) → back to Live intake → Case detail (`/cases/ca_2401`) → Dashboard.

---

## COLD OPEN — *the problem* (t=0:00 → 0:25)

**Visual:** Black screen. Then: dashboard at `/` fades in. Three "Currently on call" cards visible.

**NARRATOR:**
> Fifty thousand personal injury law firms in the United States run on one phone call. Someone gets hurt, sees a billboard, dials a number — and a paralegal making eighteen dollars an hour decides whether a case worth half a million in fees walks out the door.
>
> The lawyer is in court. The lawyer is *always* in court.
>
> So most of the time, the case walks.

*(Beat. Three seconds.)*

**NARRATOR:**
> This is Lien.

---

## ACT 1 — *the dashboard* (t=0:25 → 0:55)

**Visual:** Cursor moves across the three live cards on the dashboard. Hover briefly on each — Fardin Hoque, Carlos Mendoza, Priya Sharma.

**NARRATOR:**
> Right now, three people are on the phone with Reyes & Associates. One was rear-ended on the 101. One was lane-splitting on the 580 and got hit by an SUV. One was a passenger in an Uber that ran a red light.
>
> Margarita Reyes is the managing partner. She's in a deposition. She's not on any of these calls.
>
> She doesn't have to be.

*(Cursor settles on the Fardin Hoque card.)*

**NARRATOR:**
> Let's listen to one.

**Visual:** Click "Review →" on Fardin's card. Transition to `/inbox/ix_001`.

---

## ACT 2 — *the live call opens* (t=0:55 → 1:50)

**Visual:** Live intake page loads. Three-pane layout. Center transcript fills naturally — let the audience see the dialogue.

**NARRATOR (over a brief silent shot):**
> Fardin Hoque is on the phone with Sue, our AI intake agent. The call is live. Every word is transcribed in real time through AgentPhone.

*(Cursor highlights the transcript area. Play the first few lines as audio.)*

**SUE (00:02):**
> "Thanks for calling Reyes & Associates, this is Fardin. I'm so sorry to hear you've been in an accident — let's get you taken care of. Can you walk me through what happened?"

**FARDIN (00:14):**
> "Hi Fardin — yeah, I was rear-ended on the 101 last Tuesday. The guy hit me really hard, he admitted right there it was his fault, said he was looking at his phone."

**SUE (00:31):**
> "I'm so glad you're okay enough to be on the phone with me. Did you go to the ER, or see a doctor afterward?"

**FARDIN (00:38):**
> "I went to SF General that same night. They did x-rays and an MRI. My neck and lower back have been killing me ever since — I can barely sit at my desk."

**Visual:** Cursor moves to the left rail. The required-info checklist updates. "Mechanism," "Medical treatment," "Carrier" tick captured. The "Talked to adjuster?" item shows the dashed "CAPTURING" tag.

**NARRATOR:**
> Watch the left side. Every required piece of information for this case — mechanism, medical, carrier, police report — is being captured as Fardin speaks. The system already knows what Fardin needs to ask, and what's still missing.

---

## ACT 3 — *the flag* (t=1:50 → 2:20)

**Visual:** Transcript continues. Skip ahead to the prior-injury exchange.

**SUE (02:14):**
> "Good — that helps. Before this, had you had any prior back or neck injuries?"

**FARDIN (02:22):**
> "Not really — I tweaked my back lifting boxes a couple years ago but it was a one-week thing."

**Visual:** Cursor moves to the right rail. The "Flags" panel is highlighted. The "Prior-injury disclosure" flag pulses red.

**NARRATOR:**
> She just disclosed a prior injury. To a State Farm adjuster, that's the difference between a fifty-thousand-dollar case and a five-thousand-dollar case. A junior human paralegal would miss this nine times out of ten.
>
> The copilot doesn't.

*(Hover over the flag card. Let the warning read.)*

**NARRATOR:**
> Pulled from the firm's own history through Supermemory and Moss, the system knows exactly how State Farm twists prior strains into pre-existing conditions. It tells Sue to probe the scope right now, in her own words, before the adjuster ever gets the chance.

---

## ACT 4 — *the recommendation* (t=2:20 → 2:55)

**Visual:** Cursor scrolls the right rail to the top. "Recommend accept" panel visible with the green Accept button.

**NARRATOR:**
> Two minutes into the call, the copilot has already done its math. It pulled four firm precedents that match Fardin's case — same mechanism, same carrier, same injury profile. Average settlement: forty-eight thousand four hundred dollars.

*(Hover over the "Firm comps" list. Let the audience read the amounts.)*

**NARRATOR:**
> No disqualifying flags. Caller hasn't spoken to the State Farm adjuster yet.
>
> Recommend: accept this case.

*(Cursor clicks "Escalate to Margarita ↗". New tab opens to `/approve/ix_001`.)*

---

## ACT 5 — *Margarita on her phone* (t=2:55 → 3:20)

**Visual:** Mobile approval card visible. The phone-shaped layout: header, facts, why-recommend block, three action buttons.

**NARRATOR:**
> Margarita's still in her deposition. Her phone just buzzed.
>
> Through AgentPhone, an iMessage with one tap to accept. Through AgentMail, the retainer agreement is queued and ready to send.

*(Pause on the page. Let the audience read the facts and the recommendation.)*

**NARRATOR:**
> She has the case. She has the value range. She has the comps. She has the reasoning. She has one decision to make. And she has it without leaving the room.

**MARGARITA (single line, brief):**
> "Accept."

*(Cursor taps the black "Accept" button. Subtle haptic-style feedback.)*

---

## ACT 6 — *the rest of the call* (t=3:20 → 4:50)

**Visual:** Switch back to the live intake page (`/inbox/ix_001`). Transcript has advanced. New lines from Fardin and Fardin are visible.

**NARRATOR:**
> Five seconds later, Sue gets the approval signal mid-call. She doesn't break stride. She keeps going — collecting the last pieces of information the case needs.

**SUE (03:21):**
> "Let me get a few more things from you. The imaging at SF General — do you remember what they scanned?"

**FARDIN (03:31):**
> "Cervical spine and lumbar — neck and lower back. Both showed disc issues, I think."

**SUE (03:42):**
> "Got it. And any treatment since the ER visit? PT, follow-ups, injections?"

**FARDIN (03:51):**
> "I started physical therapy this week — three times a week for now. My PCP wants to see if injections are needed."

**SUE (04:05):**
> "That documentation is going to help us. Last thing — have you missed work since the accident?"

**FARDIN (04:14):**
> "Yes. I'm a product designer, I work from home but I've cut my hours roughly in half. I can't sit at a screen for more than thirty minutes."

**SUE (04:32):**
> "Understood. We'll document the wage loss."

*(Beat. The acceptance moment lands.)*

**SUE (04:48):**
> "Fardin, I just got the approval from our managing partner Margarita — we're going to take your case."

**FARDIN (04:58):**
> "Oh thank God. I've been so stressed — I had no idea how I was going to deal with all of this."

**Visual:** Subtle indicator appears in the transcript area — "AgentMail · sending engagement letter" badge briefly visible.

**SUE (05:08):**
> "You don't have to. I'm sending you two things right now: our engagement letter, and a medical-records authorization. Both should hit your inbox in the next minute. Sign them whenever you have a moment today."

**FARDIN (05:24):**
> "Got it. And the statute of limitations — should I be worried?"

**SUE (05:31):**
> "Good question. California gives us two years from the date of the accident, so we have plenty of time. But the sooner we lock everything in, the stronger the case looks."

**FARDIN (05:46):**
> "Okay. Thank you so much, Fardin."

**SUE (05:52):**
> "Of course. You'll hear from me again in the next couple days. In the meantime, please focus on your recovery — and don't talk to anyone from State Farm. Take care, Fardin."

**FARDIN (06:02):**
> "Thanks, you too. Bye."

*(Click sound. Call ends. Transcript shows "Call ended · transcript above is the full conversation." at the bottom.)*

---

## ACT 7 — *the cascade* (t=4:50 → 5:15)

**Visual:** Switch to the case detail page (`/cases/ca_2401`). Timeline visible with retainer signed, HIPAA executed, records request sent, etc.

**NARRATOR:**
> AgentMail just sent the retainer and the HIPAA authorization. Browser Use opened the firm's case management system and created the matter — pre-populated with everything from the call. Supermemory wrote Fardin's case into the firm's brain — every fact, with provenance, ready for the next time someone on the team touches it.
>
> Total elapsed time from the first ring to a signed client and a queued records request: six minutes and two seconds.

---

## CLOSE — *the why* (t=5:15 → 5:45)

**Visual:** Cut back to the dashboard. Carlos and Priya are still on the phone. Fardin's card is gone (or moved to "Awaiting your approval" → resolved).

**NARRATOR:**
> Fifty thousand law firms. Ten paralegals each. One managing partner who's always in court.
>
> Every intake call is a coin flip on a case worth fifty thousand, two hundred thousand, sometimes more. We don't replace the paralegal. We don't replace the lawyer.
>
> We make sure that the moment they're not in the room — the moment that decides whether a firm grows or shrinks — happens correctly anyway.

*(Pause. Hold on the dashboard.)*

**NARRATOR:**
> Lien. The intake supervisor that doesn't sleep.

*(Fade out.)*

---

## Production notes

- **Voice direction for Fardin Hoque (caller):** late twenties or thirties, mildly in pain, anxious but composed. Not melodramatic. He's a product designer — articulate, used to talking, just rattled and uncomfortable. Use his name's correct pronunciation: *FAR-deen ho-QUE* (rhymes with "joke").
- **Voice direction for Sue (AI agent):** female-coded, warm, professional, deliberately paced. Mid-pitch. ElevenLabs-grade synthesis or a real voice actress. No marketing-voice energy — she sounds like a competent intake specialist, not a chatbot. Slight emotional warmth on the empathy lines.
- **Voice direction for Margarita:** sharp, low-volume, fast. Just one word. The point is that it's a one-word interaction — she's busy.
- **Voice direction for Narrator:** Don Draper energy. Mid-pace, declarative, never trying too hard.
- **Pacing tip:** the audience does not need to read every line of the transcript. Let the dialogue voiceover do the work; the on-screen transcript is the proof. Cut between transcript pane, left-rail capture progress, and right-rail flags during long stretches of dialogue so the visual stays interesting.

## Sponsor namedrops baked in

- **AgentPhone** — the call infrastructure (Act 2; Act 5 — iMessage; the recording flow itself)
- **Supermemory + Moss** — the firm's brain and the live retrieval (Act 3)
- **AgentMail** — the iMessage approval channel and the retainer/HIPAA send (Act 5, Act 6, Act 7)
- **Browser Use** — the case management auto-update (Act 7)

Four sponsors named at the moments they're load-bearing. Doesn't feel forced.

## ⚠ Whisper cue card (live interjection)

This is the moment where **you, the presenter, look like Margarita** — typing a real-time whisper into the right rail so the agent on the call adjusts mid-conversation. The transcript on screen is streaming live. You'll literally type into the whisper textarea while the call is going.

The agent does NOT go silent while you type — she keeps the conversation alive with two filler turns of natural empathy. Once you hit Send, her next turn pivots into the whisper content.

**Do NOT pre-fill this text into the UI.** Keep this cue card on a second monitor or printed.

### Timeline at a glance

| Time | Who | Line | Your action |
|---|---|---|---|
| 02:14 | Sue | "Before this, had you had any prior back or neck injuries?" | watching |
| **02:22** | **Fardin** | **"…I tweaked my back lifting boxes a couple years ago but it was a one-week thing."** | **▶ Flag lights red. Click into the whisper textarea NOW.** |
| 02:26 | Sue (filler) | "I appreciate you sharing that — being upfront protects you…" | typing… |
| 02:40 | Fardin (filler) | "Yeah, I figured better to just say it. I don't want surprises…" | finish typing & click Send (target: send by 02:45) |
| **02:50** | **Sue (whisper landed)** | **"Actually — one quick thing while I'm thinking about it. That back tweak — did it ever require imaging or PT? Or did you file any kind of claim…"** | **observe — your whisper just changed the call** |
| 03:04 | Fardin | "No, nothing like that. Just rested for a few days. Never saw a doctor." | observe |
| 03:18 | Sue | "Perfect. That's a clean prior. State Farm is going to ask, and now we have your answer on the record." | observe → narration cue |

**You have a 23-second window** (02:22 → 02:45) to type and send. The two filler turns cover you.

### The cue (when to start typing)

Watch the transcript center pane. When this line appears:

> **02:22 — Fardin:** *"Not really — I tweaked my back lifting boxes a couple years ago but it was a one-week thing."*

…and the right-rail Flag panel pulses red with **"Prior-injury disclosure"** — start typing immediately.

### What you type into the whisper textarea

Click into the "Or write your own" textarea on the right rail. Type this (or close — typos and abbreviations make it feel more real):

> **Lock down the prior — imaging? PT? Any claim ever filed? Need a clean record before State Farm asks.**

Aim to click **Send to Sue [agent]** by **02:45** — between Fardin's filler line ending at 02:47 and Sue's whisper-incorporating line at 02:50.

### What the audience sees during your 23-second window

Sue and Fardin will exchange two warm, natural lines while you type. The conversation does not stall. To the audience, it looks like Sue is just keeping the rapport going. Then Sue pivots ("Actually — one quick thing…") and the whisper is invisible — but its consequences are obvious.

### Narrator line to insert after the whisper-incorporated exchange completes (~03:25)

> The agent listened. To Margarita. To Supermemory. To the firm's own history. Fardin will never know there was an intervention — but the case just got bulletproofed.

### Backup interjection (if you miss the 02:22 cue)

If you can't get to the textarea in time, you have a second window at **04:53 → 05:02** (wage-loss exchange). Type:

> **Confirm she has documentation — pay stubs, timesheet, anything. Otherwise carrier discounts the wage-loss number.**

Sue's existing 05:20 line ("Understood. We'll document the wage loss.") is a clean follow-on, and you can add a narrator beat about "the partner just secured the wage-loss claim from a deposition." Less dramatic than the prior-injury cue but still tells the story.

---

## Screen-recording shot list

1. Dashboard `/` — full page, mouse moves across three live cards (10s)
2. Click into `/inbox/ix_001` — transition (1s)
3. Live intake page — open call (45s)
   - Transcript center pane, lines 00:02 → 00:38 (20s)
   - Left rail required-info checklist (10s)
   - Transcript continues — prior-injury line 02:14 → 02:22 (10s)
   - Right rail Flags panel (5s)
4. Right rail Recommend Accept panel (15s)
5. Click "Escalate to Margarita ↗" — new tab opens (1s)
6. Mobile approval page `/approve/ix_001` — held still (20s)
7. Tap "Accept" button — visual feedback (2s)
8. Back to `/inbox/ix_001` — transcript advances through 03:21 → 06:02 (75s)
   - Pan slowly. The dialogue voiceover carries the pacing.
9. Click into `/cases/ca_2401` — timeline visible (20s)
10. Back to dashboard `/` for close (10s)

**Total visual runtime:** ~5:30. Matches the audio script.
