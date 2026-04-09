"""payer_api — FastAPI surface for clinical and operational staff.

Endpoints serve member lookup, panel views, cohort queries, case file reads,
HEDIS gap reporting, and the standard /healthz + /version. Every endpoint
runs through PHI-redaction-aware response shaping.
"""
