# Prompt Engineering Log — LangGraph Agent

Tracks every prompt version for each LLM-involved node. Each version documents the
prompt text, failure modes observed, and what was changed for the next iteration.

## Nodes with LLM involvement

| Node | LLM? | Notes |
|------|------|-------|
| `intake_node` | No | Pure normalization |
| `classifier_node` | No | Keyword scan |
| `confidence_node` | No | Scoring math |
| `rag_node` | No (v1) | Embedding + Pinecone vector search only — no synthesis |
| `clarify_node` | No | Template string |
| `analyst_node` | **Yes** | The only real LLM call — `gpt-4.1-nano`, temp=0 |
| `output_node` | No | Status finalizer |

## Directory structure

```
prompts/
├── README.md           ← this file
├── analyst/
│   ├── v1.md           ← baseline (current code)
│   └── v2.md           ← ...and so on
└── rag/
    ├── v1.md           ← current state (no LLM, just notes)
    └── v2.md           ← first version with LLM synthesis
```

## Iteration workflow

1. Copy the current node prompt into a new `vN.md` under the node folder.
2. Run at least 5 test cases manually or via `test_analyze.py`.
3. Document failures in the new file before editing the code.
4. Implement the new prompt in `nodes.py`.
5. Save the next version file.
