"""App DB SQLAlchemy models.

Importing this package imports every model, registering them on
`app.db.base.Base.metadata` so Alembic autogenerate sees them.
"""

from app.db.models.action_item import (
    ActionItem,
    ActionItemHandler,
    ActionItemStatus,
)
from app.db.models.call import Call, CallStatus
from app.db.models.call_artifact import ArtifactKind, CallArtifact
from app.db.models.claim_verification import ClaimVerification, VerificationStatus
from app.db.models.correction_intake import (
    CorrectionIntake,
    CorrectionIntakeStatus,
    CorrectionOrigin,
)
from app.db.models.dashboard import (
    DashboardDimension,
    DashboardSnapshot,
    SavedDashboardQuery,
)
from app.db.models.decision import (
    DecisionClass,
    DecisionRequest,
    DecisionStatus,
    RespondedVia,
)
from app.db.models.email_message import (
    EmailMessage,
    EmailProviderName,
    EmailRecipientClass,
    EmailTriggerKind,
)
from app.db.models.field_employee import FieldEmployee
from app.db.models.intake import (
    IntakeBufferItem,
    IntakePurpose,
    IntakeSource,
    IntakeStatus,
)
from app.db.models.manager_intervention import InterventionMode, ManagerIntervention
from app.db.models.oauth_credentials import OAuthProvider, WorkspaceOAuthCredentials
from app.db.models.organization import Organization
from app.db.models.provenance import Provenance, SourceType
from app.db.models.refresh_token import RefreshToken
from app.db.models.transcript import Speaker, TranscriptFragment
from app.db.models.user import User, UserRole
from app.db.models.workspace import ManagerWorkspace, ProvisioningState

__all__ = [
    "ActionItem",
    "ActionItemHandler",
    "ActionItemStatus",
    "ArtifactKind",
    "Call",
    "CallArtifact",
    "CallStatus",
    "ClaimVerification",
    "CorrectionIntake",
    "CorrectionIntakeStatus",
    "CorrectionOrigin",
    "DashboardDimension",
    "DashboardSnapshot",
    "DecisionClass",
    "DecisionRequest",
    "DecisionStatus",
    "EmailMessage",
    "EmailProviderName",
    "EmailRecipientClass",
    "EmailTriggerKind",
    "FieldEmployee",
    "IntakeBufferItem",
    "IntakePurpose",
    "IntakeSource",
    "IntakeStatus",
    "InterventionMode",
    "ManagerIntervention",
    "ManagerWorkspace",
    "OAuthProvider",
    "Organization",
    "Provenance",
    "ProvisioningState",
    "RefreshToken",
    "RespondedVia",
    "SavedDashboardQuery",
    "SourceType",
    "Speaker",
    "TranscriptFragment",
    "User",
    "UserRole",
    "VerificationStatus",
    "WorkspaceOAuthCredentials",
]
