# deploy.py
import os

from absl import app
from absl import flags
from dotenv import load_dotenv
from resume_agent.agent import root_agent
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

FLAGS = flags.FLAGS
flags.DEFINE_string("project_id", None, "GCP project ID.")
flags.DEFINE_string("location", None, "GCP location.")
flags.DEFINE_string("bucket", None, "GCP bucket for staging.")
flags.DEFINE_string("resource_id", None, "ReasoningEngine resource ID for deletion or update.")

flags.DEFINE_bool("list", False, "List all agents.")
flags.DEFINE_bool("create", False, "Creates a new agent.")
flags.DEFINE_bool("update", False, "Updates an existing agent.")
flags.DEFINE_bool("delete", False, "Deletes an existing agent.")
flags.mark_bool_flags_as_mutual_exclusive(["create", "delete", "list", "update"])


def create() -> None:
    """Creates an agent engine for the TalentRank Agent."""
    print("Creating agent...")
    adk_app = AdkApp(
        agent=root_agent, 
        enable_tracing=True)

    requirements = "requirements.txt"

    remote_agent = agent_engines.create(
        adk_app,
        display_name=root_agent.name,
        requirements=requirements,
        extra_packages=["resume_agent"],
    )
    print(f"Created remote agent: {remote_agent.resource_name}")
    print(f"Remote agent: {remote_agent}")


def update(resource_id: str, project_id: str, location: str) -> None:
    """Updates a deployed agent by its numerical resource ID."""
    full_resource_name = f"projects/{project_id}/locations/{location}/reasoningEngines/{resource_id}"
    print(f"Updating agent: {full_resource_name}...")
    adk_app = AdkApp(agent=root_agent, enable_tracing=True)
    requirements = "requirements.txt"
    updated_agent = agent_engines.update(
        resource_name=full_resource_name,
        agent_engine=adk_app,
        requirements=requirements,
        extra_packages=["resume_agent"],
    )
    print(f"Updated remote agent: {updated_agent.resource_name}")


def delete(resource_id: str, project_id: str, location: str) -> None:
    """Deletes a deployed agent by its numerical resource ID."""
    full_resource_name = f"projects/{project_id}/locations/{location}/reasoningEngines/{resource_id}"
    print(f"Deleting agent: {full_resource_name}...")
    remote_agent = agent_engines.get(full_resource_name)
    remote_agent.delete(force=True)
    print(f"Deleted remote agent: {full_resource_name}")


def list_agents() -> None:
    """Lists all deployed agents in the project and location."""
    print("Listing all agents...")
    remote_agents = agent_engines.list()
    template = '''
- Display Name: "{agent.display_name}"
  Numerical ID: {numerical_id}
  Full Resource Name: {agent.resource_name}
  Create Time: {agent.create_time}
  Update Time: {agent.update_time}
'''
    if not remote_agents:
        print("No agents found.")
        return

    agent_strings = []
    for agent in remote_agents:
        numerical_id = agent.resource_name.split('/')[-1]
        agent_strings.append(template.format(agent=agent, numerical_id=numerical_id))

    remote_agents_string = '\n'.join(agent_strings)
    print(f"All remote agents:\n{remote_agents_string}")

def main(argv: list[str]) -> None:
    del argv  # unused
    # Load the .env file from the agent's directory, not the project root.
    dotenv_path = os.path.join(os.path.dirname(__file__), 'resume_agent', '.env')
    load_dotenv(dotenv_path=dotenv_path)

    project_id = (
        FLAGS.project_id
        if FLAGS.project_id
        else os.getenv("GOOGLE_CLOUD_PROJECT")
    )
    location = (
        FLAGS.location if FLAGS.location else os.getenv("GOOGLE_CLOUD_LOCATION")
    )
    # The bucket name in deploy.py was PROJECT_ID + "-adk-staging-bucket"
    # We will use that as a default if GOOGLE_CLOUD_STORAGE_BUCKET is not set.
    bucket = (
        FLAGS.bucket if FLAGS.bucket
        else os.getenv("GOOGLE_CLOUD_STORAGE_BUCKET")
    )
    if not bucket and project_id:
        bucket = f"{project_id}-adk-staging-bucket"


    print(f"Using Project: {project_id}")
    print(f"Using Location: {location}")
    print(f"Using Staging Bucket: {bucket}\n")


    if not project_id:
        print("Missing required config: GOOGLE_CLOUD_PROJECT. Set it via --project_id or in a .env file.")
        return
    elif not location:
        print("Missing required config: GOOGLE_CLOUD_LOCATION. Set it via --location or in a .env file.")
        return
    elif not bucket:
        print(
            "Missing required config: Staging bucket. Set it via --bucket or GOOGLE_CLOUD_STORAGE_BUCKET in a .env file."
        )
        return

    vertexai.init(
        project=project_id,
        location=location,
        staging_bucket=f"gs://{bucket}",
    )

    if FLAGS.list:
        list_agents()
    elif FLAGS.create:
        print(f"Ensure bucket exists: gsutil mb -p {project_id} -l {location} gs://{bucket}\n")
        create()
    elif FLAGS.update:
        if not FLAGS.resource_id:
            print("Error: --resource_id is required to update an agent.")
            return
        update(FLAGS.resource_id, project_id, location)
    elif FLAGS.delete:
        if not FLAGS.resource_id:
            print("Error: --resource_id is required to delete an agent.")
            return
        delete(FLAGS.resource_id, project_id, location)
    else:
        print("No command specified. Use --create, --list, --delete, or --update.")


if __name__ == "__main__":
    app.run(main)