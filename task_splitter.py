import os
import json
from typing import List
from pydantic import BaseModel, Field

# from huggingface_hub import InferenceClient
from litellm import completion
from prompts import TASK_SPLITTER_SYSTEM_INSTRUCTIONS

LLM_SUBTASKS_MODEL = os.environ["LLM_SUBTASKS_MODEL"]
LLM_SUBTASKS_BASE_URL = os.environ["LLM_SUBTASKS_BASE_URL"]
LLM_SUBTASKS_API_KEY = os.environ["LLM_SUBTASKS_API_KEY"]

class Subtask(BaseModel):
    id: str = Field(
        ...,
        description="Short identifier for the subtask (e.g. 'A', 'history', 'drivers').",
    )
    title: str = Field(
        ...,
        description="Short descriptive title of the subtask.",
    )
    description: str = Field(
        ...,
        description="Clear, detailed instructions for the sub-agent that will research this subtask.",
    )

class SubtaskList(BaseModel):
    subtasks: List[Subtask] = Field(
        ...,
        description="List of subtasks that together cover the whole research plan.",
    )

TASK_SPLITTER_JSON_SCHEMA = {
    "name": "subtaskList",
    "schema": SubtaskList.model_json_schema(),
    "strict": True,
}

def split_into_subtasks(research_plan: str) -> List[Subtask]:
    print("Splitting the research plan into subtasks...")
    print("MODEL: ", LLM_SUBTASKS_MODEL)
    print("API_BASE: ", LLM_SUBTASKS_BASE_URL)

    from typing import Any

    response: Any = completion(
        model=LLM_SUBTASKS_MODEL,
        api_base=LLM_SUBTASKS_BASE_URL,
        api_key=LLM_SUBTASKS_API_KEY,
        messages=[
            {"role": "system", "content": TASK_SPLITTER_SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": research_plan},
        ],
        stream=False,
    )

    content = response.choices[0].message.content
    subtasks = json.loads(content)["subtasks"]

    return subtasks

if __name__ == "__main__":
    with open("example-results/1_research_plan.md") as f:
        plan = f.read()
    subtasks = split_into_subtasks(research_plan=plan)
    print(json.dumps(subtasks, indent=2, ensure_ascii=False))