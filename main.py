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
JOBBER_ACCESS_TOKEN = os.getenv("JOBBER_ACCESS_TOKEN")
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


def split_name(full_name: str):
    if not full_name:
        return "Unknown", "Customer"

    parts = full_name.strip().split()

    if len(parts) == 1:
        return parts[0], "Customer"

    return parts[0], " ".join(parts[1:])


def create_jobber_client(caller_name):
    first_name, last_name = split_name(caller_name)

    query = """
    mutation CreateClient($input: ClientCreateInput!) {
      clientCreate(input: $input) {
        client {
          id
          firstName
          lastName
        }
      }
    }
    """

    variables = {
        "input": {
            "firstName": first_name,
            "lastName": last_name,
        }
    }

    response = requests.post(
        "https://api.getjobber.com/api/graphql",
        headers={
            "Authorization": f"Bearer {JOBBER_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "X-JOBBER-GRAPHQL-VERSION": "2025-01-20",
        },
        json={
            "query": query,
            "variables": variables,
        },
        timeout=30,
    )

    result = response.json()
    print("JOBBER CLIENT CREATE RESPONSE:", result)
    return result


@app.get("/jobber/test-client")
async def jobber_test_client():
    try:
        result = create_jobber_client("Test Customer")

        return {
            "success": True,
            "jobber_response": result,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@app.post("/vapi")
async def vapi_webhook(request: Request):
    data = await request.json()

    intent = data.get("intent", "unknown")
    summary = data.get("summary", "")
    caller_number = data.get("caller_number")
    caller_name = data.get("caller_name", "Unknown Customer")
    service_address = data.get("service_address", "")

    if not caller_number:
        return {
            "success": False,
            "error": "Missing caller_number",
            "received": data,
        }

    sms_body = """Thank you for contacting Northcrest HVAC.

We received your service request.

Our team will review your request and follow up shortly."""

    try:
        sms_sid = None
        jobber_result = None

        if intent in ["service_request", "estimate", "maintenance", "emergency"]:
            jobber_result = create_jobber_client(caller_name)

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

Customer Name:
{caller_name}

Caller Number:
{caller_number}

Service Address:
{service_address}

Summary:
{summary}

Jobber Result:
{jobber_result}
"""

        resend.Emails.send({
            "from": "Northcrest HVAC <onboarding@resend.dev>",
            "to": [OWNER_EMAIL],
            "subject": email_subject,
            "text": email_body,
        })

        return {
            "success": True,
            "intent": intent,
            "sms_sent": intent in ["service_request", "estimate", "maintenance", "emergency"],
            "sms_sid": sms_sid,
            "owner_notified": True,
            "jobber_result": jobber_result,
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "success": False,
            "error": str(e),
        }
