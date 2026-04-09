"""member_record — longitudinal Member 360 backed by MongoDB.

Persistence for Member, Encounter, ClaimLine, MedicationFill, LabResult,
RiskScore, Disposition, and CaseFile. Manages indexes (member_id + ts
compound), tenant isolation by payer_org_id, and PHI-safe accessors. All
reads and writes go through this module — no other code should touch
pymongo directly.
"""
