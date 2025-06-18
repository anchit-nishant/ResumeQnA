# resume_agent/tools.py

import io
from pypdf import PdfReader
import docx # python-docx
import google.auth
import requests
import logging
import sys
import os
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.cloud import storage
from google.adk.tools import FunctionTool, ToolContext
import concurrent.futures

# Configure logging to output to stdout to be captured by Cloud Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    force=True  # Ensure this config is applied even if another lib configured logging
)

SCOPES = ["https://www.googleapis.com/auth/drive"]

# --- Generic Supporting Functions ---

def _parse_content(filename: str, content: bytes) -> str:
    """Parses content based on file extension."""
    logging.info(f"  Parsing content for: {filename}")
    if filename.lower().endswith('.pdf'):
        logging.info("    Using PDF parser (pypdf)...")
        try:
            reader = PdfReader(io.BytesIO(content))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except Exception as e:
            logging.error(f"    Failed to parse PDF {filename} with pypdf: {e}")
            return f"Error parsing PDF: {e}"
    elif filename.lower().endswith('.docx'):
        logging.info("    Using DOCX parser (python-docx)...")
        doc = docx.Document(io.BytesIO(content))
        return "\n".join([para.text for para in doc.paragraphs])
    elif filename.lower().endswith('.txt'):
        logging.info("    Using text parser...")
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            logging.warning("    Fallback parser failed. File is not valid UTF-8 text.")
            return "Unsupported file type: Could not decode as text."
    else:
        logging.info(f"    Unsupported file type for {filename}, skipping.")
        return "Unsupported file type"


# --- Google Drive Specific Functions ---

def _get_service_account_email_from_metadata():
    """Queries the GCE metadata server to get the default service account email."""
    logging.info("Querying metadata server for service account email...")
    try:
        url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
        headers = {"Metadata-Flavor": "Google"}
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
    service_account_email = _get_service_account_email_from_metadata()
    credentials, project = google.auth.default(scopes=SCOPES)
    if not service_account_email:
        logging.warning("Metadata server query failed, attempting to get email from credentials object...")
        service_account_email = getattr(credentials, 'service_account_email', 'N/A')
    logging.info(f"--> Service Account Email for Drive API: {service_account_email}")
    logging.info(f"Authentication resolved for project: {project}")
    return credentials

def _list_files_recursively(service, folder_id: str) -> list:
    """Recursively lists all files in a folder and its subfolders."""
    all_files = []
    page_token = None
    while True:
        try:
            response = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces='drive',
                fields='nextPageToken, files(id, name, mimeType)',
                pageToken=page_token
            ).execute()
            for file in response.get('files', []):
                if file.get('mimeType') == 'application/vnd.google-apps.folder':
                    all_files.extend(_list_files_recursively(service, file.get('id')))
                else:
                    all_files.append(file)
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        except HttpError as error:
            logging.error(f"Drive API error on files.list for folder '{folder_id}': {error}")
            return []
    return all_files

def _read_drive_file_content(service, file_id: str) -> dict:
    """Helper to read file content from Drive."""
    try:
        request = service.files().get_media(fileId=file_id)
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        return {"status": "success", "content": file_io.getvalue()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def load_and_parse_drive_contents(folder_url: str, tool_context: ToolContext) -> dict:
    """
    Use this to load all resumes and a job description from a Google Drive folder. Provide the folder URL.
    This function finds all files in a Google Drive folder, parses their content, and loads them into session state.
    """
    logging.info("=== DRIVE CONTENT LOADER STARTED ===")
    try:
        creds = _authenticate_drive()
        service = build("drive", "v3", credentials=creds)
        
        folder_id = folder_url.split('/folders/')[-1].split('?')[0] if '/folders/' in folder_url else folder_url
        logging.info(f"Extracted Folder ID: {folder_id}")
        
        all_files = _list_files_recursively(service, folder_id)
        if not all_files:
            return {"status": "error", "message": "No files found in the folder."}

        parsed_files, failed_files = [], []
        for file in all_files:
            filename = file.get("name")
            logging.info(f"-> Processing '{filename}'")
            try:
                content_resp = _read_drive_file_content(service, file.get("id"))
                if content_resp["status"] == "error":
                    raise IOError(content_resp['message'])
                
                text_content = _parse_content(filename, content_resp["content"])
                if "Unsupported file type" in text_content:
                    raise TypeError(text_content)
                
                parsed_files.append({"filename": filename, "content": text_content})
            except Exception as e:
                failed_files.append({"filename": filename, "error": str(e)})
        
        drive_data = {
            "source": "Google Drive",
            "parsed_files": parsed_files,
            "failed_files": failed_files
        }
        tool_context.state["drive_data"] = drive_data
        
        return f"Successfully processed {len(parsed_files)} files from Drive. {len(failed_files)} failed."
    except Exception as e:
        logging.critical(f"CRITICAL ERROR in load_and_parse_drive_contents: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

# --- Google Cloud Storage Specific Functions ---

def _download_blob_content(blob):
    """Downloads a single blob's content and returns it with its name."""
    filename = os.path.basename(blob.name)
    logging.info(f"  Queueing download for: {filename}")
    try:
        content = blob.download_as_bytes()
        logging.info(f"  ✅ Downloaded {filename}")
        return filename, content
    except Exception as e:
        logging.error(f"  ❌ Failed to download {filename}: {e}")
        return filename, None

def load_and_parse_gcs_contents(gcs_folder_url: str, tool_context: ToolContext) -> dict:
    """
    Use this to load all resumes and a job description from a Google Cloud Storage (GCS) folder. Provide the GCS URL (e.g., gs://bucket/folder/). This is faster.
    This function finds all files in a GCS folder, parses their content in parallel, and loads them into session state.
    """
    logging.info("=== GCS CONTENT LOADER STARTED (PARALLEL) ===")
    try:
        if not gcs_folder_url.startswith("gs://"):
            raise ValueError("Invalid GCS URL. Must start with 'gs://'.")
        
        storage_client = storage.Client()
        bucket_name, prefix = gcs_folder_url[5:].split("/", 1)
        prefix = prefix if prefix.endswith('/') else prefix + '/'
        
        blobs = [blob for blob in storage_client.list_blobs(bucket_name, prefix=prefix) if not blob.name.endswith('/')]
        
        if not blobs:
            return {"status": "error", "message": "No files found in GCS folder."}

        logging.info(f"Found {len(blobs)} files. Starting parallel download...")

        # Use a ThreadPoolExecutor to download files in parallel
        downloaded_content = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_blob = {executor.submit(_download_blob_content, blob): blob for blob in blobs}
            for future in concurrent.futures.as_completed(future_to_blob):
                downloaded_content.append(future.result())

        logging.info("All downloads complete. Starting sequential parsing...")
        
        parsed_files, failed_files = [], []
        for filename, content in downloaded_content:
            if content is None:
                failed_files.append({"filename": filename, "error": "Download failed"})
                continue

            logging.info(f"-> Parsing '{filename}'")
            try:
                text_content = _parse_content(filename, content)
                if "Unsupported file type" in text_content:
                    raise TypeError(text_content)
                parsed_files.append({"filename": filename, "content": text_content})
            except Exception as e:
                failed_files.append({"filename": filename, "error": str(e)})

        gcs_data = {
            "source": "GCS (Parallel)",
            "parsed_files": parsed_files,
            "failed_files": failed_files,
        }
        tool_context.state["gcs_data"] = gcs_data
        
        return f"Successfully processed {len(parsed_files)} files from GCS. {len(failed_files)} failed."
    except Exception as e:
        logging.critical(f"CRITICAL ERROR in load_and_parse_gcs_contents: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# --- Tool Definitions ---

drive_content_loader_tool = FunctionTool(load_and_parse_drive_contents)

gcs_content_loader_tool = FunctionTool(load_and_parse_gcs_contents)