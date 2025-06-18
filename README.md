# Resume QnA Agent on Agentspace

This project implements a Generative AI agent to address the following use case:
- Recruiters collect resumes and dump them in Google Drive folders.
- This Agent integrates with Google Drive and answers questions related to the resumes, such as:
  - Stack ranking of resumes by scoring against a job description.
  - Answering specific questions about resume content.

This project includes deployment scripts for deploying the agent to Vertex AI Agent Engine and making it available via Agentspace. Optionally, it can be tested using a local Streamlit app provided.

Tech Stack:
- Google Agent Development Kit (ADK), Python 
- Google Drive SDK
- Agent Engine
- AgentSpace
- Streamlit


## Features

- **Google Drive Integration**: Recursively scans a specified Google Drive folder for resumes.
- **Multi-Format Parsing**: Supports parsing text from PDF, DOCX, and TXT files.
- **LLM-Powered Analysis**: Utilizes a language model to score and rank resumes based on a provided job description.
- **Cloud Deployable**: Includes a robust script for deploying, updating, and managing the agent on Vertex AI.
- **Stateful Sessions**: Remembers the context of parsed resumes within a session for efficient follow-up questions.

## Getting Started

Follow these instructions to set up and run the project on your local machine for development and testing.

### Prerequisites

- Python 3.9+
- [Google Cloud SDK](https://cloud.google.com/sdk/install) installed and initialized.
- A Google Cloud Project with the Vertex AI API enabled.

### 1. Clone the Repository

```bash
git clone https://github.com/anchit-nishant/ResumeQnA.git
cd ResumeQnA
```

### 2. Set Up a Virtual Environment

It's highly recommended to use a virtual environment to manage project dependencies.

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

The project's dependencies are listed in `requirements.txt`.

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

This project requires Google Cloud credentials and configuration for deploying the agent, running the UI, and registering it with Agentspace.

First, create a `.env` file in the `resume_agent` directory. 

Now, open `resume_agent/.env` and fill in the values for your environment.

```env
# --- Google Cloud Project Details ---
# Your Google Cloud project ID.
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
# The location for your project (e.g., "us-central1").
GOOGLE_CLOUD_LOCATION="us-central1"
# A unique Google Cloud Storage bucket name for staging.
GOOGLE_CLOUD_STORAGE_BUCKET="your-gcp-staging-bucket"

# --- Agent & Model Configuration (Optional) ---
# The Vertex AI model to use for the agent. Defaults to gemini-2.0-flash-001.
MODEL_NAME="gemini-2.0-flash-001"
GOOGLE_GENAI_USE_VERTEXAI=TRUE


# --- Deployed Agent Details ---
# The NUMERICAL ID of your deployed agent (an "Agent Engine").
# You will get this after running 'python deploy.py --create' for the first time.
AGENT_ENGINE_ID="1234567890123456789"

# --- Agentspace Registration Details ---
# The simple string ID of your "Agent App" (an "Engine" in the Discovery Engine API).
AGENTSPACE_APP_ID="your-agentspace-app-id"
# The OAuth Client ID you created for your application.
OAUTH_CLIENT_ID="your-oauth-client-id.apps.googleusercontent.com"
# The OAuth Client Secret associated with the Client ID.
OAUTH_CLIENT_SECRET="your-oauth-client-secret"

# --- Agent Configuration (Optional) ---
# You can override the default agent configuration by setting these variables.
# AGENT_AUTH_ID="custom-auth-id"
# AGENT_DISPLAY_NAME="My Custom TalentRank Agent"
AGENT_DESCRIPTION="A custom agent for analyzing resumes."
AGENT_TOOL_DESCRIPTION="You are a specialized HR assistant for technical roles."
```

**Why the different ID formats?**

You'll notice `AGENT_ENGINE_ID` is a full path while `AGENTSPACE_APP_ID` is a simple string. This is not an error! It's because they are two different kinds of resources managed by two different Google Cloud APIs, and each API requires a specific format:

*   **Agent Engine:** Managed by the Vertex AI SDK, which uses the full resource path.
*   **Agentspace App:** Managed by the Discovery Engine REST API, which builds its request URL using the simple App ID.

The scripts handle this difference correctly. Just make sure to copy the IDs in the format specified below.

**Where to find these values:**

*   `AGENT_ENGINE_ID`: Run `python deploy.py --create`. The script will print the full resource name (e.g., `projects/.../reasoningEngines/12345...`). **Copy only the final numerical part** into your `.env` file.
*   `AGENTSPACE_APP_ID`: This is the **simple ID** for your "Agent App" container. In the Google Cloud Console, navigate to **Vertex AI -> Agents -> Agentspace**. Select your agent application. The ID is the last part of the URL in your browser (e.g., `.../engines/your-agentspace-app-id`). Copy only that final part.
*   `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET`: These come from the OAuth 2.0 Client ID you must create in the Google Cloud Console under **APIs & Services -> Credentials**. Ensure it is configured as a "Web application."

### 5. Authenticate with Google Cloud

Log in with your Google Cloud credentials. This command will open a browser window for you to authenticate.

```bash
gcloud auth application-default login
```

This makes your user credentials available to the application, which is necessary for the agent to interact with Google Cloud services like Vertex AI and Google Drive on your behalf.

## Local Development with ADK Web

The AI Development Kit (ADK) includes a web-based interface for interactively testing your agent locally. This is the best way to iterate on your tools and prompts.

To start the local web server, run:

```bash
adk web
```

This will use the `root_agent` defined in `resume_agent/agent.py` for local testing.

## Running the Streamlit UI

The `interact_ui.py` script provides a user-friendly chat interface to interact with your *deployed* agent. Before running it, make sure you have:

1.  Run `python deploy.py --create` at least once.
2.  Copied the resulting `AGENT_ENGINE_ID` into your `resume_agent/.env` file.

To run the UI:

```bash
streamlit run interact_ui.py
```

## Deploying to Vertex AI Agent Engine

The `deploy.py` script is your primary tool for managing the agent's lifecycle on Google Cloud.

### Initial Setup: Staging Bucket

The deployment process requires a Google Cloud Storage bucket for staging files. If you don't have one, create one using `gsutil`. A unique name is required.

```bash
# Replace [PROJECT_ID] and [LOCATION] with your actual GCP project ID and location.
gsutil mb -p [PROJECT_ID] -l [LOCATION] gs://[PROJECT_ID]-adk-staging-bucket
```

### Create a New Agent

To deploy your agent to Vertex AI for the first time, use the `--create` flag.

```bash
python deploy.py --create
```

The script will output the full resource name of the newly created agent (e.g., `projects/.../reasoningEngines/12345...`). **Copy only the final numerical part** of this name and save it as `AGENT_ENGINE_ID` in your `.env` file.

### Update an Existing Agent

If you've made changes to your agent's code (e.g., in `tools.py` or `agent.py`), update the deployed version using the `--update` flag. Make sure your `.env` file contains the correct `AGENT_ENGINE_ID`.

```bash
python deploy.py --update
```

### List Deployed Agents

To see all agents deployed in your project, use `--list`. The output will show the **Numerical ID** needed for `update` and `delete` operations if you aren't using the `.env` file.

```bash
python deploy.py --list
```

### Delete an Agent

To remove a deployed agent from Vertex AI, use the `--delete` flag. It will use the `AGENT_ENGINE_ID` from your `.env` file.

```bash
python deploy.py --delete
```

This action is irreversible.

## Registering with Agentspace

After deploying your agent, register it with Agentspace to make it discoverable. The `register_agent.py` script manages this process.

Ensure all `AGENTSPACE_*` and `OAUTH_*` variables are correctly set in your `resume_agent/.env` file before proceeding.

### Register a New Agent

You can register the agent to act on behalf of a user (requiring OAuth consent) or using its own service account.

**With User Identity (OAuth)**
This is the standard method, allowing the agent to access resources the end-user has access to.
```bash
python register_agent.py register
```

**With Service Account Identity**
Use this if the agent only needs to access resources explicitly shared with its service account.
```bash
python register_agent.py register --no-auth
```

### List Registered Agents

To see all agents registered in your Agentspace app and find their numeric IDs:

```bash
python register_agent.py list
```

### Get Agent Details

To retrieve the full JSON configuration of a specific registered agent, use the `get` command. The script will use the `AGENTSPACE_APP_ID` from your `.env` file to identify the correct agent application. It will then prompt you for the specific numeric ID of the agent you wish to inspect (which you can find with the `list` command).

```bash
python register_agent.py get
```

### Delete a Registered Agent

To remove an agent from Agentspace, use the `delete` command. It will use the `AGENTSPACE_APP_ID` from your `.env` file to identify the correct agent application.

```bash
python register_agent.py delete
```
The script will prompt you for the numeric ID of the agent to delete (which you can find with the `list` command).

## Interacting with the Deployed Agent

Once your agent is deployed, you can interact with it through the Vertex AI console or via the API. You can find your agent in the Google Cloud Console under **Vertex AI -> Agents**. From there, you can test it in the console, integrate it with other services, or get the necessary details to call it programmatically.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details. 