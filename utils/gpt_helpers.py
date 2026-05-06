import os

from providers.completion import get_completion_provider
from utils.logging import (
    log_operation,
    log_timing,
    log_errors,
    portfolio_logger,
)

DEFAULT_OPENAI_PEERS_MODEL = "gpt-5.4-mini"
_EPHEMERAL_CACHE_CONTROL = {"type": "ephemeral"}
_PEER_GENERATION_SYSTEM_PROMPT = """
You are a fundamental equity analyst.
Given stock details, return 5-10 peer tickers that best represent the stock's
subindustry or closest competitive group, ideally companies that compete with
or operate in similar business models.

Only include currently publicly listed equities from the U.S., Canada, or U.K.
Do not include companies that have been acquired, merged, or delisted.

Return a clean Python list of tickers, no explanation.

Example Input:

Ticker: NVDA
Name: NVIDIA Corporation
Industry: Semiconductors

Expected Output:

["AMD", "INTC", "AVGO", "QCOM", "TSM", "MRVL", "TXN"]
""".strip()


class PeerGenerationLLMError(RuntimeError):
    """Raised when the LLM peer-generation backend cannot produce a response."""

_ASSET_CLASSIFICATION_SYSTEM_PROMPT = """
You are a financial asset classification expert.
Classify securities into exactly one of these asset classes: equity, bond,
real_estate, commodity, crypto, cash, mixed, unknown.

Focus on the investment exposure, not the legal structure. For example:
- A bond fund should be classified as "bond"
- A REIT or real estate fund should be classified as "real_estate"
- A mining company or fund (gold, silver, copper, etc.) should be classified as "commodity"
- A cryptocurrency fund or crypto-themed ETF should be classified as "crypto"
- A regular stock should be classified as "equity"
- A money market or ultra-short-term bond fund should be classified as "cash"
- A multi-asset fund should be classified as "mixed"
- If unclear or insufficient information, use "unknown"

Respond in this exact format: "asset_class,confidence_score"
Where confidence_score is between 0.00 and 1.00
Return only that one line. Do not include explanation, prose, Markdown, code fences, or extra text.

Examples:
- "bond,0.95" for a bond fund
- "equity,0.85" for a regular stock
- "real_estate,0.90" for a REIT or real estate fund
- "commodity,0.80" for a mining company or mining fund
- "crypto,0.90" for a cryptocurrency fund or crypto-themed ETF
- "cash,0.95" for a money market or ultra-short-term bond fund
- "mixed,0.75" for a target-date fund
- "unknown,0.30" if insufficient information
""".strip()


def _resolve_peers_model(provider) -> str | None:
    model_override = os.getenv("LLM_PEERS_MODEL", "").strip()
    if model_override:
        return model_override

    if str(getattr(provider, "provider_name", "")).strip().lower() == "openai":
        return DEFAULT_OPENAI_PEERS_MODEL

    return None


@log_errors("high")
@log_operation("ai_interpretation")
@log_timing(3.0)
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
        "I want you to help interpret them for me and communicate with me in simple language.\n"
        "Start your response with 'Let's break down your portfolio's risk profile'...\n\n"
        f"{diagnostics_text}"
    )

    provider = get_completion_provider()
    if provider is None:
        return "(AI interpretation unavailable)"

    return provider.complete(
        user_prompt,
        system="You are a portfolio risk analysis expert.",
        model=os.getenv("LLM_INTERPRETATION_MODEL") or None,
        max_tokens=2000,
        temperature=0.5,
        cache_control=_EPHEMERAL_CACHE_CONTROL,
    )

# ── Peer-generator helper ─────────────────────────────────────────────
@log_errors("high")
def generate_subindustry_peers(
    ticker: str,
    name: str,
    industry: str,
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
    max_tokens : int, default=200
        Max token count for the GPT response.
    temperature : float, default=0.2
        Sampling temperature (lower → more deterministic).

    Returns
    -------
    str
        The raw GPT response content as a string (still needs `ast.literal_eval()` parsing).

    Notes
    -----
    • This function does **not** parse the GPT output into a Python list. That is handled downstream.
    • The model is instructed to return only a Python list of valid, public tickers from the U.S., U.K., or Canada.
    • Provider and API failures raise PeerGenerationLLMError; callers should not treat them as empty peers.

    Example Output
    --------------
    '["AMD", "INTC", "AVGO", "QCOM", "TSM", "MRVL", "TXN"]'
    """
    prompt = f"""
Ticker: {ticker}
Name: {name}
Industry: {industry}
""".strip()

    provider = get_completion_provider()
    if provider is None:
        raise PeerGenerationLLMError("No completion provider configured for subindustry peer generation")

    try:
        content = provider.complete(
            prompt,
            system=_PEER_GENERATION_SYSTEM_PROMPT,
            model=_resolve_peers_model(provider),
            max_tokens=max_tokens,
            temperature=temperature,
            cache_control=_EPHEMERAL_CACHE_CONTROL,
        )

        # Expect something like ["AMD", "INTC", "QCOM", ...]
        if not isinstance(content, str) or not content.strip():
            raise PeerGenerationLLMError(f"Empty subindustry peer LLM response for {ticker}")

        return content

    except Exception as e:
        # Log full traceback so the root cause is visible
        portfolio_logger.error(f"⚠️ generate_subindustry_peers failed for {ticker}: {e}")
        portfolio_logger.debug(f"generate_subindustry_peers traceback for {ticker}", exc_info=True)
        raise PeerGenerationLLMError(f"Subindustry peer LLM call failed for {ticker}") from e


@log_errors("high")
@log_operation("ai_asset_classification")
@log_timing(3.0)
def generate_asset_class_classification(ticker: str, company_name: str, description: str, timeout: int = 30) -> str:
    """
    GPT function for asset class classification (follows generate_subindustry_peers pattern)
    
    Args:
        ticker: Stock symbol (e.g., "DSU")
        company_name: Company name from FMP (e.g., "BlackRock Debt Strategies Fund, Inc.")
        description: Company description from FMP profile
        timeout: Request timeout in seconds
        
    Returns:
        String in format "asset_class,confidence_score" (e.g., "bond,0.95")
        FALLBACK: Returns "mixed,0.50" if GPT API fails (timeout, error, etc.)
        
    Fallback Behavior:
        - GPT API failure → "mixed,0.50" (safe default for unknown securities)
        - Maintains consistent return format even on error
        - Caller can parse and handle low confidence appropriately
        - "mixed" is safest assumption for unclassifiable securities
        
    Prompt Strategy:
        - Clear 8-category classification (equity, bond, real_estate, commodity, crypto, cash, mixed, unknown)
        - Focus on investment exposure, not legal structure
        - Return format: "asset_class,confidence_score"
        - Confidence range: 0.00-1.00
    """
    prompt = f"""
Security: {ticker}
Company: {company_name}
Description: {description}

Return only the exact classification string, no explanation.
""".strip()

    provider = get_completion_provider()
    if provider is None:
        return "mixed,0.50"

    try:
        content = provider.complete(
            prompt,
            system=_ASSET_CLASSIFICATION_SYSTEM_PROMPT,
            model=os.getenv("LLM_CLASSIFICATION_MODEL") or None,
            max_tokens=50,  # Short response expected
            temperature=0.2,  # Low temperature for consistent classification
            timeout=timeout,
            cache_control=_EPHEMERAL_CACHE_CONTROL,
        )
        portfolio_logger.debug(f"GPT asset class response for {ticker}: {content}")
        return content

    except Exception as e:
        # Log full traceback for debugging
        portfolio_logger.error(f"GPT asset class classification failed for {ticker}: {e}")
        portfolio_logger.debug(f"GPT asset class classification traceback for {ticker}", exc_info=True)
        return "mixed,0.50"  # Return structured response format even on error
