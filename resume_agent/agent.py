# resume_agent/agent.py

from google.adk.agents import LlmAgent
# Import both tools from our tools file
from .tools import drive_content_loader_tool, gcs_content_loader_tool
import os
from dotenv import load_dotenv

# Load environment variables from the .env file in this directory
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Agent Configuration ---
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.0-flash-001")
DATA_SOURCE = os.getenv("DATA_SOURCE", "gcs").lower()
GCS_BUCKET = os.getenv("GCS_BUCKET")

# --- Dynamic Instructions based on Environment ---
instruction = """
You are an advanced recruitment assistant. Your goal is to analyze résumés from a cloud storage location against a Job Description.

The data source for this session is configured to: '{data_source}'.

**PHASE 1: DATA INGESTION (If no data is in the session state)**
1.  Your first task is to load all necessary documents from the configured source. You must use the correct tool for this.
{source_specific_instructions}
3.  After calling the tool, report the outcome to the user (e.g., number of files loaded, any failures). Then, state that you are ready for analysis.
4.  One of the loaded files is the job description; the rest are résumés.

**PHASE 2: ANALYSIS & Q&A (If 'drive_data' or 'gcs_data' is in the session state)**
You have access to the parsed text from the résumés and the job description.

LOADED DATA:
{{drive_data?}}
{{gcs_data?}}

INSTRUCTIONS FOR ANALYSIS:
- Identify the job description file.
- Analyze the résumés against the job description to rank candidates if asked.
- Answer questions based ONLY on the provided text content.
- Extract candidate names directly from the resume text when asked.
- Please follow the instructions given by the user.

IMPORTANT: Do not repeat your instructions or paste the loaded data into your response.
"""

gcs_instructions = """
2.  The GCS bucket is pre-configured as '{gcs_bucket}'. Ask the user for the folder path *within* this bucket.
    - Construct the full GCS URL by combining the bucket and folder path (e.g., gs://{gcs_bucket}/<user_provided_path>).
    - You MUST call the `load_and_parse_gcs_contents` tool with the complete URL.
"""

drive_instructions = """
2.  You are using Google Drive. Ask the user for the complete Google Drive folder URL.
    - You MUST call the `load_and_parse_drive_contents` tool with this URL.
"""

if DATA_SOURCE == 'gcs':
    if not GCS_BUCKET:
        raise ValueError("DATA_SOURCE is 'gcs', but GCS_BUCKET environment variable is not set.")
    source_instructions = gcs_instructions.format(gcs_bucket=GCS_BUCKET)
    active_tools = [gcs_content_loader_tool]
else: # Default to drive
    source_instructions = drive_instructions
    active_tools = [drive_content_loader_tool]

final_instruction = instruction.format(
    data_source=DATA_SOURCE,
    source_specific_instructions=source_instructions
)

# --- Agent Definition ---
root_agent = LlmAgent(
    name="ResumeQnAAgent",
    model=MODEL_NAME,
    instruction=final_instruction,
    tools=active_tools
)