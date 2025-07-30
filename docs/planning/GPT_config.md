Ah good point! Let's find all the places in your codebase that use GPT so you can apply the new `gpt_enabled()` configuration consistently.
Ran tool
Search files...

**Great catch!** You're absolutely right - there are **multiple GPT usage points** throughout your codebase. Let me identify all the places that should use your new `gpt_enabled()` configuration:

## **🎯 GPT Usage Areas Found:**

### **✅ Already Configured:**
1. **`services/factor_proxy_service.py`** - Sub-industry peer generation (already uses `gpt_enabled()`)

### **❌ Need Configuration Updates:**

2. **`gpt_helpers.py`** - Core GPT functions:
   - `interpret_portfolio_risk()` - Portfolio interpretation 
   - `generate_subindustry_peers()` - Peer generation

3. **`routes/api.py`** - API endpoints:
   - `/api/portfolio_analysis_gpt` endpoint
   - Direct calls to `interpret_portfolio_risk()`

4. **`core/interpretation.py`** - Business logic:
   - `analyze_and_interpret()` function

5. **`run_risk.py`** - CLI interface:
   - `run_and_interpret()` function  

6. **`proxy_builder.py`** - Proxy generation:
   - `get_subindustry_peers_from_ticker()` function

## **🔧 Recommended Updates:**

Want me to help you update these files to use your centralized `gpt_enabled()` configuration? This would give you **one environment variable** (`USE_GPT_SUBINDUSTRY`) to control **all GPT usage** across your system.

**Priority order**:
1. `gpt_helpers.py` (core functions)
2. `proxy_builder.py` (direct GPT calls)  
3. API routes and CLI interfaces

Should we start with updating `gpt_helpers.py` since that's where the core GPT functions live? 🎯