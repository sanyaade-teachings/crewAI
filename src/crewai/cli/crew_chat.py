import json
import subprocess
from typing import cast

import click

from crewai.cli.fetch_chat_llm import fetch_chat_llm
from crewai.cli.fetch_crew_inputs import fetch_crew_inputs
from crewai.types.crew_chat import ChatInputs


def run_chat():
    """
    Runs an interactive chat loop using the Crew's chat LLM with function calling.
    Incorporates crew_name, crew_description, and input fields to build a tool schema.
    Exits if crew_name or crew_description are missing.
    """
    click.secho("Welcome to CrewAI Chat with Function-Calling!", fg="green")

    # 1) Fetch CrewInputs
    click.secho("Gathering crew inputs via `fetch_crew_inputs()`...", fg="cyan")
    try:
        crew_inputs: ChatInputs = fetch_crew_inputs()
    except Exception as e:
        click.secho(f"Error fetching crew inputs: {e}", fg="red")
        return

    # Check for mandatory fields
    if not crew_inputs.crew_name:
        click.secho("Error: Crew name is missing. Exiting.", fg="red")
        return

    if not crew_inputs.crew_description:
        click.secho("Error: Crew description is missing. Exiting.", fg="red")
        return

    # 2) Generate a tool schema from the crew inputs
    crew_tool_schema = generate_crew_tool_schema(crew_inputs)

    # 3) Build initial system message
    required_fields_str = (
        ", ".join(
            f"{field.name} (desc: {field.description or 'n/a'})"
            for field in crew_inputs.inputs
        )
        or "(No required fields detected)"
    )

    system_message = (
        "You are a helpful AI assistant for the CrewAI platform. "
        "You have a function (tool) you can call by name if you have all required inputs. "
        f"Those required inputs are: {required_fields_str}. "
        "Once you have them, call the function. "
        "Please keep your responses concise and friendly."
        f"\nCrew Name: {crew_inputs.crew_name}"
        f"\nCrew Description: {crew_inputs.crew_description}"
    )

    messages = [
        {"role": "system", "content": system_message},
    ]

    # 4) Retrieve ChatLLM
    click.secho("\nFetching the Chat LLM...", fg="cyan")
    try:
        chat_llm = fetch_chat_llm()
    except Exception as e:
        click.secho(f"Failed to retrieve Chat LLM: {e}", fg="red")
        return
    if not chat_llm:
        click.secho("No valid Chat LLM returned. Exiting.", fg="red")
        return

    # 5) Prepare available_functions for the callback dictionary
    available_functions = {
        crew_inputs.crew_name: run_crew_tool,  # The LLM can call run_crew_tool using the crew's name
    }

    click.secho(
        "\nEntering an interactive chat loop with function-calling.\n"
        "Type 'exit' or Ctrl+C to quit.\n",
        fg="cyan",
    )

    # 6) Main chat loop
    while True:
        try:
            user_input = click.prompt("You: ", type=str)
            if user_input.strip().lower() in ["exit", "quit"]:
                click.echo("Exiting chat. Goodbye!")
                break

            # Append user message
            messages.append({"role": "user", "content": user_input})

            # Invoke the LLM, passing tools and available_functions
            final_response = chat_llm.call(
                messages=messages,
                tools=[crew_tool_schema],
                available_functions=available_functions,
            )

            # Append the final assistant response and print
            messages.append({"role": "assistant", "content": final_response})
            click.secho(f"\nAI: {final_response}\n", fg="green")

        except (KeyboardInterrupt, EOFError):
            click.echo("\nExiting chat. Goodbye!")
            break
        except Exception as e:
            click.secho(f"Error occurred: {e}", fg="red")
            break


def generate_crew_tool_schema(crew_inputs: ChatInputs) -> dict:
    """
    Dynamically build a Littellm 'function' schema for the given crew.

    crew_name: The name of the crew (used for the function 'name').
    crew_inputs: A ChatInputs object containing crew_description
                 and a list of input fields (each with a name & description).
    """
    properties = {}
    for field in crew_inputs.inputs:
        properties[field.name] = {
            "type": "string",
            "description": field.description or "No description provided",
        }

    required_fields = [field.name for field in crew_inputs.inputs]

    return {
        "type": "function",
        "function": {
            "name": crew_inputs.crew_name,
            "description": crew_inputs.crew_description or "No crew description",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required_fields,
            },
        },
    }


def run_crew_tool(**kwargs) -> str:
    """
    Subprocess-based function that:
      1) Calls 'uv run run_crew' (which in turn calls your crew's 'run()' in main.py)
      2) Passes the LLM-provided kwargs as CLI overrides (e.g. --key=value).
    """
    import subprocess

    command = ["uv", "run", "run_crew"]

    # Convert LLM arguments to --key=value CLI params
    for key, value in kwargs.items():
        val_str = str(value)
        command.append(f"--{key}={val_str}")

    try:
        # Capture stdout so we can return it to the LLM
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        stdout_str = result.stdout.strip()
        return stdout_str if stdout_str else "No output from run_crew command."
    except subprocess.CalledProcessError as e:
        return (
            f"Error: Command failed with exit code {e.returncode}\n"
            f"STDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}"
        )
    except Exception as e:
        return f"Unexpected error running crew: {e}"
