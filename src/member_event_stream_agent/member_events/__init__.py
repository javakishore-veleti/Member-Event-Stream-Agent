"""member_events — Kafka consumer / producer, event schemas, and normalizer.

Ingests events from every payer source system (eligibility / claims / PBM /
ADT / lab vendors / care management platform) into a unified MemberEvent
envelope. Normalization handles late-arriving claims, multi-source dedup, and
schema-evolution-friendly attribute preservation.
"""
