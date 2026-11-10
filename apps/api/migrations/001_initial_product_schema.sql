CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(160) NOT NULL,
  slug varchar(80) NOT NULL UNIQUE,
  status varchar(20) NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'suspended', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  identity_issuer text NOT NULL,
  identity_subject text NOT NULL,
  email varchar(320),
  display_name varchar(160),
  status varchar(20) NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'disabled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT users_identity_unique UNIQUE (identity_issuer, identity_subject)
);

CREATE UNIQUE INDEX users_email_lower_unique
  ON users (lower(email))
  WHERE email IS NOT NULL;

CREATE TABLE organization_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role varchar(24) NOT NULL
    CHECK (role IN ('owner', 'admin', 'member')),
  status varchar(20) NOT NULL DEFAULT 'active'
    CHECK (status IN ('invited', 'active', 'suspended', 'removed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT organization_memberships_unique UNIQUE (organization_id, user_id),
  CONSTRAINT organization_memberships_id_org_unique UNIQUE (id, organization_id)
);

CREATE INDEX organization_memberships_user_status_idx
  ON organization_memberships (user_id, status);

CREATE TABLE meetings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  created_by_membership_id uuid NOT NULL,
  title varchar(200) NOT NULL,
  description text,
  status varchar(20) NOT NULL DEFAULT 'scheduled'
    CHECK (status IN ('scheduled', 'active', 'ended', 'cancelled')),
  scheduled_start_at timestamptz,
  scheduled_end_at timestamptz,
  actual_started_at timestamptz,
  actual_ended_at timestamptz,
  timezone varchar(80),
  room_name varchar(160) NOT NULL,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT meetings_creator_membership_fk
    FOREIGN KEY (created_by_membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id),
  CONSTRAINT meetings_schedule_valid
    CHECK (
      scheduled_end_at IS NULL OR scheduled_start_at IS NULL
      OR scheduled_end_at > scheduled_start_at
    ),
  CONSTRAINT meetings_actual_times_valid
    CHECK (
      actual_ended_at IS NULL OR actual_started_at IS NULL
      OR actual_ended_at >= actual_started_at
    ),
  CONSTRAINT meetings_room_unique_per_org UNIQUE (organization_id, room_name),
  CONSTRAINT meetings_id_org_unique UNIQUE (id, organization_id)
);

CREATE INDEX meetings_org_status_start_idx
  ON meetings (organization_id, status, scheduled_start_at);

CREATE TABLE meeting_participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  membership_id uuid,
  participant_type varchar(16) NOT NULL
    CHECK (participant_type IN ('member', 'guest')),
  role varchar(20) NOT NULL DEFAULT 'participant'
    CHECK (role IN ('host', 'moderator', 'participant', 'guest')),
  display_name varchar(160),
  email varchar(320),
  joined_at timestamptz,
  left_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT meeting_participants_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT meeting_participants_membership_fk
    FOREIGN KEY (membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id),
  CONSTRAINT meeting_participant_identity_valid
    CHECK (
      (participant_type = 'member' AND membership_id IS NOT NULL)
      OR (participant_type = 'guest' AND membership_id IS NULL)
    ),
  CONSTRAINT meeting_participant_times_valid
    CHECK (left_at IS NULL OR joined_at IS NULL OR left_at >= joined_at)
);

CREATE UNIQUE INDEX meeting_participants_member_unique
  ON meeting_participants (meeting_id, membership_id)
  WHERE membership_id IS NOT NULL;

CREATE INDEX meeting_participants_meeting_idx
  ON meeting_participants (organization_id, meeting_id);

CREATE TABLE guest_invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  created_by_membership_id uuid NOT NULL,
  token_hash char(64) NOT NULL UNIQUE,
  email varchar(320),
  expires_at timestamptz NOT NULL,
  redeemed_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT guest_invitations_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT guest_invitations_creator_fk
    FOREIGN KEY (created_by_membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id),
  CONSTRAINT guest_invitations_expiry_valid CHECK (expires_at > created_at)
);

CREATE INDEX guest_invitations_meeting_idx
  ON guest_invitations (organization_id, meeting_id);

CREATE TABLE attendance_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  participant_id uuid NOT NULL REFERENCES meeting_participants(id) ON DELETE CASCADE,
  provider_participant_id text NOT NULL,
  joined_at timestamptz NOT NULL,
  left_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT attendance_sessions_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT attendance_session_times_valid CHECK (left_at IS NULL OR left_at >= joined_at)
);

CREATE INDEX attendance_sessions_meeting_time_idx
  ON attendance_sessions (organization_id, meeting_id, joined_at);

CREATE INDEX attendance_sessions_open_idx
  ON attendance_sessions (meeting_id, participant_id)
  WHERE left_at IS NULL;

CREATE TABLE media_provider_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  provider varchar(32) NOT NULL,
  provider_event_id varchar(200) NOT NULL,
  event_type varchar(80) NOT NULL,
  occurred_at timestamptz,
  received_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL,
  CONSTRAINT media_provider_events_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT media_provider_events_dedupe UNIQUE (provider, provider_event_id)
);

CREATE INDEX media_provider_events_meeting_received_idx
  ON media_provider_events (organization_id, meeting_id, received_at);
