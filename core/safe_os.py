"""
safe_os.py — SAFE OS Core Schema
Defines DomainConfig and CulturalPrinciple dataclasses.
These are the base building blocks for all SAFE OS domain extensions.

Architecture:
  Tier 1: Preservation-Focused  — archive, memory, carrying the dead alongside the living
  Tier 2: Verification-Focused  — material anchoring, narrative testimony, contradiction handling
  Tier 3: Reflexive/Meta-Aware  — bias tracking, funding disclosure, self-audit layer

Governance: All entity additions, relationship locks, and contradiction resolutions
require human ratification (Dual Commit). AI retrieves; humans approve.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class CulturalPrinciple:
    """
    Defines how the AI behaves culturally within a domain.
    Applied during conversation to trigger context-aware responses.
    """
    name: str
    description: str
    examples: List[str] = field(default_factory=list)
    application_rules: List[str] = field(default_factory=list)

    def applies_to(self, context: str) -> bool:
        """Check if this principle applies to a given conversation context."""
        context_lower = context.lower()
        return any(ex.lower() in context_lower for ex in self.examples)

    def __repr__(self):
        return f"CulturalPrinciple(name={self.name\!r}, rules={len(self.application_rules)})"


@dataclass
class DomainConfig:
    """
    Configuration for a SAFE OS domain extension.
    One config per tier (Preservation / Verification / Reflexive).
    """
    domain_name: str
    entity_types: List[str] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    pre_training_sources: List[str] = field(default_factory=list)
    tier: str = "preservation"  # "preservation" | "verification" | "reflexive"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    # Governance — tasks AI can do automatically vs. require human ratification
    auto_permitted: List[str] = field(default_factory=list)
    requires_ratification: List[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "domain": self.domain_name,
            "tier": self.tier,
            "entities": len(self.entity_types),
            "relationships": len(self.relationships),
            "hooks": len(self.hooks),
            "sources": len(self.pre_training_sources),
        }

    def __repr__(self):
        return f"DomainConfig(domain={self.domain_name\!r}, tier={self.tier\!r}, entities={len(self.entity_types)})"


@dataclass
class SAFEOSExtension:
    """
    A complete SAFE OS domain extension — all three tiers bundled.
    This is the canonical unit for registering a new domain.
    """
    domain_name: str
    tier1_preservation: Optional[DomainConfig] = None
    tier2_verification: Optional[DomainConfig] = None
    tier3_reflexive: Optional[DomainConfig] = None
    principles: List[CulturalPrinciple] = field(default_factory=list)
    version: str = "1.0"
    ratified_by: Optional[str] = None  # Human approver
    ratified_at: Optional[str] = None

    def is_ratified(self) -> bool:
        return self.ratified_by is not None

    def tiers_configured(self) -> List[str]:
        tiers = []
        if self.tier1_preservation: tiers.append("preservation")
        if self.tier2_verification: tiers.append("verification")
        if self.tier3_reflexive: tiers.append("reflexive")
        return tiers

    def summary(self) -> dict:
        return {
            "domain": self.domain_name,
            "version": self.version,
            "tiers": self.tiers_configured(),
            "principles": [p.name for p in self.principles],
            "ratified": self.is_ratified(),
            "ratified_by": self.ratified_by,
        }
