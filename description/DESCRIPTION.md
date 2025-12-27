# Multi‑Agent Research System
**Note** This is a mostly model-generated description of the pipeline (GPT 5.2). This is not completly proof-read, yet.

## Overview

This project implements a **multi‑agent, large‑language‑model–driven research pipeline** designed to answer questions with depth, structure, and evidence. Rather than generating a single monolithic answer, the system explicitly **plans, decomposes, executes, and synthesizes research** in stages, closely mirroring how a human research team would operate.

The result is a **high‑quality Markdown report** grounded in real web sources, structured reasoning, and explicit uncertainty handling. The system is optimized for *quality, traceability, and depth*.    
    
Also, the pipeline aims for speed by using concurrent Subagent calls.    

## High‑Level Flow

At a conceptual level, the system runs through four phases:

1. **Planning** – Turn a user’s question into a detailed research plan.
2. **Task Decomposition** – Split the plan into independent subtasks.
3. **Parallel Research** – Run multiple specialized research agents concurrently.
4. **Synthesis** – Integrate all findings into a single coherent report.

Each phase is handled by a different component, with different prompts, constraints, and (optionally) different models.

## General App Flow
    
![App Flow](./app-flow-alpha.png)

---

## Entry Point and User Experience

The main entry point is `app.py`.

When run, the user:
- Enters a natural‑language research query.
- Waits while the system performs planning, research, and synthesis.
- Receives a timestamped Markdown file saved to `results/`.

All orchestration is handled by a single function call:
`run_deep_research(user_query)`.

---

## Research Planning

The planning phase is handled by `planner.py`.

A dedicated **planner LLM** receives the raw user query and produces a **research plan**, not an answer. This plan includes:
- Key dimensions and perspectives to investigate
- Explicit assumptions and open‑ended aspects
- Desired structure of the final output
- Guidance on evidence quality and sources

This step externalizes reasoning and ensures that downstream agents operate from a shared, explicit understanding of the task.

---

## Task Splitting

The research plan is passed to `task_splitter.py`.

A separate LLM breaks the plan into **3–8 non‑overlapping subtasks**, each with:
- A short identifier
- A descriptive title
- Detailed instructions for a research agent

The output is required to be **strict JSON**, validated against a schema. This ensures the subtasks are machine‑readable, predictable, and safe to execute in parallel.

---

## Sub‑Agent Research Execution

Each subtask is executed by a dedicated **tool‑calling research agent**, orchestrated in `coordinator.py`.

### Sub‑agent characteristics

Each sub‑agent:
- Focuses on exactly one subtask
- Has access to web search and page‑fetching tools
- Is instructed to prioritize primary and authoritative sources
- Explicitly acknowledges uncertainty and disagreement
- Produces a structured Markdown mini‑report

Sub‑agents do not coordinate with each other; independence is a deliberate design choice to reduce bias and overlap.

### Parallelism

Subtasks are executed concurrently using a thread pool. This:
- Improves performance
- Prevents single‑point reasoning failures
- Mirrors a real research team working in parallel

Failures are captured and reported without aborting the entire run.

---

## Web Search and Scraping

### Search

The search layer (`search.py`) provides:
- Google Custom Search as the primary backend
- Automatic fallback to DuckDuckGo if Google fails
- Normalized result objects independent of provider

### Scraping

The scraping layer (`scraper.py`) is responsible for extracting usable text:
- Fast HTTP scraping for static pages
- Playwright‑based scraping for JavaScript‑heavy sites
- Heuristic detection of main article content
- Conversion of HTML into clean Markdown
- Automatic skipping of download links (PDFs, ZIPs, etc.)

This ensures agents reason over **actual page content**, not just snippets.

---

## Final Synthesis

Once all subtasks complete, the system performs a synthesis step.

A **coordinator LLM** receives:
- The original user question
- The research plan
- All sub‑agent reports (including partial failures)

It is instructed to:
- Integrate findings across all subtasks
- Eliminate redundancy
- Reconcile disagreements
- Explain reasoning and trade‑offs
- Highlight uncertainty and open questions
- Produce a polished, standalone Markdown report

The synthesis agent is explicitly forbidden from mentioning tools, agents, or internal processes. The output is intended to read like a human‑written research document.

---

## Configuration and Model Separation

All models and APIs are configured via environment variables (see `env.example`).

Different models can be used independently for:
- Planning
- Task splitting
- Sub‑agent research
- Final synthesis

This allows flexible trade‑offs between cost, speed, and quality, and supports multiple providers through a unified interface.

---

## Design Philosophy

This project is built around a few core ideas:

- **Structure improves reliability**: Explicit plans outperform implicit reasoning.
- **Decomposition reduces hallucination**: Smaller, focused tasks are more robust.
- **Parallelism improves coverage**: Independent agents surface diverse perspectives.
- **Synthesis is a distinct skill**: Writing and reasoning benefit from separation.

The system intentionally favors clarity, modularity, and inspectability over minimalism.

---

## Why This Design?

This system is deliberately structured as a **multi‑stage, multi‑agent pipeline** rather than a single prompt or autonomous agent. The design reflects practical lessons from using large language models for complex research tasks.

### Explicit Planning Over Implicit Reasoning

Instead of relying on a model to internally “figure out what to research,” the system forces an explicit **research planning step**. This makes assumptions, dimensions, and goals visible and auditable. In practice, this reduces shallow answers and helps prevent important angles from being silently ignored.

### Decomposition to Reduce Hallucination

Breaking a research task into narrowly scoped subtasks improves reliability. Smaller, focused prompts are less likely to hallucinate, more likely to seek relevant evidence, and easier to correct or rerun independently. This also makes partial failures survivable rather than catastrophic.

### Parallel, Independent Agents

Sub‑agents operate independently and in parallel, without sharing intermediate reasoning. This mirrors real research teams and helps surface **diverse perspectives**, disagreements, and edge cases that a single agent might collapse into a single narrative.

### Separation of Research and Writing

Research and synthesis are treated as different cognitive tasks. Sub‑agents focus on gathering and analyzing information, while the final synthesis agent focuses on **integration, explanation, and communication**. This separation produces clearer, more coherent final reports.

### Tool‑Grounded Reasoning

Agents work over **actual fetched source content**, not just search snippets or model priors. This design favors grounded reasoning and makes it easier to trace claims back to real sources, even though the final report intentionally hides internal mechanics.

---

## Limitations & Trade‑Offs

This design makes several conscious trade‑offs. Understanding these is important for correct expectations and future extensions.

### Latency and Cost

Running multiple models sequentially and in parallel is slower and more expensive than a single prompt. This system prioritizes **depth and quality** over speed and minimal token usage.

### Complexity Over Simplicity

The architecture introduces orchestration logic, multiple prompts, and more moving parts. This increases maintenance cost and makes the system harder to reason about compared to a single‑agent setup.

### No Persistent Memory

Each run is stateless. The system does not learn from previous runs, cache results, or build long‑term knowledge. This keeps behavior predictable but limits cumulative intelligence.

### Limited Citation Guarantees

While agents are instructed to use high‑quality sources, the final synthesis step integrates prose rather than producing strict, machine‑verifiable citations. The output is suitable for human reading, not automatic fact‑checking pipelines.

### Best for Exploratory, Not Deterministic Tasks

The system excels at **open‑ended, exploratory research** with ambiguous or multi‑dimensional questions. It is not optimized for deterministic queries, simple lookups, or tasks with a single correct answer.
