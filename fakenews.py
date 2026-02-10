import json
import re
from typing import TypedDict, List, Dict
from flask import Flask, request, jsonify
from flask_cors import CORS

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.messages import SystemMessage, HumanMessage

app_flask = Flask(__name__)
CORS(app_flask)

model = ChatOpenAI(
    model="llama3.1:8b",
    base_url="http://localhost:11434/v1",
    api_key="ollama",
    temperature=0
)

search_tool = DuckDuckGoSearchRun()

def extract_json(text: str):
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("No JSON found")
    return json.loads(match.group())


class VerifyState(TypedDict):
    A: str
    plan: List[str]
    claims: List[str]
    current_index: int
    claim_results: List[Dict]
    legitimacy_percentage: float
    final_verdict: str
    D: str
    final_explanation: str

def plan_claims(state: VerifyState):
    article = state["A"]

    system = SystemMessage(
        content="You are an expert fact-checker. Identify what factual claims SHOULD be verified."
    )
    human = HumanMessage(
        content=(
            "Return a JSON list of factual claim topics that need verification.\n\n"
            "JSON only:\n"
            "{\"plan\": [\"claim topic 1\", \"claim topic 2\"]}\n\n"
            f"Article:\n{article}"
        )
    )

    try:
        response = model.invoke([system, human])
        plan = extract_json(response.content).get("plan", [])
    except:
        plan = []

    return {
        "plan": plan,
        "claims": [],
        "current_index": 0,
        "claim_results": [],
        "legitimacy_percentage": 0.0
    }

def extract_next_claim(state: VerifyState):
    article = state["A"]
    plan = state["plan"]
    extracted = state["claims"]

    system = SystemMessage(
        content="Extract one factual claim at a time. Respond DONE if no new claim remains."
    )

    human = HumanMessage(
        content=(
            f"Planned claim topics:\n{plan}\n\n"
            f"Already extracted claims:\n{extracted}\n\n"
            "Extract the NEXT missing factual claim.\n"
            "Return JSON:\n"
            "{\"claim\": \"...\"} OR {\"done\": true}\n\n"
            f"Article:\n{article}"
        )
    )

    try:
        response = model.invoke([system, human])
        parsed = extract_json(response.content)
    except:
        parsed = {"done": True}

    if parsed.get("done"):
        return {}

    return {
        "claims": extracted + [parsed["claim"]]
    }

def should_extract_more(state: VerifyState):
    if len(state["claims"]) < len(state["plan"]):
        return "extract_next_claim"
    return "verify_claim"

def verify_claim(state: VerifyState):
    idx = state["current_index"]
    claim = state["claims"][idx]

    search_result = search_tool.run(claim)

    system = SystemMessage(
        content="You are a strict fact-checker. Explain clearly WHY a claim is legit or not legit."
    )

    human = HumanMessage(
        content=(
            f"Verify the following claim:\n{claim}\n\n"
            f"Evidence from search results:\n{search_result}\n\n"
            "Return JSON ONLY:\n"
            "{"
            "\"verdict\": \"legit\" or \"not legit\", "
            "\"explanation\": \"A clear, factual explanation referencing the evidence.\""
            "}"
        )
    )


    try:
        response = model.invoke([system, human])
        parsed = extract_json(response.content)
        verdict = parsed.get("verdict", "not legit")
        explanation = parsed.get("explanation", "")
    except:
        verdict = "not legit"
        explanation = "Verification failed."

    return {
        "claim_results": state["claim_results"] + [
            {"claim": claim, "verdict": verdict, "explanation": explanation}
        ],
        "current_index": idx + 1
    }

def should_continue_verification(state: VerifyState):
    if state["current_index"] < len(state["claims"]):
        return "verify_claim"
    return "compute_score"

def compute_score(state: VerifyState):
    results = state["claim_results"]

    if not results:
        return {"legitimacy_percentage": 0.0, "final_verdict": "Fake", "D": "Fake"}

    legit_count = sum(1 for r in results if r["verdict"] == "legit")
    percentage = (legit_count / len(results)) * 100
    verdict = "Verified" if percentage >= 60 else "Unverified"

    return {
        "legitimacy_percentage": round(percentage, 2),
        "final_verdict": verdict,
        "D": verdict
    }


def final_explanation(state: VerifyState):
    formatted = []

    for r in state["claim_results"]:
        if r["verdict"] == "not legit":
            formatted.append(
                f"❌ Claim: {r['claim']}\n"
                f"Why it is not legit:\n{r['explanation']}\n"
            )
        else:
            formatted.append(
                f"✅ Claim: {r['claim']}\n"
                f"Why it is legit:\n{r['explanation']}\n"
            )

    return {
        "final_explanation": "\n".join(formatted)
    }



builder = StateGraph(VerifyState)

builder.add_node("plan_claims", plan_claims)
builder.add_node("extract_next_claim", extract_next_claim)
builder.add_node("verify_claim", verify_claim)
builder.add_node("compute_score", compute_score)
builder.add_node("final_explanation", final_explanation)

builder.set_entry_point("plan_claims")

builder.add_edge("plan_claims", "extract_next_claim")

builder.add_conditional_edges(
    "extract_next_claim",
    should_extract_more,
    {
        "extract_next_claim": "extract_next_claim",
        "verify_claim": "verify_claim"
    }
)

builder.add_conditional_edges(
    "verify_claim",
    should_continue_verification,
    {
        "verify_claim": "verify_claim",
        "compute_score": "compute_score"
    }
)

builder.add_edge("compute_score", "final_explanation")
builder.add_edge("final_explanation", END)

graph_app = builder.compile()

@app_flask.route("/predict", methods=["POST"])
def predict():
    data = request.get_json(force=True)
    header = data.get("header", "")
    body = data.get("body", "")
    content = f"{header}\n{body}"

    result = graph_app.invoke({"A": content})

    return jsonify({
        "label": result.get("D", ""),
        "percentage": result.get("legitimacy_percentage", 0),
        "explanation": result.get("final_explanation", "")
    })

if __name__ == "__main__":
    app_flask.run(host="0.0.0.0", port=5000, debug=True)