from datetime import datetime

from coordinator import run_deep_research

from dotenv import load_dotenv
from slugify import slugify



def _build_slug(query: str, max_length: int = 40) -> str:
    base = slugify(query)
    if not base:
        return "research-result"
    parts = base.split("-")
    slug = ""
    for part in parts:
        candidate = part if not slug else f"{slug}-{part}"
        if len(candidate) > max_length:
            break
        slug = candidate
    return slug or "research-result"


def start_research_process():
    load_dotenv()
    user_query = input("Enter your research query: ")
    result = run_deep_research(user_query)

    slug = _build_slug(user_query, max_length=40)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
    filename = f"{slug}-{timestamp}.md"
    path = f"results/{filename}"

    with open(path, "w") as f:
        f.write(result)

    print(f"Research result saved to {path}")


if __name__ == "__main__":
    start_research_process()
