# resume_agent/tools.py

import io
import fitz  # PyMuPDF
import docx # python-docx
import google.auth
import requests
import logging
import sys
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.adk.tools import FunctionTool, ToolContext
# Removed parallel processing to prevent segmentation faults
import time

# Configure logging to output to stdout to be captured by Cloud Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    force=True  # Ensure this config is applied even if another lib configured logging
)

SCOPES = ["https://www.googleapis.com/auth/drive"]

# --- Supporting Functions for the Tool ---

def _get_service_account_email_from_metadata():
    """Queries the GCE metadata server to get the default service account email."""
    logging.info("Querying metadata server for service account email...")
    try:
        url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
        headers = {"Metadata-Flavor": "Google"}
        # Use a short timeout to avoid long waits if the server isn't available (e.g., local testing)
        response = requests.get(url, headers=headers, timeout=3)
        response.raise_for_status()
        email = response.text
        logging.info(f"Successfully retrieved service account email from metadata server: {email}")
        return email
    except requests.exceptions.RequestException as e:
        logging.warning(f"Could not query metadata server. This is normal if running locally. Error: {e}")
        return None

def _authenticate_drive():
    """Authenticates using Application Default Credentials for production."""
    logging.info("Authenticating with Google Drive using Application Default Credentials...")

    # First, try to get the email from the metadata server, which is the most reliable way on GCP.
    service_account_email = _get_service_account_email_from_metadata()

    credentials, project = google.auth.default(scopes=SCOPES)

    # If metadata server failed, try to get it from the credentials object as a fallback.
    if not service_account_email:
        logging.warning("Metadata server query failed, attempting to get email from credentials object as a fallback...")
        service_account_email = getattr(credentials, 'service_account_email', 'N/A (could not determine from credentials)')

    logging.info(f"--> Service Account Email being used for Drive API calls: {service_account_email}")
    logging.info(f"Authentication resolved for project: {project}")
    return credentials

def _list_files_recursively(service, folder_id: str) -> list:
    """Recursively lists all files in a folder and its subfolders."""
    logging.info(f"--> Entering _list_files_recursively for folder_id: {folder_id}")
    all_files = []
    page_token = None
    page_count = 0
    while True:
        page_count += 1
        query = f"'{folder_id}' in parents and trashed=false"
        logging.info(f"    Executing Drive API files.list with query: \"{query}\", page: {page_count}")

        try:
            response = service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name, mimeType)'
            ).execute()
        except HttpError as error:
            logging.error(f"    Drive API error on files.list for folder '{folder_id}': {error}")
            # This can happen if the service account lacks permission for a subfolder.
            # Log the error and continue, treating the folder as empty.
            return [] # Return empty list for this branch of recursion

        files_in_page = response.get('files', [])
        logging.info(f"    API response for page {page_count} contained {len(files_in_page)} items.")

        for file in files_in_page:
            if file.get('mimeType') == 'application/vnd.google-apps.folder':
                # It's a subfolder, recurse into it
                logging.info(f"      Found subfolder: '{file.get('name')}' (ID: {file.get('id')}). Descending into it.")
                all_files.extend(_list_files_recursively(service, file.get('id')))
            else:
                # It's a file
                logging.info(f"      Found file: '{file.get('name')}' (ID: {file.get('id')})")
                all_files.append(file)
                
        page_token = response.get('nextPageToken', None)
        if page_token is None:
            logging.info(f"    No more pages for folder_id: {folder_id}. Finishing recursion level.")
            break
        else:
            logging.info(f"    Found nextPageToken. Continuing to next page for folder_id: {folder_id}.")
    
    logging.info(f"<-- Exiting _list_files_recursively. Found {len(all_files)} total files/sub-items in this folder branch.")
    return all_files

def _parse_content(filename: str, content: bytes) -> str:
    """Parses content based on file extension."""
    logging.info(f"  Parsing content for: {filename}")
    if filename.lower().endswith('.pdf'):
        logging.info("    Using PDF parser (PyMuPDF)...")
        with fitz.open(stream=content, filetype="pdf") as doc:
            return "".join(page.get_text() for page in doc)
    elif filename.lower().endswith('.docx'):
        logging.info("    Using DOCX parser (python-docx)...")
        doc = docx.Document(io.BytesIO(content))
        return "\n".join([para.text for para in doc.paragraphs])
    else:
        # Fallback for plain text or unsupported types
        logging.info("    Using fallback text parser (UTF-8 decode)...")
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            logging.warning("    Fallback parser failed. File is not valid UTF-8 text.")
            return "Unsupported file type: Could not decode as text."

# --- The Core Tool Implementation ---

def load_and_parse_drive_contents(folder_url: str, tool_context: ToolContext) -> dict:
    """
    Recursively finds all files (PDF, DOCX, TXT) in a Google Drive folder,
    parses their text content, and loads everything into the session state.
    """
    logging.info("=== DRIVE CONTENT LOADER STARTED ===")
    logging.info(f"Folder URL: {folder_url}")
    
    try:
        logging.info("Starting authentication...")
        creds = _authenticate_drive()
        service = build("drive", "v3", credentials=creds)
        logging.info("Service built successfully.")
        
        # Extract folder ID from various Google Drive URL formats
        folder_id = None
        if '/folders/' in folder_url:
            folder_id = folder_url.split('/folders/')[-1].split('?')[0].split('/')[0]
        elif '/d/' in folder_url: # Note: This is usually for files, but can be for folders
            folder_id = folder_url.split('/d/')[-1].split('/')[0]
        else:
            folder_id = folder_url.strip() # Assuming direct ID
        
        if not folder_id:
            raise ValueError("Could not extract a valid Folder ID from the provided URL.")

        logging.info(f"Extracted Folder ID: {folder_id}")
        
        logging.info(f"Discovering files in folder: {folder_id}")
        all_files = _list_files_recursively(service, folder_id)
        
        if not all_files:
            logging.warning("No files were found in the specified folder or its subfolders.")
            return {"status": "error", "message": "No files found in the folder or its subfolders."}
        
        logging.info(f"Found {len(all_files)} total files. Starting download and parse process...")
        
        parsed_files = []
        failed_files = []

        for i, file in enumerate(all_files, 1):
            filename = file.get("name")
            file_id = file.get("id")
            
            logging.info(f"-> Processing {i}/{len(all_files)}: '{filename}' (ID: {file_id})")
            
            try:
                content_resp = _read_drive_file_content(service, file_id)
                if content_resp["status"] == "error":
                    raise IOError(f"Failed to read file content: {content_resp['message']}")
                
                logging.info(f"  Successfully downloaded {len(content_resp['content'])} bytes.")
                text_content = _parse_content(filename, content_resp["content"])
                if "Unsupported file type" in text_content:
                     raise TypeError(text_content)

                # Simple file info - let LLM figure out what's what
                file_info = {
                    "filename": filename,
                    "file_id": file_id,
                    "content_length": len(text_content),
                    "text_content": text_content
                }
                
                parsed_files.append(file_info)
                logging.info(f"  ✅ Success: Parsed {len(text_content)} characters from '{filename}'")
                
            except Exception as e:
                failed_files.append({"filename": filename, "error": str(e)})
                logging.error(f"  ❌ Failed to process '{filename}': {e}", exc_info=True)
            
            # Brief pause between files to avoid overwhelming the API
            if i < len(all_files):
                time.sleep(0.5)
        
        logging.info("All files processed. Saving final data structure to session state...")
        
        # Simple structure - let LLM do the intelligent analysis
        drive_data = {
            "parsed_files": parsed_files,
            "failed_files": failed_files,
            "total_files": len(all_files),
            "successful_files": len(parsed_files)
        }
        
        # Store in session state
        tool_context.state["drive_data"] = drive_data
        
        logging.info(f"=== COMPLETED! Loaded {len(parsed_files)} files, {len(failed_files)} failed ===")
        
        # Final result should be a simple string for the LLM to use, not a complex object.
        # The detailed data is in the session state for the agent's internal use.
        return f"Successfully processed {len(parsed_files)} files. {len(failed_files)} failed."

    except Exception as e:
        logging.critical(f"CRITICAL ERROR in load_and_parse_drive_contents: {e}", exc_info=True)
        return {"status": "error", "message": f"A critical error occurred: {e}"}

def _read_drive_file_content(service, file_id: str, max_retries: int = 2) -> dict:
    """Helper to read file content using an existing service object with retry logic."""
    logging.info(f"    Reading content for file_id: {file_id}")
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait_time = attempt * 2  # 2, 4 seconds
                logging.info(f"    Retrying download in {wait_time} seconds...")
                time.sleep(wait_time)
            
            request = service.files().get_media(fileId=file_id)
            file_io = io.BytesIO()
            downloader = MediaIoBaseDownload(file_io, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logging.info(f"      Downloading... {int(status.progress() * 100)}%")
            
            content = file_io.getvalue()
            return {"status": "success", "content": content}
            
        except Exception as e:
            logging.error(f"    Exception during download (attempt {attempt+1}/{max_retries+1}): {e}", exc_info=True)
            if attempt == max_retries:
                return {"status": "error", "message": f"Failed to download after {max_retries+1} attempts: {e}"}

# --- Create and Export the Final Tool Object ---
drive_content_loader_tool = FunctionTool(
    func=load_and_parse_drive_contents
)