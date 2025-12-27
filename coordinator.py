from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import json
import logging
import os
import sys
from typing import Optional

from prompts import SUBAGENT_PROMPT_TEMPLATE, COORDINATOR_SYNTHESIS_PROMPT_TEMPLATE
from planner import generate_research_plan
from scraper import fetch_url, is_likely_download_url
from search import search_with_fallback
from task_splitter import split_into_subtasks

import litellm
from slugify import slugify
from smolagents import LiteLLMModel, ToolCallingAgent, tool
from smolagents.monitoring import LogLevel

litellm.drop_params = True

# ******************************
# Logging configuration
# ******************************
# Suppress noisy loggers
for noisy in [
    "smolagents", "smolagents.agents", "smolagents.tools",
    "smolagents.models", "smolagents.monitoring",
    "litellm", "LiteLLM",
    "scrapegraphai", "urllib3", "httpx", "httpcore",
]:
    logging.getLogger(noisy).setLevel(logging.CRITICAL)

litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)

# ******************************
# Define models for coordinator (sythesis) and subagents
# ******************************
LLM_COORDINATOR_MODEL = os.environ["LLM_COORDINATOR_MODEL"]
LLM_COORDINATOR_BASE_URL = os.environ["LLM_COORDINATOR_BASE_URL"]
LLM_COORDINATOR_API_KEY = os.environ["LLM_COORDINATOR_API_KEY"]

LLM_COORDINATOR_CONFIG = {
    "model_id": LLM_COORDINATOR_MODEL,
    "api_key": LLM_COORDINATOR_API_KEY,
    "api_base": LLM_COORDINATOR_BASE_URL,
    "drop_params": True,
}

LLM_SUBAGENT_MODEL = os.environ["LLM_SUBAGENT_MODEL"]
LLM_SUBAGENT_BASE_URL = os.environ["LLM_SUBAGENT_BASE_URL"]
LLM_SUBAGENT_API_KEY = os.environ["LLM_SUBAGENT_API_KEY"]

LLM_SUBAGENT_CONFIG = {
    "model_id": LLM_SUBAGENT_MODEL,
    "api_key": LLM_SUBAGENT_API_KEY,
    "api_base": LLM_SUBAGENT_BASE_URL,
    "drop_params": True,
}


def get_model(use_config: str = "coordinator") -> LiteLLMModel:
    """
    Factory function for consistent model creation.
    Pass which config to use by passing "coordinator" or "subagent"
    """
    model_configs = {"coordinator": LLM_COORDINATOR_CONFIG, "subagent": LLM_SUBAGENT_CONFIG}
    try:
        use_config = model_configs[use_config]
        return LiteLLMModel(**use_config)
    except:
        return LiteLLMModel(**model_configs.get("coordinator"))


# ******************************
# more debug output suppression
# ******************************
@contextmanager
def filtered_agent_output():
    """Filter out noisy smolagents messages while preserving useful output."""
    
    patterns_to_hide = [
        # Tool call parsing errors (normal - happens when agent gives final answer)
        "Error while parsing tool call",
        "does not contain any JSON blob",
        # JSON decoding errors (occasional LLM format glitches)
        "JSON blob was:",
        "decoding failed on that specific part",
        # Any other smolagents noise you encounter
        "Traceback (most recent call last):",  # Optional: hide tracebacks too
    ]
    
    class FilteredStream:
        def __init__(self, original):
            self.original = original
            self.line_buffer = ""
            self.suppressing_block = False  # For multi-line error blocks
        
        def write(self, text):
            self.line_buffer += text
            
            while "\n" in self.line_buffer:
                line, self.line_buffer = self.line_buffer.split("\n", 1)
                
                # Check if this line starts a block we want to suppress
                if any(pattern in line for pattern in patterns_to_hide):
                    self.suppressing_block = True
                    continue
                
                # If we're in a suppression block, check if this line ends it
                # (empty line or a line starting with our output prefix)
                if self.suppressing_block:
                    if line.strip() == "" or line.startswith("\033["):
                        self.suppressing_block = False
                    else:
                        continue  # Skip this line
                
                self.original.write(line + "\n")
        
        def flush(self):
            if self.line_buffer and not self.suppressing_block:
                if not any(pattern in self.line_buffer for pattern in patterns_to_hide):
                    self.original.write(self.line_buffer)
            self.line_buffer = ""
            self.suppressing_block = False
            self.original.flush()
        
        def __getattr__(self, name):
            return getattr(self.original, name)
    
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = FilteredStream(old_stdout)
    sys.stderr = FilteredStream(old_stderr)
    
    try:
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout = old_stdout
        sys.stderr = old_stderr


# ============================================================
# TOOLS (defined at module level, not nested)
# ============================================================
@tool
def fetch_page(url: str) -> str:
    """
    Fetch the readable content of a web page.

    Args:
        url (str): The URL of the page to fetch.

    Returns:
        str: Extracted page content or an error message.
    """
    # Early rejection of download URLs
    if is_likely_download_url(url):
        return "Skipped: URL appears to be a file download"
    
    content = fetch_url(url=url)
    
    if content:
        return content
    
    return "Error: Could not fetch page content"

@tool
def search_and_fetch(query: str, num_results: int = 10) -> list[dict]:
    """
    Search Google AND fetch the content of top results.
    
    This is the PRIMARY research tool. It searches for information
    and returns the actual page content, not just snippets.
    Falls back to DuckDuckGo if Google returns no results.

    Args:
        query (str): The search query to send to Google.
        num_results (int): Number of pages to fetch (max 5).

    Returns:
        list[dict]: List of results with title, url, snippet, and full_content.
    """
    print(f"    🔍 Searching: {query}")
    
    num_results = min(num_results, 5)
    
    # Use fallback search
    search_results, source = search_with_fallback(query, num_results)
    
    if not search_results:
        print(f"    ❌ No search results from any source")
        return []
    
    print(f"    ✓ Got {len(search_results)} results from {source}")

    results = []
    for item in search_results:
        url = item.get("url")
        
        if not url:
            continue

        # Skip download URLs early
        if is_likely_download_url(url):
            print(f"    ⏭️  Skipping download: {url}")
            continue

        result = {
            "title": item.get("title"),
            "url": url,
            "snippet": item.get("snippet"),
            "full_content": None,
            "fetch_status": "not_attempted",
            "search_source": source,
        }
        
        print(f"    📄 Fetching: {url}")
        try:
            content = fetch_url(url)
            if content:
                result["full_content"] = content[:15000]
                result["fetch_status"] = "success"
            else:
                result["full_content"] = item.get("snippet", "No content available")
                result["fetch_status"] = "failed_using_snippet"
        except Exception as e:
            result["full_content"] = item.get("snippet", f"Fetch error: {e}")
            result["fetch_status"] = "error"
        
        results.append(result)
    
    return results

# ============================================================
# SUBAGENT RUNNER (explicit function, not a tool)
# ============================================================

class SubtaskResult:
    """Container for subtask execution results."""
    def __init__(self, subtask_id: str, title: str, report: str, success: bool = True, error: Optional[str] = None):
        self.subtask_id = subtask_id
        self.title = title
        self.report = report
        self.success = success
        self.error = error


def run_subagent(
    subtask: dict,
    user_query: str,
    research_plan: str,
    max_retries: int = 2
) -> SubtaskResult:
    """
    Execute a single research subtask with a dedicated subagent.
    
    This is a regular function, NOT an agent tool. The coordinator
    calls this directly via Python control flow.

    Note:
    - subtask_id must not consist of any special chars such as "-"
        - subtask["id"] is created by model, hence special chars can occure
        - Hence, simply slugify subtask["id"] and change "-" to "_"
            - creates valid Python identifier
    - Otherwise throws error such as:
        oss-alternatives: Subtask failed after 2 attempts: Agent name 'subagent_oss-alternatives' must be a valid Python identifier and not a reserved keyword.
    """
    subtask_id = slugify(subtask["id"]).replace("-", "_")  # handle any special char
    subtask_title = subtask["title"]
    subtask_description = subtask["description"]
    
    print(f"\033[94m[Subagent {subtask_id}] Starting: {subtask_title}\033[0m")
    
    for attempt in range(max_retries):
        try:
            subagent = ToolCallingAgent(
                tools=[search_and_fetch, fetch_page],
                model=get_model(use_config="subagent"),
                add_base_tools=False,
                name=f"subagent_{subtask_id}",
                verbosity_level=LogLevel.ERROR,
            )
            
            prompt = SUBAGENT_PROMPT_TEMPLATE.format(
                user_query=user_query,
                research_plan=research_plan,
                subtask_id=subtask_id,
                subtask_title=subtask_title,
                subtask_description=subtask_description,
            )
            
            # Filter out the noisy parsing messages
            with filtered_agent_output():
                result = subagent.run(prompt)

            report = str(result)
            
            print(f"\033[92m[Subagent {subtask_id}] Completed\033[0m")
            return SubtaskResult(subtask_id, subtask_title, report)
            
        except Exception as e:
            logger.warning(f"Subagent {subtask_id} attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                error_msg = f"Subtask failed after {max_retries} attempts: {e}"
                return SubtaskResult(
                    subtask_id, subtask_title, 
                    f"[Research incomplete due to error: {e}]",
                    success=False, 
                    error=error_msg
                )
    
    # Should not reach here, but just in case
    return SubtaskResult(subtask_id, subtask_title, "[No result]", success=False)

# ============================================================
# MAIN ORCHESTRATION (no coordinator agent needed)
# ============================================================

def run_deep_research(user_query: str, parallel: bool = True, max_workers: int = 10) -> str:
    """
    Execute deep research on a user query.
    
    Args:
        user_query: The research question
        parallel: Whether to run subtasks in parallel
        max_workers: Max concurrent subagents (if parallel=True)
    
    Returns:
        Final synthesized research report
    """
    # *************
    # 1 - Generate research plan
    # *************
    print("\033[93m[Phase 1] Generating Research Plan\033[0m")
    research_plan = generate_research_plan(user_query)
    
    # *************
    # 2 - Split into subtasks
    # *************
    print()
    print("\033[93m[Phase 2] Generating Subtasks\033[0m")
    subtasks = split_into_subtasks(research_plan)
    print(f"  → {len(subtasks)} subtasks identified")
    
    # *************
    # 3 - Execute subtasks (parallel)
    # *************
    print()
    print(f"\033[93m[Phase 3] Executing Subtasks ({'parallel' if parallel else 'sequential'})\033[0m")
    results: list[SubtaskResult] = []
    
    results = _run_subtasks(subtasks, user_query, research_plan, max_workers)
    
    # *************
    # 4 - Log any failures
    # *************
    failed = [r for r in results if not r.success]
    if failed:
        print()
        print(f"\033[91m  ⚠ {len(failed)} subtask(s) had errors\033[0m")
        for r in failed:
            print(f"    - {r.subtask_id}: {r.error}")

    # *************
    # 5 - Synthesize final report
    # *************
    print()
    print("\033[93m[Phase 4] Synthesizing Final Report\033[0m")
    final_report = _synthesize_report(user_query, research_plan, results)
    
    return final_report


def _run_subtasks(
    subtasks: list[dict],
    user_query: str,
    research_plan: str,
    max_workers: int
) -> list[SubtaskResult]:
    """
    Run subtasks concurrently with a thread pool.
    
    If you want a simple sequential run, use:
        return [
            run_subagent(subtask, user_query, research_plan)
            for subtask in subtasks
        ]
    instead of threadding.
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_subtask = {
            executor.submit(run_subagent, subtask, user_query, research_plan): subtask
            for subtask in subtasks
        }
        
        for future in as_completed(future_to_subtask):
            subtask = future_to_subtask[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"Subtask {subtask['id']} raised exception: {e}")
                results.append(SubtaskResult(
                    subtask["id"], 
                    subtask["title"],
                    f"[Fatal error: {e}]",
                    success=False,
                    error=str(e)
                ))
    
    # Sort by original order for consistent output
    id_order = {s["id"]: i for i, s in enumerate(subtasks)}
    results.sort(key=lambda r: id_order.get(r.subtask_id, 999))
    
    return results


def _synthesize_report(
    user_query: str,
    research_plan: str,
    results: list[SubtaskResult]
) -> str:
    """Combine all subtask reports into a final synthesis."""
    # *************
    # Format reports for the synthesis prompt
    # *************
    report_sections = []
    for r in results:
        status = "" if r.success else " [PARTIAL]"
        report_sections.append(f"=== Subtask {r.subtask_id}: {r.title}{status} ===\n{r.report}")
    
    subagent_reports_text = "\n\n".join(report_sections)
    
    synthesis_prompt = COORDINATOR_SYNTHESIS_PROMPT_TEMPLATE.format(
        user_query=user_query,
        research_plan=research_plan,
        subagent_reports=subagent_reports_text,
    )

    # *************
    # Create report
    # *************
    synthesis_model = get_model()
    response = synthesis_model.generate(
        messages=[{"role": "user", "content": synthesis_prompt}]
    )
    
    content = response.content

    if isinstance(content, str):
        return content
    
    return str(content) if content else ""