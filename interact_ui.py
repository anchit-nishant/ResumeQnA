# interact_ui.py
import streamlit as st
import vertexai
from vertexai import agent_engines
import os
from dotenv import load_dotenv

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Resume QnA Agent", page_icon="🤖")
st.title("🤖 Resume QnA Agent")
st.caption("An AI agent that analyzes résumés from Google Drive against a Job Description.")

# --- AGENT CONFIGURATION ---
# Load environment variables from the .env file in the resume_agent directory
dotenv_path = os.path.join(os.path.dirname(__file__), 'resume_agent', '.env')
load_dotenv(dotenv_path=dotenv_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION")
AGENT_ENGINE_ID = os.getenv("AGENT_ENGINE_ID")

# --- VALIDATE CONFIGURATION ---
if not all([PROJECT_ID, LOCATION, AGENT_ENGINE_ID]):
    st.error("Missing critical configuration. Please ensure GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, and AGENT_ENGINE_ID are set in your .env file.")
    st.stop()

# Build the full resource name from the components
full_reasoning_engine_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{AGENT_ENGINE_ID}"
# --- END CONFIGURATION ---


# Function to initialize the Vertex AI SDK and connect to the agent
@st.cache_resource
def initialize_agent():
    """Initializes Vertex AI and gets a handle to the remote agent.
    Using @st.cache_resource ensures this expensive operation runs only once.
    """
    print("Initializing Vertex AI and connecting to the agent...")
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    agent = agent_engines.get(full_reasoning_engine_name)
    print("Agent connection established.")
    return agent

# Initialize the agent
try:
    remote_agent = initialize_agent()
except Exception as e:
    st.error(f"Failed to initialize the agent. Have you run `gcloud auth application-default login`? Error: {e}")
    st.stop()


# Initialize chat history in Streamlit's session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Hardcode a user ID for this demo app. In a real application,
# this would be dynamically assigned per logged-in user.
USER_ID = "streamlit-user-001"

# Initialize a new remote session if one doesn't exist
if "remote_session_id" not in st.session_state:
    with st.spinner("Creating new remote session..."):
        print("Creating new remote session...")
        # Add the required user_id parameter
        response = remote_agent.create_session(user_id=USER_ID)
        # CORRECTED: Access the session ID using the dictionary key 'id'
        st.session_state.remote_session_id = response["id"]
        # Add the first message from the agent to kick things off
        st.session_state.messages.append({"role": "assistant", "content": "Hello! I can help you analyze résumés. Please provide the Google Drive folder URL."})
        print(f"New session created: {st.session_state.remote_session_id} for user {USER_ID}")


# Display past chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Main Interaction Logic ---
if prompt := st.chat_input("Your message..."):
    # Add user message to UI
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call the remote agent and display its streamed response
    with st.chat_message("assistant"):
        response_stream = remote_agent.stream_query(
            user_id=USER_ID,
            session_id=st.session_state.remote_session_id,
            message=prompt,
        )

        response_placeholder = st.empty()
        full_response_text = ""
        
        # Loop through all events from the agent stream
        for event in response_stream:
            # The event stream contains different types of data. We only want to
            # display the text that is part of the final response to the user.
            # Based on the observed structure, this text is nested inside a
            # 'content' dictionary with a 'parts' list.
            if isinstance(event, dict) and (content := event.get("content")):
                if isinstance(content, dict) and (parts := content.get("parts")):
                    for part in parts:
                        if text_chunk := part.get("text"):
                            # Append the chunk to the full response and update the placeholder
                            full_response_text += text_chunk
                            response_placeholder.markdown(full_response_text + "▌")

        # Display the final, complete response
        response_placeholder.markdown(full_response_text)
        
        if full_response_text:
            st.session_state.messages.append({"role": "assistant", "content": full_response_text})