"""care_decisioning — multi-agent pipeline that turns events into dispositions.

Triage classifies the event family. Enrichment loads the longitudinal member
context from member_record. Scoring runs the rule + LLM hybrid that produces
a RiskScore with grounded citations. Recommendation maps the score to a
Disposition (notify_care_manager / open_outreach / queue_pa_review /
propose_intervention / escalate_fwa / draft_pa_response / none). Every run
writes a CaseFile for HIPAA-grade audit.
"""
