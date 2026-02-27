"""
Core package for risk module data objects and exceptions.

Factor intelligence helpers are available via `core.factor_intelligence` directly.
Convenience re-exports were removed to break a circular import chain:
  data_loader → settings → utils/security_type_mappings → inputs → core/__init__
  → core/factor_intelligence → data_loader (partially loaded)
"""
