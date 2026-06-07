import os
import requests

import resend
from fastapi import FastAPI, Request
from twilio.rest import Client

app = FastAPI()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "kiimigu4@gmail.com")

JOBBER_CLIENT_ID = os.getenv("JOBBER_CLIENT_ID")
JOBBER_CLIENT_SECRET = os.getenv("JOBBER_CLIENT_SECRET")
JOBBER_REDIRECT_URI = os.getenv(
    "JOBBER_REDIRECT_URI",
    "https://northcresthvac.onrender.com/jobber/callback",
)

resend.api_key = RESEND_API_KEY


@app.get("/")
def health_check():
    return {"status": "ok"}


@app.get("/jobber/callback")
async def jobber_callback(code: str = None):
    if not code:
        return {"success": False, "error": "Missing code"}

    try:
        response = requests.post(
            "https://api.getjobber.com/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": JOBBER_CLIENT_ID,
                "client_secret": JOBBER_CLIENT_SECRET,
                "redirect_uri": JOBBER_REDIRECT_URI,
            },
            timeout=30,
        )

        token_data = response.json()
        print("JOBBER TOKEN RESPONSE:", token_data)

        return {
            "success": True,
            "message": "Jobber OAuth token received",
            "token_data": token_data,
        }

    except Exception as e:
        print("JOBBER OAUTH ERROR:", str(e))
        return {"success": False, "error": str(e)}


@app.post("/vapi")
async def vapi_webhook(request: Request):
    data = await request.json()

    intent = data.get("intent", "unknown")
    summary = data.get("summary", "")
    caller_number = data.get("caller_number")

    if not caller_number:
        return {
            "success": False,
            "error": "Missing caller_number",
            "received": data,
        }

    sms_body = """Thank you for contacting Northcrest HVAC.

You can request service here:
https://clienthub.getjobber.com/client_hubs/xxxx/request_work

Our team will review your request and follow up shortly."""

    try:
        sms_sid = None

        if intent in ["service_request", "estimate", "maintenance", "emergency"]:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            sms = client.messages.create(
                body=sms_body,
                from_=TWILIO_PHONE_NUMBER,
                to=caller_number,
            )
            sms_sid = sms.sid

        email_subject = f"Northcrest HVAC Inquiry: {intent}"

        email_body = f"""
New HVAC customer request received.

Intent:
{intent}

Summary:
{summary}

Caller Number:
{caller_number}
"""

        print("Sending HVAC team email via Resend...")

        resend.Emails.send({
            "from": "Northcrest HVAC <onboarding@resend.dev>",
            "to": [OWNER_EMAIL],
            "subject": email_subject,
            "text": email_body,
        })

        print("HVAC team email sent successfully via Resend")

        return {
            "success": True,
            "intent": intent,
            "sms_sent": intent in ["service_request", "estimate", "maintenance", "emergency"],
            "sms_sid": sms_sid,
            "owner_notified": True,
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "success": False,
            "error": str(e),
        }
