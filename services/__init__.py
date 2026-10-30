"""Framework-independent CEQ platform services."""

from .genesys_auth import (
    GenesysAuthConfiguration,
    GenesysAuthService,
    GenesysAuthenticationError,
    GenesysConfigurationError,
    GenesysOrganizationError,
    OrganizationInfo,
    TokenOptions,
    TokenResult,
)
from .fingerprint_service import FingerprintIdentifiers, FingerprintResult, FingerprintService, InteractionContext
from .ticket_matching_service import MatchCandidate, PrematchResult, TicketFacts, TicketMatchingService, TicketRow, TicketExportResult
from .ticket_policy_service import KBQuery, TicketPolicyService, VerificationResult

__all__ = [
    "GenesysAuthConfiguration",
    "GenesysAuthService",
    "GenesysAuthenticationError",
    "GenesysConfigurationError",
    "GenesysOrganizationError",
    "OrganizationInfo",
    "TokenOptions",
    "TokenResult",
    "FingerprintIdentifiers",
    "FingerprintResult",
    "FingerprintService",
    "InteractionContext",
    "MatchCandidate",
    "PrematchResult",
    "TicketFacts",
    "TicketMatchingService",
    "TicketRow",
    "TicketExportResult",
    "KBQuery",
    "TicketPolicyService",
    "VerificationResult",
]
