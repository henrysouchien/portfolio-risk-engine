#!/usr/bin/env python
# coding: utf-8

# In[ ]:


# === OPENAI API Setup ===
import openai
from io import StringIO
from contextlib import redirect_stdout
from dotenv import load_dotenv
import os

load_dotenv()  # This loads variables from .env into the environment

# Now access your keys like this
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Import logging decorators for GPT API operations
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling,
    log_api_health,
    log_service_health,
    log_critical_alert
)


# In[ ]:


# File: gpt_helpers.py

@log_error_handling("high")
@log_portfolio_operation_decorator("ai_interpretation")
@log_api_health("OpenAI", "chat_completions")
@log_performance(3.0)
def interpret_portfolio_risk(diagnostics_text: str) -> str:
    """
    Sends raw printed diagnostics to GPT for layman interpretation.
    """
    # LOGGING: Add OpenAI API request logging and timing here
    # LOGGING: Add service health monitoring for OpenAI API here
    # LOGGING: Add critical alert for OpenAI API failures here

    # LOGGING: Add OpenAI response logging with token usage here
    # LOGGING: Add service health logging for OpenAI API response here
    user_prompt = (
        "You are a professional risk analyst at a hedge fund.\n"
        "I want you to help evaluate my portfolio. I will give you details of the portfolio's risk metrics.\n"
        "I want you to help interpret them for me and communicate with me in simple language.\n\n"
        f"{diagnostics_text}"
    )

    response = client.chat.completions.create(
        model="gpt-4.1",  # or "gpt-4o-mini" if desired
        messages=[
            {"role": "system", "content": "You are a portfolio risk analysis expert."},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=2000,
        temperature=0.5
    )
    # LOGGING: Add OpenAI response logging with token usage here

    return response.choices[0].message.content.strip()


# In[ ]:


# File: gpt_helpers.py

import os
from typing import List
from dotenv import load_dotenv
import openai
import traceback

# ── Load env & set up the shared client ───────────────────────────────
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# ── Peer-generator helper ─────────────────────────────────────────────
@log_error_handling("high")
def generate_subindustry_peers(
    ticker: str,
    name: str,
    industry: str,
    model: str = "gpt-4.1",    # any available chat model
    max_tokens: int = 200,
    temperature: float = 0.2,
) -> str:
    """
    Uses GPT to generate a peer group of subindustry tickers for a given stock.

    Given a stock's ticker, name, and industry, this function sends a structured
    prompt to the OpenAI ChatCompletion API and expects a response in the form of 
    a Python list of tickers (strings). The peers are intended to reflect companies 
    with similar business models or competitive positioning.

    Parameters
    ----------
    ticker : str
        The stock symbol to generate peers for (e.g., "NVDA").
    name : str
        The full company name (e.g., "NVIDIA Corporation").
    industry : str
        Broad industry classification (e.g., "Semiconductors").
    model : str, default="gpt-4.1"
        The OpenAI chat model to use.
    max_tokens : int, default=200
        Max token count for the GPT response.
    temperature : float, default=0.2
        Sampling temperature (lower → more deterministic).

    Returns
    -------
    str
        The raw GPT response content as a string (still needs `ast.literal_eval()` parsing).
        Returns an empty string on error or if the model response is malformed.

    Notes
    -----
    • This function does **not** parse the GPT output into a Python list. That is handled downstream.
    • The model is instructed to return only a Python list of valid, public tickers from the U.S., U.K., or Canada.
    • Failures (API issues, unexpected formats) return an empty string and print full stack trace.

    Example Output
    --------------
    '["AMD", "INTC", "AVGO", "QCOM", "TSM", "MRVL", "TXN"]'
    """
    prompt = f"""
You’re a fundamental equity analyst.
Given the following stock details, return 5–10 peer tickers that best
represent its subindustry or closest competitive group — ideally companies
that compete with or operate in similar business models.

Only include **currently publicly listed** equities from the U.S., Canada,
or U.K.  

Do not include companies that have been acquired, merged, or
delisted.  

Return a clean list of tickers, no explanation.

⸻

Example Input:

Ticker: NVDA
Name: NVIDIA Corporation
Industry: Semiconductors

⸻

Expected Output:

["AMD", "INTC", "AVGO", "QCOM", "TSM", "MRVL", "TXN"]
⸻

Do for this:

Ticker: {ticker}
Name: {name}
Industry: {industry}
""".strip()

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        content = resp.choices[0].message.content.strip()

        # Expect something like ["AMD", "INTC", "QCOM", ...]
        return content 

    except Exception as e:
        # Log full traceback so the root cause is visible
        print(f"⚠️ generate_subindustry_peers failed for {ticker}: {e}")
        traceback.print_exc()
        return ""


