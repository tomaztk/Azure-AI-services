"""
demo_data.py
------------
Synthetic call-centre extraction records used by the built-in demo.
Each record has deliberate errors/edge-cases to showcase different validation layers.
"""

DEMO_RECORDS = [

    # ── Record 1: CLEAN PASS ─────────────────────────────────────────────────
    {
        "audio_file": "call_001_clean.wav",
        "summary": (
            "Customer called about an incorrect charge on their credit card statement. "
            "The agent verified the account, confirmed the duplicate transaction, and "
            "issued a full refund within 3-5 business days. Customer was satisfied."
        ),
        "product_L1": "Banking",
        "product_L2": "Credit Card",
        "product_L3": "Payment Dispute",
        "customer_sentiment": "Negative",
        "customer_sentiment_score": -0.65,
        "customer_sentiment_reasoning": "Customer expressed frustration about the incorrect charge.",
        "agent_sentiment": "Positive",
        "agent_sentiment_score": 0.70,
        "agent_sentiment_reasoning": "Agent was empathetic and professional throughout.",
        "tonality": "Professional",
        "tonality_descriptors": "empathetic, calm, efficient",
        "service": "Billing Dispute",
        "action_taken": "Agent verified duplicate transaction and initiated refund.",
        "resolution": "Resolved",
        # Attached transcript for groundedness evaluation (Layer 4)
        "_transcript": (
            "[AGENT] Thank you for calling support. How can I help you today?\n"
            "[CUSTOMER] Hi, I have a duplicate charge on my credit card statement.\n"
            "[AGENT] I can see the duplicate transaction. I'll issue a full refund now.\n"
            "[CUSTOMER] Thank you, that's great.\n"
            "[AGENT] The refund will appear in 3-5 business days."
        ),
    },

    # ── Record 2: LAYER 1/2 FAIL — sentiment-score contradiction ────────────
    {
        "audio_file": "call_002_sentiment_error.wav",
        "summary": (
            "Customer reported a broadband outage affecting their home office setup. "
            "Agent ran diagnostics and confirmed a local node failure. An engineer "
            "visit was scheduled for the following morning."
        ),
        "product_L1": "Telecom",
        "product_L2": "Broadband",
        "product_L3": "Outage Report",
        "customer_sentiment": "Positive",        # ← Error: score says negative
        "customer_sentiment_score": -0.80,       # ← Contradiction!
        "customer_sentiment_reasoning": "Customer was frustrated about the outage.",
        "agent_sentiment": "Neutral",
        "agent_sentiment_score": 0.10,
        "agent_sentiment_reasoning": "Agent was calm and factual.",
        "tonality": "Formal",
        "tonality_descriptors": "neutral, procedural",
        "service": "Technical Support",
        "action_taken": "Ran diagnostics and scheduled engineer visit.",
        "resolution": "Pending",
    },

    # ── Record 3: LAYER 3 FAIL — invalid taxonomy path ───────────────────────
    {
        "audio_file": "call_003_bad_taxonomy.wav",
        "summary": (
            "Customer inquired about adding a named driver to their motor insurance policy. "
            "The agent explained the process and premium implications. Customer agreed to "
            "proceed and the change was processed on the same call."
        ),
        "product_L1": "Insurance",
        "product_L2": "Motor",
        "product_L3": "Add Named Driver",       # ← Not in KB taxonomy
        "customer_sentiment": "Neutral",
        "customer_sentiment_score": 0.05,
        "customer_sentiment_reasoning": "Straightforward transactional call.",
        "agent_sentiment": "Positive",
        "agent_sentiment_score": 0.55,
        "agent_sentiment_reasoning": "Agent was helpful and clear.",
        "tonality": "Friendly",
        "tonality_descriptors": "warm, informative",
        "service": "Policy Change",
        "action_taken": "Added named driver and recalculated premium.",
        "resolution": "Resolved",
    },

    # ── Record 4: LAYER 5 FAIL — agent detects contradictions ───────────────
    {
        "audio_file": "call_004_contradiction.wav",
        "summary": (
            "Customer called to dispute a fraud charge on their account. The agent "
            "escalated the case to the fraud team for further investigation and issued "
            "a temporary block on the card."
        ),
        "product_L1": "Banking",
        "product_L2": "Credit Card",
        "product_L3": "Fraud Report",
        "customer_sentiment": "Negative",
        "customer_sentiment_score": -0.90,
        "customer_sentiment_reasoning": "Customer was very distressed about fraud.",
        "agent_sentiment": "Positive",
        "agent_sentiment_score": 0.60,
        "agent_sentiment_reasoning": "Agent was calm and reassuring.",
        "tonality": "Empathetic",
        "tonality_descriptors": "reassuring, professional",
        "service": "Fraud Report",
        "action_taken": "Escalated to fraud team and blocked the card.",
        "resolution": "Resolved",             # ← Contradiction: escalated = not resolved
    },

    # ── Record 5: LAYER 1/2 FAIL — missing required fields ──────────────────
    {
        "audio_file": "call_005_missing_fields.wav",
        "summary": "Customer called about an issue.",  # ← Too short (3 words after "Customer called about")
        "product_L1": "Utilities",
        "product_L2": "Electricity",
        "product_L3": "Billing",
        "customer_sentiment": "Unknown",       # ← Invalid label
        "customer_sentiment_score": 0.0,
        "customer_sentiment_reasoning": "",
        "agent_sentiment": "Neutral",
        "agent_sentiment_score": 0.0,
        "agent_sentiment_reasoning": "",
        "tonality": "Neutral",
        "tonality_descriptors": "",
        "service": "N/A",                      # ← Missing
        "action_taken": "",                    # ← Missing
        "resolution": "Unknown",               # ← Invalid label
    },

    # ── Record 6: WARN only — unknown service label ───────────────────────────
    {
        "audio_file": "call_006_unknown_service.wav",
        "summary": (
            "Customer called to ask about switching their gas tariff to a fixed-rate plan. "
            "The agent explained the available options and savings. The customer chose the "
            "12-month fixed plan and the switch was confirmed immediately."
        ),
        "product_L1": "Utilities",
        "product_L2": "Gas",
        "product_L3": "Tariff Change",
        "customer_sentiment": "Positive",
        "customer_sentiment_score": 0.75,
        "customer_sentiment_reasoning": "Customer was happy with the savings explained.",
        "agent_sentiment": "Positive",
        "agent_sentiment_score": 0.80,
        "agent_sentiment_reasoning": "Agent was enthusiastic and knowledgeable.",
        "tonality": "Friendly",
        "tonality_descriptors": "warm, helpful, clear",
        "service": "Tariff Switch",            # ← Not in KB (close: none)
        "action_taken": "Switched customer to 12-month fixed tariff.",
        "resolution": "Resolved",
    },
]
