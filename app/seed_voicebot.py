"""
Seed VoiceBot campaign + contacts using SQLAlchemy (Async).

Usage:
  export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname"
  python scripts/seed_voicebot.py

Fix:
- DB columns are TIMESTAMP WITHOUT TIME ZONE, so we must pass naive datetimes.
"""

import asyncio
from uuid import uuid4
from datetime import datetime

from sqlalchemy import select

from app.core.db import async_session_maker
from app.models.campaign import VoiceBotCampaign, CampaignContact
from app.services.analytics.sentiment_analysis import analyze_transcript


CONTACTS = [
    {
        "phone": "+919399319061",
        "name": "Rahul Sharma",
        "collected_data": {"city": "Pune", "loan_type": "Personal Loan"},
        "transcript": (
            "Agent: Good morning! Am I speaking with Mr. Sharma?\n"
            "Customer: Yes, this is Sharma.\n"
            "Agent: Sir, I'm calling from Roinet Finance regarding a pre-approved personal loan offer. "
            "Would you be interested in hearing the details?\n"
            "Customer: Actually, I am interested, but I'm in a meeting right now. "
            "Can you call me back tomorrow after 6 PM?\n"
            "Agent: Absolutely, sir. I'll arrange a callback tomorrow evening.\n"
            "Customer: Yes, please. Thank you."
        )
    },
    {
        "phone": "+919999999902",
        "name": "Neha Singh",
        "collected_data": {"city": "Delhi", "loan_type": "Business Loan"},
        "transcript": (
            "Agent: Hello, is this Neha Singh?\n"
            "Customer: Yes speaking.\n"
            "Agent: I'm calling regarding a Roinet Finance business loan. We have a great offer to expand your business.\n"
            "Customer: I'm not interested, please don't call me again.\n"
            "Agent: I understand, ma'am. We will remove your number. Have a good day."
        )
    },
    {
        "phone": "+919999999903",
        "name": "Amit Verma",
        "collected_data": {"city": "Mumbai", "loan_type": "Personal Loan"},
        "transcript": (
            "Agent: Hi Amit, this is Roinet Finance. We have a pre-approved loan for you.\n"
            "Customer: Awesome, I was actually looking for a loan. What's the interest rate?\n"
            "Agent: It's 10.5% per annum.\n"
            "Customer: That sounds good. Can we proceed with the application?\n"
            "Agent: Yes, I will send you a link to upload your documents."
        )
    },
    {
        "phone": "+919999999904",
        "name": "Suresh Kumar",
        "collected_data": {"city": "Bangalore", "loan_type": "Home Loan"},
        "transcript": (
            "Agent: Hello, is this Suresh?\n"
            "Customer: Yes.\n"
            "Agent: I am from Roinet Finance calling about our new home loan schemes.\n"
            "Customer: I already have a home loan from HDFC. Not looking for a new one right now.\n"
            "Agent: Oh, no problem. Have a nice day."
        )
    },
    {
        "phone": "+919999999905",
        "name": "Priya Das",
        "collected_data": {"city": "Kolkata", "loan_type": "Personal Loan"},
        "transcript": (
            "Agent: Good afternoon Priya, calling from Roinet Finance.\n"
            "Customer: I'm busy right now, call me later.\n"
            "Agent: Sure, when would be a good time?\n"
            "Customer: Tomorrow around 10 AM.\n"
            "Agent: Got it. Will call you back then."
        )
    },
    {
        "phone": "+919999999906",
        "name": "Vikram Patel",
        "collected_data": {"city": "Ahmedabad", "loan_type": "Business Loan"},
        "transcript": (
            "Agent: Hello Vikram sir, Roinet Finance here. Can we discuss a business loan?\n"
            "Customer: You guys are a scam! Stop calling me. It's terrible.\n"
            "Agent: I'm sorry to bother you sir. We will not call again."
        )
    },
    {
        "phone": "+919999999907",
        "name": "Pooja Reddy",
        "collected_data": {"city": "Hyderabad", "loan_type": "Personal Loan"},
        "transcript": (
            "Agent: Hi Pooja, this is Roinet Finance. We have a pre-approved loan offer.\n"
            "Customer: I want a person to call me, not a bot!\n"
            "Agent: I understand, ma'am. I will schedule a human agent to call you shortly.\n"
            "Customer: Thank you."
        )
    },
    {
        "phone": "+919999999908",
        "name": "Ravi Gupta",
        "collected_data": {"city": "Chennai", "loan_type": "Personal Loan"},
        "transcript": (
            "Agent: Hello Ravi, Roinet Finance calling.\n"
            "Customer: Wrong number.\n"
            "Agent: Sorry for the inconvenience."
        )
    },
    {
        "phone": "+919999999909",
        "name": "Anjali Sharma",
        "collected_data": {"city": "Jaipur", "loan_type": "Business Loan"},
        "transcript": (
            "Agent: Hi Anjali, we have a business loan offer for you from Roinet Finance.\n"
            "Customer: Tell me more about it.\n"
            "Agent: It's an unsecured loan up to 10 lakhs.\n"
            "Customer: Sure, I am interested, please send details."
        )
    },
    {
        "phone": "+919999999910",
        "name": "Rajesh Singh",
        "collected_data": {"city": "Lucknow", "loan_type": "Personal Loan"},
        "transcript": (
            "Agent: Hello Rajesh, a Roinet Finance rep here.\n"
            "Customer: I don't need a loan, thank you.\n"
            "Agent: Alright, have a good day."
        )
    }
]


def utcnow_naive() -> datetime:
    #  naive UTC datetime (no tzinfo) — matches TIMESTAMP WITHOUT TIME ZONE
    return datetime.utcnow()


def make_execution_id(i: int) -> str:
    return f"seed-exec-{i:03d}-{uuid4().hex[:8]}"


async def main():
    async with async_session_maker() as db:
        now = utcnow_naive()

        # 1) Create campaign FIRST (dynamic id via ORM default or fallback)
        camp = VoiceBotCampaign(
            # If your model doesn't default id, uncomment:
            # id=uuid4(),
            name=f"Seed Campaign - Bolna Webhook Test ({now.isoformat(timespec='seconds')})",
            description="Seeded campaign for testing Bolna webhook + post-call analytics.",
            status="RUNNING",
            started_at=now,  #  naive
            total_contacts=len(CONTACTS),
            script_config={
                "product": "personal_loan",
                "language": "hi-en",
                "qualification_min_score": 60,
            },
        )
        db.add(camp)
        await db.flush()

        campaign_id = camp.id
        if campaign_id is None:
            camp.id = uuid4()
            await db.flush()
            campaign_id = camp.id

        # 2) Insert contacts using campaign_id
        created = 0
        skipped = 0
        exec_map: dict[str, str] = {}

        for idx, c in enumerate(CONTACTS, start=1):
            phone = c["phone"].strip()

            existing = await db.scalar(
                select(CampaignContact).where(
                    CampaignContact.campaign_id == campaign_id,
                    CampaignContact.phone == phone,
                )
            )
            if existing:
                skipped += 1
                continue

            exec_id = make_execution_id(idx)
            exec_map[phone] = exec_id
            
            transcript = c.get("transcript", "")
            print(f"  [{idx}/10] Analyzing transcript for {phone}...")
            analysis_result = analyze_transcript(transcript)

            collected_data = c.get("collected_data") or {}
            collected_data["analysis"] = analysis_result.model_dump()
            collected_data["ui_flags"] = {"show_callback_button": analysis_result.callback_requested}

            contact = CampaignContact(
                # If your model doesn't default id, uncomment:
                # id=uuid4(),
                campaign_id=campaign_id,
                phone=phone,
                name=c.get("name"),
                status="CONTACTED",  # Update to contacted so they show up easily
                call_outcome="ANSWERED_CALL",
                callback_needed=analysis_result.callback_requested,
                call_attempts=1,
                collected_data=collected_data,
                transcript=transcript,
                bolna_execution_id=exec_id,
                created_at=now,   # naive
                updated_at=now,   # naive
            )
            db.add(contact)
            created += 1

        await db.commit()

        print("\n------ Seed complete")
        print("Campaign ID:", campaign_id)
        print(f"Contacts inserted: {created}, skipped: {skipped}")
        print("Execution IDs:")
        for phone, exec_id in exec_map.items():
            print(f" - {phone} -> {exec_id}")


if __name__ == "__main__":
    asyncio.run(main())
