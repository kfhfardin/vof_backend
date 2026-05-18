export type IntakeStatus = "live" | "review" | "approved" | "declined";

export type Intake = {
  id: string;
  caller: string;
  callerPhone: string;
  source: string;
  startedAt: string;
  duration: string;
  status: IntakeStatus;
  paralegal: string;
  caseType: string;
  valueRange: string;
  carrier: string | null;
  statute: { date: string; label: string } | null;
  summary: string;
  recommendation?: { verdict: "Accept" | "Decline" | "Hold"; body: string };
  decision?: { takenBy: string; at: string; outcome: "Accepted" | "Declined" | "Needs more info" };
};

export const INTAKES: Intake[] = [
  {
    id: "ix_001",
    caller: "Fardin Hoque",
    callerPhone: "+1 (415) 555-0142",
    source: "Billboard · 101 / Cesar Chavez",
    startedAt: "09:24",
    duration: "00:05",
    status: "live",
    paralegal: "Sue [agent]",
    caseType: "Auto · rear-end",
    valueRange: "$40K – $60K",
    carrier: "State Farm",
    statute: { date: "2028-04-14", label: "1y 11mo" },
    summary: "Rear-ended on the 101 last Tuesday. ER visit at SF General. Back and neck pain ongoing. Other driver admitted fault at scene.",
    recommendation: {
      verdict: "Accept",
      body: "4 firm comps match this pattern at avg $48,400. No disqualifying flags. Caller hasn't talked to the State Farm adjuster — lock representation now.",
    },
  },
  {
    id: "ix_008",
    caller: "Carlos Mendoza",
    callerPhone: "+1 (510) 555-0319",
    source: "Google · motorcycle lawyer Oakland",
    startedAt: "09:21",
    duration: "06:48",
    status: "live",
    paralegal: "Maya Patel",
    caseType: "Motorcycle · lane-split",
    valueRange: "$70K – $130K",
    carrier: "GEICO",
    statute: { date: "2028-04-16", label: "1y 11mo" },
    summary: "Lane-split collision on 580 E. SUV merged without signaling. Open femur fracture. Two surgeries scheduled this month.",
    recommendation: {
      verdict: "Accept",
      body: "Strong fit. Open fracture + documented surgeries push comp range to $90–140K. GEICO settles pre-suit on these in ~9 months.",
    },
  },
  {
    id: "ix_009",
    caller: "Priya Sharma",
    callerPhone: "+1 (415) 555-0871",
    source: "Referral · Andrea Chen",
    startedAt: "09:28",
    duration: "01:34",
    status: "live",
    paralegal: "Sue [agent]",
    caseType: "Rideshare · Uber passenger",
    valueRange: "$30K – $55K",
    carrier: "Uber · James River",
    statute: { date: "2028-04-19", label: "1y 11mo" },
    summary: "Passenger in Uber when driver ran a red on Van Ness. Whiplash + concussion. Driver still on the platform.",
    recommendation: {
      verdict: "Accept",
      body: "Clean liability. Uber's James River carrier fast-tracks passenger claims. 3 firm comps with whiplash + concussion settled avg $42K in 4 months.",
    },
  },
  {
    id: "ix_002",
    caller: "James Wilson",
    callerPhone: "+1 (650) 555-0188",
    source: "Google · slip and fall lawyer SF",
    startedAt: "09:08",
    duration: "06:41",
    status: "review",
    paralegal: "Sue [agent]",
    caseType: "Premises · slip and fall",
    valueRange: "$8K – $15K",
    carrier: "Whole Foods (self-insured)",
    statute: { date: "2028-04-02", label: "1y 10mo" },
    summary: "Slipped on unmarked wet floor at Whole Foods on Market. Twisted ankle, urgent care visit. No surgical recommendation yet.",
  },
  {
    id: "ix_006",
    caller: "Aisha Patel",
    callerPhone: "+1 (415) 555-0710",
    source: "Billboard · Bayshore",
    startedAt: "08:51",
    duration: "05:18",
    status: "review",
    paralegal: "Maya Patel",
    caseType: "Auto · T-bone",
    valueRange: "$22K – $34K",
    carrier: "Allstate",
    statute: { date: "2028-04-08", label: "1y 10mo" },
    summary: "T-boned at 19th Ave / Sloat. Driver ran red. ER visit, neck/back pain, no surgery yet. Police report filed.",
  },
  {
    id: "ix_007",
    caller: "Tom García",
    callerPhone: "+1 (415) 555-0954",
    source: "Yelp",
    startedAt: "08:32",
    duration: "08:02",
    status: "review",
    paralegal: "Sue [agent]",
    caseType: "Bicycle · hit",
    valueRange: "$18K – $28K",
    carrier: "Farmers",
    statute: { date: "2028-04-05", label: "1y 10mo" },
    summary: "Cyclist hit at Folsom/9th by car turning right without signaling. Wrist fracture, surgery scheduled. Witness present.",
  },
  {
    id: "ix_003",
    caller: "Andrea Chen",
    callerPhone: "+1 (415) 555-0303",
    source: "Referral · Linda Brooks",
    startedAt: "Yesterday 16:42",
    duration: "11:08",
    status: "approved",
    paralegal: "Maya Patel",
    caseType: "Motorcycle · PCH",
    valueRange: "$120K – $220K",
    carrier: "GEICO",
    statute: { date: "2028-05-09", label: "1y 11mo" },
    summary: "Motorcycle hit at PCH intersection. Pre-existing condition complicating liability. Hospital 4 nights. Surgery scheduled.",
    decision: { takenBy: "M. Reyes", at: "Yesterday 16:51", outcome: "Accepted" },
  },
  {
    id: "ix_004",
    caller: "Robert Kim",
    callerPhone: "+1 (415) 555-0421",
    source: "Billboard · 280 / 19th Ave",
    startedAt: "Yesterday 14:11",
    duration: "07:32",
    status: "approved",
    paralegal: "Sue [agent]",
    caseType: "Pedestrian · hit-and-run",
    valueRange: "$60K – $110K",
    carrier: "UM/UIM coverage",
    statute: { date: "2028-05-08", label: "1y 11mo" },
    summary: "Hit in crosswalk at Sloat. Plate recovered. Uninsured motorist claim. Broken tibia, surgery completed.",
    decision: { takenBy: "M. Reyes", at: "Yesterday 14:24", outcome: "Accepted" },
  },
  {
    id: "ix_005",
    caller: "Linda Brooks",
    callerPhone: "+1 (415) 555-0612",
    source: "Yelp",
    startedAt: "Yesterday 11:02",
    duration: "03:54",
    status: "declined",
    paralegal: "Sue [agent]",
    caseType: "Dog bite",
    valueRange: "$3K – $6K",
    carrier: "State Farm (homeowners)",
    statute: { date: "2028-05-07", label: "1y 11mo" },
    summary: "Minor dog bite from neighbor's dog. Urgent care only, no significant treatment. Carrier already offered $2.5K.",
    decision: { takenBy: "M. Reyes", at: "Yesterday 11:18", outcome: "Declined" },
  },
];

export type TranscriptLine = {
  t: string;
  speaker: "Caller" | "Paralegal";
  text: string;
};

export const TRANSCRIPT: TranscriptLine[] = [
  { t: "00:02", speaker: "Paralegal", text: "Thanks for calling Reyes & Associates, this is Sue. I'm so sorry to hear you've been in an accident — let's get you taken care of. Can you walk me through what happened?" },
  { t: "00:14", speaker: "Caller", text: "Hi Sue — yeah, I was rear-ended on the 101 last Tuesday. The guy hit me really hard, he admitted right there it was his fault, said he was looking at his phone." },
  { t: "00:31", speaker: "Paralegal", text: "I'm so glad you're okay enough to be on the phone with me. Did you go to the ER, or see a doctor afterward?" },
  { t: "00:38", speaker: "Caller", text: "I went to SF General that same night. They did x-rays and an MRI. My neck and lower back have been killing me ever since — I can barely sit at my desk." },
  { t: "00:54", speaker: "Paralegal", text: "I hear you. Do you happen to know what insurance the other driver had?" },
  { t: "01:08", speaker: "Caller", text: "State Farm. I took a picture of his card at the scene." },
  { t: "01:21", speaker: "Paralegal", text: "Smart. And was a police report filed?" },
  { t: "01:28", speaker: "Caller", text: "Yes, CHP came out. I have the case number in an email." },
  { t: "01:42", speaker: "Paralegal", text: "Perfect. Were there any witnesses, or anyone else in the other car?" },
  { t: "01:55", speaker: "Caller", text: "His wife was in the passenger seat. And there were a couple of people in the next lane who stopped to make sure I was okay." },
  { t: "02:14", speaker: "Paralegal", text: "Good — that helps. Before this, had you had any prior back or neck injuries?" },
  { t: "02:22", speaker: "Caller", text: "Not really — I tweaked my back lifting boxes a couple years ago but it was a one-week thing." },
  // ⚠ MARGARITA WHISPER WINDOW OPENS HERE — see DEMO_SCRIPT.md → Whisper cue card.
  // Filler exchange below keeps the agent talking while Margarita types.
  { t: "02:26", speaker: "Paralegal", text: "Got it. And I appreciate you sharing that — being upfront about any medical history actually protects you. The only thing that creates real problems is when something comes up later that the carrier didn't know about." },
  { t: "02:40", speaker: "Caller", text: "Yeah, I figured better to just say it. I really don't want any surprises down the road." },
  // ⚠ WHISPER LANDS — by this point Margarita has sent it. Sue incorporates it on her next turn.
  { t: "02:50", speaker: "Paralegal", text: "Actually — one quick thing while I'm thinking about it. That back tweak from a couple years ago, did it ever require any imaging or PT? Or did you file any kind of claim at the time, through work or insurance?" },
  { t: "03:04", speaker: "Caller", text: "No, nothing like that. I just rested for a few days. I never even saw a doctor about it — it was sore muscle stuff." },
  { t: "03:18", speaker: "Paralegal", text: "Perfect. That's a clean prior — State Farm is going to ask, and now we have your answer on the record. Has anyone from State Farm reached out to you yet?" },
  { t: "03:32", speaker: "Caller", text: "An adjuster called yesterday and left a message. I haven't called back." },
  { t: "03:44", speaker: "Paralegal", text: "Perfect — please don't return that call until we have you signed up. Anything you say to them can get used to lower your settlement. We'll handle all communication with them from this point." },
  { t: "04:02", speaker: "Caller", text: "Okay. So… what happens now?" },
  { t: "04:09", speaker: "Paralegal", text: "Let me get a few more things from you. The imaging at SF General — do you remember what they scanned?" },
  { t: "04:19", speaker: "Caller", text: "Cervical spine and lumbar — neck and lower back. Both showed disc issues, I think." },
  { t: "04:30", speaker: "Paralegal", text: "Got it. And any treatment since the ER visit? PT, follow-ups, injections?" },
  { t: "04:39", speaker: "Caller", text: "I started physical therapy this week — three times a week for now. My PCP wants to see if injections are needed." },
  { t: "04:53", speaker: "Paralegal", text: "That documentation is going to help us. Last thing — have you missed work since the accident?" },
  { t: "05:02", speaker: "Caller", text: "Yes. I'm a product designer, I work from home but I've cut my hours roughly in half. I can't sit at a screen for more than thirty minutes." },
  { t: "05:20", speaker: "Paralegal", text: "Understood. We'll document the wage loss." },
  { t: "05:36", speaker: "Paralegal", text: "Fardin, I just got the approval from our managing partner Margarita — we're going to take your case." },
  { t: "05:46", speaker: "Caller", text: "Oh thank God. I've been so stressed — I had no idea how I was going to deal with all of this." },
  { t: "05:56", speaker: "Paralegal", text: "You don't have to. I'm sending you two things right now: our engagement letter, and a medical-records authorization. Both should hit your inbox in the next minute. Sign them whenever you have a moment today." },
  { t: "06:12", speaker: "Caller", text: "Got it. And the statute of limitations — should I be worried?" },
  { t: "06:19", speaker: "Paralegal", text: "Good question. California gives us two years from the date of the accident, so we have plenty of time. But the sooner we lock everything in, the stronger the case looks." },
  { t: "06:34", speaker: "Caller", text: "Okay. Thank you so much, Sue." },
  { t: "06:40", speaker: "Paralegal", text: "Of course. You'll hear from me again in the next couple days. In the meantime, please focus on your recovery — and don't talk to anyone from State Farm. Take care, Fardin." },
  { t: "06:50", speaker: "Caller", text: "Thanks, you too. Bye." },
];

export type Precedent = {
  id: string;
  client: string;
  facts: string;
  carrier: string;
  outcome: string;
  amount: string;
};

export const PRECEDENTS: Precedent[] = [
  { id: "p1", client: "T. Nguyen (2025)",  facts: "405 rear-end · ER visit · soft tissue", carrier: "State Farm", outcome: "Settled pre-suit (7 mo)", amount: "$52,000" },
  { id: "p2", client: "D. Alvarez (2025)", facts: "880 rear-end · ER + 4 PT visits",      carrier: "State Farm", outcome: "Settled pre-suit (5 mo)", amount: "$41,500" },
  { id: "p3", client: "S. Park (2024)",     facts: "405 rear-end · ER · MRI + injection", carrier: "State Farm", outcome: "Filed; settled (11 mo)",   amount: "$78,000" },
  { id: "p4", client: "K. Liu (2024)",      facts: "Bay Br. rear-end · no ER · PT",       carrier: "State Farm", outcome: "Settled pre-suit (3 mo)", amount: "$22,000" },
];

export type RequiredField = {
  key: string;
  label: string;
  status: "captured" | "capturing" | "partial" | "needed" | "flagged";
  detail?: string;
};

export const REQUIRED_INFO: RequiredField[] = [
  { key: "mechanism", label: "Mechanism of injury",  status: "captured", detail: "Rear-end · 405 N · last Tuesday" },
  { key: "treatment", label: "Medical treatment",    status: "captured", detail: "ER same night · SF General" },
  { key: "carrier",   label: "At-fault carrier",     status: "captured", detail: "State Farm · admitted fault" },
  { key: "report",    label: "Police report",        status: "captured", detail: "CHP · report # pending pull" },
  { key: "witnesses", label: "Witnesses",            status: "partial",  detail: "3 named · contact info missing for 2" },
  { key: "prior",     label: "Prior injuries",       status: "flagged",  detail: "Lifting strain '21 — probe scope before adjuster does" },
  { key: "adjuster",  label: "Talked to adjuster?",  status: "capturing", detail: "Sue is asking now" },
  { key: "imaging",   label: "Imaging on file",      status: "needed" },
  { key: "wages",     label: "Lost wages",           status: "needed" },
  { key: "hipaa",     label: "HIPAA authorization",  status: "needed",   detail: "Send before hang-up" },
];

export type CopilotSignal =
  | { kind: "precedent"; title: string; body: string; meta: string }
  | { kind: "flag"; title: string; body: string; severity: "info" | "warn" }
  | { kind: "ask"; title: string; body: string };

export const WHISPER_SUGGESTIONS: { id: string; reason: string; text: string }[] = [
  {
    id: "w1",
    reason: "Caller hasn't been asked about the adjuster contact",
    text: "Has the State Farm adjuster reached out to you yet? Please don't return that call until we represent you — anything you say can lower the settlement.",
  },
  {
    id: "w2",
    reason: "Prior-injury disclosure · scope risk",
    text: "Just to be sure — that back tweak from a couple years ago, did it require any imaging, PT, or follow-up at the time? We want a clean record before the carrier asks.",
  },
  {
    id: "w3",
    reason: "Wage-loss documentation not yet captured",
    text: "Quick one — have you missed any work since the accident, or had to cut hours? Even partial loss matters for the demand.",
  },
];

export const COPILOT_SIGNALS: CopilotSignal[] = [
  {
    kind: "precedent",
    title: "4 firm comps for this fact pattern",
    body: "405 rear-end · State Farm · ER + soft tissue. Avg $48,400 · 7 mo to settle pre-suit.",
    meta: "Moss · matched 4/4",
  },
  {
    kind: "flag",
    title: "Statute clock",
    body: "California PI 2-yr statute. Expires April 14, 2028. 1y 11mo remaining.",
    severity: "info",
  },
  {
    kind: "flag",
    title: "Prior-injury disclosure",
    body: "Caller mentioned a prior back tweak. Probe gently to scope; do not assume pre-existing.",
    severity: "warn",
  },
  {
    kind: "ask",
    title: "Ask next",
    body: "\"Has the State Farm adjuster contacted you yet? It's important you don't give a recorded statement before we represent you.\"",
  },
  {
    kind: "ask",
    title: "Ask before you hang up",
    body: "\"Can I email you our representation agreement and a HIPAA authorization right now?\"",
  },
];

export const CASES = [
  { id: "ca_2401", client: "Andrea Chen",   type: "Motorcycle",      stage: "Demand drafted",    carrier: "GEICO",     value: "$120K – $220K", statute: "2028-05-09", next: "Demand mailed Fri" },
  { id: "ca_2399", client: "Robert Kim",    type: "Pedestrian",      stage: "Records collection", carrier: "UM/UIM",    value: "$60K – $110K",  statute: "2028-05-08", next: "Awaiting CHP report" },
  { id: "ca_2398", client: "Tom García",    type: "Auto · rear-end", stage: "PT in progress",    carrier: "Allstate",  value: "$25K – $45K",   statute: "2028-04-30", next: "Tx complete ETA 3 wk" },
  { id: "ca_2390", client: "Sarah Lopez",   type: "Auto · T-bone",   stage: "In suit",           carrier: "Mercury",   value: "$80K – $140K",  statute: "2027-09-12", next: "Depo of defendant" },
  { id: "ca_2376", client: "David Hassan",  type: "Premises",        stage: "Settled",           carrier: "Liberty",   value: "$32,500",       statute: "—",          next: "Disbursement 5/22" },
];

export const CASE_TIMELINE = [
  { date: "May 15", what: "Intake call — Sue [agent]", ref: "ix_003" },
  { date: "May 15", what: "Case accepted — M. Reyes" },
  { date: "May 16", what: "Retainer signed by client" },
  { date: "May 17", what: "Medical records request sent — Stanford" },
  { date: "May 17", what: "HIPAA auth executed" },
  { date: "May 20", what: "GEICO claim opened — adjuster Janet S." },
  { date: "May 24", what: "Police report received · favorable" },
];
