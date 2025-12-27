# Example Results
This directory holds example results of each step of the processing chain executed in coordinator.py    
    
If you want to delete this directory, do not forget to remove (or edit in some way)
```python
if __name__ == "__main__":
    with open("example-results/1_research_plan.md") as f:
        plan = f.read()
    subtasks = split_into_subtasks(research_plan=plan)
    print(json.dumps(subtasks, indent=2, ensure_ascii=False))
```
in task_splitter.py