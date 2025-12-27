import logging
import os

from prompts import PLANNER_SYSTEM_INSTRUCTIONS

from litellm import completion
import litellm

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)


LLM_PLANNER_MODEL = os.environ["LLM_PLANNER_MODEL"]
LLM_PLANNER_BASE_URL = os.environ["LLM_PLANNER_BASE_URL"]
LLM_PLANNER_API_KEY = os.environ["LLM_PLANNER_API_KEY"]

def generate_research_plan(user_query: str) -> str:
    print("Generating the research plan for the query: ", user_query)
    print("MODEL: ", LLM_PLANNER_MODEL)
    print("API_BASE: ", LLM_PLANNER_BASE_URL)

    response = completion(
        model=LLM_PLANNER_MODEL,
        api_base=LLM_PLANNER_BASE_URL,
        api_key=LLM_PLANNER_API_KEY,
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": user_query},
        ],
        stream=False,
    )

    research_plan = response.choices[0].message.content

    return research_plan

if __name__ == "__main__":
    research_plan = generate_research_plan(user_query="What is a good pet for a 9 year old kid?")
    print(research_plan)