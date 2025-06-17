import os
import json
import requests
import google.auth
from google.auth.transport.requests import Request
import argparse
from dotenv import load_dotenv

# ==============================================================================
#
#       HOW TO USE THIS SCRIPT
#
#       This script manages the lifecycle of your ADK Agent in Agentspace.
#
#       ** Step 1: Configure **
#       Fill in all the details in the "CONFIGURE YOUR AGENT DETAILS" section below.
#
#       ** Step 2: Run from your terminal **
#
#       --- To LIST all registered agents and find their IDs ---
#       $ python manage_agent.py list
#
#       --- To DELETE a registered agent ---
#       First, use 'list' to find the agent's numeric ID.
#       $ python manage_agent.py delete
#       (The script will then prompt you for the Agent ID)
#
#       --- To REGISTER the agent WITHOUT using user identity (OAuth) ---
#       **Pre-requisite**: Share your Google Drive files/folders with:
#       service-<projectNumber>@gcp-sa-discoveryengine.iam.gserviceaccount.com
#       $ python manage_agent.py register --no-auth
#
#       --- To REGISTER the agent WITH user identity (OAuth) ---
#       $ python manage_agent.py register
#
#       --- To GET the details of a specific registered agent ---
#       $ python manage_agent.py get
#       (The script will then prompt you for the Agent ID)
#
# ==============================================================================


# ==============================================================================
#
#       1. CONFIGURE YOUR AGENT DETAILS HERE
#
# ==============================================================================

# Load environment variables from the .env file in the resume_agent directory
dotenv_path = os.path.join(os.path.dirname(__file__), 'resume_agent', '.env')
load_dotenv(dotenv_path=dotenv_path)

# -- Project and Agent Details --
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION")
REASONING_ENGINE_ID = os.getenv("REASONING_ENGINE_ID") # The NUMERIC ID from `python deploy.py --create`
AGENTSPACE_APP_ID = os.getenv("AGENTSPACE_APP_ID") # The ID of your Agent App in Agentspace

# -- OAuth Credentials (only used if registering with OAuth) --
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")

# -- Agent Configuration --
AGENT_AUTH_ID = os.getenv("AGENT_AUTH_ID", "talentrank-gdrive-auth") # Default value if not set
AGENT_DISPLAY_NAME = os.getenv("AGENT_DISPLAY_NAME", "TalentRank Agent")
AGENT_DESCRIPTION = os.getenv("AGENT_DESCRIPTION", "Analyzes resumes against job descriptions from a central repository.")
AGENT_TOOL_DESCRIPTION = os.getenv("AGENT_TOOL_DESCRIPTION", "You are an expert HR assistant. Your task is to analyze resumes and job descriptions from the shared corporate Google Drive folder and answer questions about them.")

# --- Validate required variables ---
REQUIRED_VARS = [
    "PROJECT_ID", "LOCATION", "REASONING_ENGINE_ID", "AGENTSPACE_APP_ID",
    "OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET"
]
missing_vars = [var for var in REQUIRED_VARS if not globals()[var]]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}. Please define them in resume_agent/.env")


# ==============================================================================
#
#       2. SCRIPT LOGIC (No changes needed below)
#
# ==============================================================================

API_BASE_URL = "https://discoveryengine.googleapis.com/v1alpha"

def get_gcp_token():
    """Gets a fresh GCP access token."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not credentials.valid:
        credentials.refresh(Request())
    return credentials.token

def manage_agent(headers, action, use_oauth):
    """Performs register, delete, get, or list actions on the agent."""
    print(f"\n--- ACTION: {action.capitalize()} Agent(s) ---")
    
    # **FIXED HERE:** The base path for the API resource, not a full URL yet.
    base_agent_path = (
        f"projects/{PROJECT_ID}/locations/global/collections/default_collection/"
        f"engines/{AGENTSPACE_APP_ID}/assistants/default_assistant/agents"
    )
    
    # Determine the correct full URL based on the action
    if action in ["register", "list"]:
        agent_url = f"{API_BASE_URL}/{base_agent_path}"
    else: # For get/delete
        agent_id = input(f"Please enter the numeric Agent ID to {action} (e.g., 7869605575475419328): ")
        if not agent_id.isdigit():
            print("Invalid Agent ID format. It should be a number. Exiting.")
            return
        agent_url = f"{API_BASE_URL}/{base_agent_path}/{agent_id}"

    # --- Execute action ---
    if action == "list":
        response = requests.get(agent_url, headers=headers)
        if response.status_code == 200:
            agents = response.json().get('agents', [])
            if not agents:
                print("No agents found in this Agentspace app.")
                return
            print(f"Found {len(agents)} agent(s):")
            for agent in agents:
                full_name = agent.get('name', 'N/A')
                agent_id = full_name.split('/')[-1]
                print("-" * 20)
                print(f"  Display Name: {agent.get('displayName', 'N/A')}")
                print(f"  Agent ID:     {agent_id}")
                print(f"  Full Name:    {full_name}")
        else:
            print(f"ERROR: Failed to list agents (Status {response.status_code}):\n{response.text}")
        return

    if action == "delete":
        response = requests.delete(agent_url, headers=headers)
        if response.status_code == 200:
            print("SUCCESS: Agent deleted successfully.")
        else:
            print(f"ERROR: Failed to delete agent (Status {response.status_code}):\n{response.text}")
        return

    if action == "get":
        response = requests.get(agent_url, headers=headers)
        if response.status_code == 200:
            print("SUCCESS: Agent details retrieved.")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"ERROR: Failed to get agent (Status {response.status_code}):\n{response.text}")
        return
        
    if action == "register":
        # Build the full resource name for the payload
        full_reasoning_engine_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{REASONING_ENGINE_ID}"

        agent_payload = {
            "displayName": AGENT_DISPLAY_NAME, "description": AGENT_DESCRIPTION,
            "adk_agent_definition": {
                "tool_settings": {"tool_description": AGENT_TOOL_DESCRIPTION},
                "provisioned_reasoning_engine": {
                    "reasoning_engine": full_reasoning_engine_name
                },
            },
        }
        if use_oauth:
            print("Registering agent WITH OAuth.")
            agent_payload["authorizations"] = [f"{API_BASE_URL}/projects/{PROJECT_ID}/locations/global/authorizations/{AGENT_AUTH_ID}"]
        else:
            print("Registering agent WITHOUT OAuth (will use service account identity).")

        response = requests.post(agent_url, headers=headers, data=json.dumps(agent_payload))
        if response.status_code == 200:
            response_data = response.json()
            print("SUCCESS: Agent registered successfully!")
            print("IMPORTANT: The new Agent ID is at the end of the 'name' field below.")
            print(json.dumps(response_data, indent=2))
        else:
            print(f"ERROR: Failed to register agent (Status {response.status_code}):\n{response.text}")

def main():
    """Main function to orchestrate agent management."""
    parser = argparse.ArgumentParser(description="Manage Agentspace Agent Registration.",
        formatter_class=argparse.RawTextHelpFormatter)
    # **FIXED HERE:** Added 'list' to the available choices.
    parser.add_argument("action", choices=["register", "delete", "get", "list"], help="The action to perform.")
    parser.add_argument("--no-auth", dest="use_oauth", action="store_false",
        help="Flag to register the agent WITHOUT OAuth.\nAgent will use its own fixed service account identity.")
    parser.set_defaults(use_oauth=True)
    args = parser.parse_args()

    auth_token = get_gcp_token()
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID,
    }
        
    manage_agent(headers, action=args.action, use_oauth=args.use_oauth)
        
if __name__ == "__main__":
    main()