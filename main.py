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

JOBBER_API_VERSION = "2026-05-12"

resend.api_key = RESEND_API_KEY


@app.get("/")
def health_check():
    return {"status": "ok"}


def jobber_graphql(query, variables=None):
    response = requests.post(
        "https://api.getjobber.com/api/graphql",
        headers={
            "Authorization": f"Bearer {JOBBER_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "X-JOBBER-GRAPHQL-VERSION": JOBBER_API_VERSION,
        },
        json={
            "query": query,
            "variables": variables or {},
        },
        timeout=30,
    )

    result = response.json()
    print("JOBBER GRAPHQL RESPONSE:", result)
    return result


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


def create_jobber_client(caller_name: str):
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

    return jobber_graphql(query, variables)


def get_client_id(jobber_result):
    try:
        return jobber_result["data"]["clientCreate"]["client"]["id"]
    except Exception:
        return None


def create_jobber_property(client_id, service_address):
    if not client_id or not service_address:
        return None

    query = """
    mutation CreateProperty($clientId: EncodedId!, $input: PropertyCreateInput!) {
      propertyCreate(clientId: $clientId, input: $input) {
        property {
          id
        }
      }
    }
    """

    variables = {
        "clientId": client_id,
        "input": {
            "address": {
                "street1": service_address,
            }
        },
    }

    return jobber_graphql(query, variables)


def get_property_id(property_result):
    try:
        return property_result["data"]["propertyCreate"]["property"]["id"]
    except Exception:
        return None


def create_jobber_request(client_id, property_id, caller_number, service_address, summary):
    if not client_id:
        return None

    details = f"""
Phone:
{caller_number}

Service Address:
{service_address}

Issue:
{summary}
"""

    query = """
    mutation CreateRequest($input: RequestCreateInput!) {
      requestCreate(input: $input) {
        request {
          id
          title
        }
      }
    }
    """

    input_data = {
        "clientId": client_id,
        "title": "HVAC Service Request",
        "requestDetails": details,
    }

    if property_id:
        input_data["propertyId"] = property_id

    variables = {
        "input": input_data,
    }

    return jobber_graphql(query, variables)


def create_jobber_client_note(client_id, caller_number, service_address, summary):
    if not client_id:
        return None

    message = f"""
New HVAC service request from AI phone assistant.

Phone:
{caller_number}

Service Address:
{service_address}

Issue:
{summary}
"""

    query = """
    mutation CreateClientNote($clientId: EncodedId!, $input: ClientCreateNoteInput!) {
      clientCreateNote(clientId: $clientId, input: $input) {
        note {
          id
          message
        }
      }
    }
    """

    variables = {
        "clientId": client_id,
        "input": {
            "message": message,
        },
    }

    return jobber_graphql(query, variables)


def create_full_jobber_record(caller_name, caller_number, service_address, summary):
    client_result = create_jobber_client(caller_name)
    client_id = get_client_id(client_result)

    property_result = None
    property_id = None
    request_result = None
    note_result = None

    if client_id:
        try:
            property_result = create_jobber_property(client_id, service_address)
            property_id = get_property_id(property_result)
        except Exception as e:
            property_result = {"success": False, "error": str(e)}

        try:
            request_result = create_jobber_request(
                client_id=client_id,
                property_id=property_id,
                caller_number=caller_number,
                service_address=service_address,
                summary=summary,
            )
        except Exception as e:
            request_result = {"success": False, "error": str(e)}

        try:
            note_result = create_jobber_client_note(
                client_id=client_id,
                caller_number=caller_number,
                service_address=service_address,
                summary=summary,
            )
        except Exception as e:
            note_result = {"success": False, "error": str(e)}

    return {
        "client_id": client_id,
        "property_id": property_id,
        "client_result": client_result,
        "property_result": property_result,
        "request_result": request_result,
        "note_result": note_result,
    }


@app.get("/jobber/test-client")
async def jobber_test_client():
    try:
        result = create_full_jobber_record(
            caller_name="Test Customer",
            caller_number="+16025551234",
            service_address="123 Main Street, Phoenix, Arizona",
            summary="Test HVAC request",
        )

        return {
            "success": True,
            "jobber_response": result,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@app.get("/jobber/schema-test")
async def jobber_schema_test():
    query = """
    {
      clientNote: __type(name: "ClientCreateNoteInput") {
        inputFields {
          name
          type {
            name
            kind
            ofType {
              name
              kind
            }
          }
        }
      }

      property: __type(name: "PropertyCreateInput") {
        inputFields {
          name
          type {
            name
            kind
            ofType {
              name
              kind
            }
          }
        }
      }

      request: __type(name: "RequestCreateInput") {
        inputFields {
          name
          type {
            name
            kind
            ofType {
              name
              kind
            }
          }
        }
      }
    }
    """

    return jobber_graphql(query)


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
            jobber_result = create_full_jobber_record(
                caller_name=caller_name,
                caller_number=caller_number,
                service_address=service_address,
                summary=summary,
            )

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
"""

        resend.Emails.send(
            {
                "from": "Northcrest HVAC <onboarding@resend.dev>",
                "to": [OWNER_EMAIL],
                "subject": email_subject,
                "text": email_body,
            }
        )

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
