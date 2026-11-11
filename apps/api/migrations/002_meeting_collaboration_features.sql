-- Simorgh Meet product features required by the On-Premise package:
-- organizational units/groups, permanent rooms, public/private meetings,
-- meeting-level permissions, files, recordings, transcription, AI minutes,
-- action items, calendar feeds, background jobs and audit events.

-- ---------------------------------------------------------------------------
-- Organizational units / groups (واحدها و گروه‌ها)
-- ---------------------------------------------------------------------------
CREATE TABLE organization_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  parent_group_id uuid,
  name varchar(160) NOT NULL,
  kind varchar(20) NOT NULL DEFAULT 'unit'
    CHECK (kind IN ('unit', 'team', 'committee', 'project')),
  status varchar(20) NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT organization_groups_id_org_unique UNIQUE (id, organization_id),
  CONSTRAINT organization_groups_name_unique UNIQUE (organization_id, name),
  CONSTRAINT organization_groups_parent_fk
    FOREIGN KEY (parent_group_id, organization_id)
    REFERENCES organization_groups (id, organization_id)
    ON DELETE SET NULL (parent_group_id)
);

CREATE TABLE organization_group_members (
  organization_id uuid NOT NULL,
  group_id uuid NOT NULL,
  membership_id uuid NOT NULL,
  group_role varchar(20) NOT NULL DEFAULT 'member'
    CHECK (group_role IN ('manager', 'member')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, membership_id),
  CONSTRAINT organization_group_members_group_fk
    FOREIGN KEY (group_id, organization_id)
    REFERENCES organization_groups (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT organization_group_members_membership_fk
    FOREIGN KEY (membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Permanent rooms (اتاق دائمی واحدها و گروه‌ها)
-- ---------------------------------------------------------------------------
CREATE TABLE rooms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  group_id uuid,
  name varchar(160) NOT NULL,
  room_name varchar(160) NOT NULL,
  visibility varchar(16) NOT NULL DEFAULT 'private'
    CHECK (visibility IN ('private', 'internal', 'public')),
  is_permanent boolean NOT NULL DEFAULT true,
  lobby_enabled boolean NOT NULL DEFAULT true,
  guests_allowed boolean NOT NULL DEFAULT false,
  default_recording boolean NOT NULL DEFAULT false,
  default_ai_minutes boolean NOT NULL DEFAULT true,
  status varchar(20) NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived')),
  created_by_membership_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT rooms_id_org_unique UNIQUE (id, organization_id),
  CONSTRAINT rooms_room_name_unique UNIQUE (organization_id, room_name),
  CONSTRAINT rooms_group_fk
    FOREIGN KEY (group_id, organization_id)
    REFERENCES organization_groups (id, organization_id)
    ON DELETE SET NULL (group_id),
  CONSTRAINT rooms_creator_fk
    FOREIGN KEY (created_by_membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id)
    DEFERRABLE INITIALLY DEFERRED
);

-- ---------------------------------------------------------------------------
-- Meeting extensions: visibility, permanent-room link, policies, calendar UID
-- private  = only explicitly invited members/guests
-- internal = any active organization member may join
-- public   = anyone with the link may request to join (lobby still applies)
-- ---------------------------------------------------------------------------
ALTER TABLE meetings
  ADD COLUMN room_id uuid,
  ADD COLUMN visibility varchar(16) NOT NULL DEFAULT 'private'
    CHECK (visibility IN ('private', 'internal', 'public')),
  ADD COLUMN lobby_enabled boolean NOT NULL DEFAULT true,
  ADD COLUMN recording_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN ai_minutes_enabled boolean NOT NULL DEFAULT true,
  ADD COLUMN transcription_language varchar(16) NOT NULL DEFAULT 'fa-IR',
  ADD COLUMN ical_uid varchar(255),
  ADD COLUMN ical_sequence integer NOT NULL DEFAULT 0,
  ADD CONSTRAINT meetings_room_fk
    FOREIGN KEY (room_id, organization_id) REFERENCES rooms (id, organization_id)
    ON DELETE SET NULL (room_id);

CREATE UNIQUE INDEX meetings_ical_uid_unique ON meetings (ical_uid) WHERE ical_uid IS NOT NULL;

-- Fine-grained in-meeting permissions (مدیر جلسه و سطوح دسترسی).
-- Role sets defaults; the JSON allows per-participant overrides such as
-- {"share_screen": true, "share_files": false, "unmute_self": true}.
ALTER TABLE meeting_participants
  ADD COLUMN permissions jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN invited_at timestamptz,
  ADD COLUMN response varchar(16) NOT NULL DEFAULT 'pending'
    CHECK (response IN ('pending', 'accepted', 'declined', 'tentative'));

ALTER TABLE meeting_participants
  ADD CONSTRAINT meeting_participants_id_org_unique UNIQUE (id, organization_id);

-- ---------------------------------------------------------------------------
-- Meeting files (اشتراک فایل)
-- ---------------------------------------------------------------------------
CREATE TABLE meeting_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  uploaded_by_participant_id uuid,
  file_name varchar(255) NOT NULL,
  content_type varchar(160) NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  sha256 char(64) NOT NULL,
  storage_key text NOT NULL,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT meeting_files_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT meeting_files_uploader_fk
    FOREIGN KEY (uploaded_by_participant_id, organization_id)
    REFERENCES meeting_participants (id, organization_id)
    ON DELETE SET NULL (uploaded_by_participant_id)
);

CREATE INDEX meeting_files_meeting_idx ON meeting_files (organization_id, meeting_id);

-- ---------------------------------------------------------------------------
-- Recordings and archive (ضبط و آرشیو جلسات)
-- ---------------------------------------------------------------------------
CREATE TABLE recordings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  provider varchar(32) NOT NULL DEFAULT 'jibri',
  status varchar(20) NOT NULL DEFAULT 'recording'
    CHECK (status IN ('recording', 'processing', 'available', 'failed', 'deleted')),
  started_by_participant_id uuid,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  duration_seconds integer CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
  storage_key text,
  sha256 char(64),
  retention_until timestamptz,
  consent_notice_shown_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT recordings_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT recordings_id_org_unique UNIQUE (id, organization_id),
  CONSTRAINT recordings_times_valid CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE INDEX recordings_meeting_idx ON recordings (organization_id, meeting_id);
CREATE INDEX recordings_retention_idx ON recordings (retention_until) WHERE status = 'available';

-- ---------------------------------------------------------------------------
-- Transcription (STT) — one session per Jigasi/STT connection or offline file
-- ---------------------------------------------------------------------------
CREATE TABLE transcription_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  source varchar(20) NOT NULL
    CHECK (source IN ('live', 'recording', 'upload')),
  provider_session_id varchar(200),
  recording_id uuid,
  engine varchar(64) NOT NULL,
  model varchar(200) NOT NULL,
  language varchar(16) NOT NULL DEFAULT 'fa',
  status varchar(20) NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'completed', 'failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CONSTRAINT transcription_sessions_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT transcription_sessions_recording_fk
    FOREIGN KEY (recording_id, organization_id)
    REFERENCES recordings (id, organization_id)
    ON DELETE SET NULL (recording_id),
  CONSTRAINT transcription_sessions_id_org_unique UNIQUE (id, organization_id),
  CONSTRAINT transcription_sessions_provider_unique UNIQUE (source, provider_session_id)
);

CREATE TABLE transcript_segments (
  id bigserial PRIMARY KEY,
  organization_id uuid NOT NULL,
  session_id uuid NOT NULL,
  participant_id uuid,
  speaker_label varchar(160) NOT NULL,
  provider_participant_id text,
  start_ms bigint NOT NULL CHECK (start_ms >= 0),
  end_ms bigint NOT NULL,
  text text NOT NULL,
  confidence real,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT transcript_segments_session_fk
    FOREIGN KEY (session_id, organization_id)
    REFERENCES transcription_sessions (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT transcript_segments_participant_fk
    FOREIGN KEY (participant_id, organization_id)
    REFERENCES meeting_participants (id, organization_id)
    ON DELETE SET NULL (participant_id),
  CONSTRAINT transcript_segments_times_valid CHECK (end_ms >= start_ms)
);

CREATE INDEX transcript_segments_session_time_idx ON transcript_segments (session_id, start_ms);

-- ---------------------------------------------------------------------------
-- Minutes and action items (صورت‌جلسه و پیگیری اقدامات + تولید خودکار با AI)
-- content JSON schema (version 1):
-- { "title", "summary", "agenda":[...], "discussion":[{"topic","points":[...]}],
--   "decisions":[{"text","owner"}], "action_items":[...], "open_questions":[...],
--   "attendees":[...], "absentees":[...] }
-- ---------------------------------------------------------------------------
CREATE TABLE meeting_minutes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  status varchar(20) NOT NULL DEFAULT 'draft'
    CHECK (status IN ('generating', 'draft', 'in_review', 'approved', 'failed')),
  origin varchar(16) NOT NULL DEFAULT 'ai'
    CHECK (origin IN ('ai', 'manual')),
  language varchar(16) NOT NULL DEFAULT 'fa',
  content jsonb NOT NULL DEFAULT '{}'::jsonb,
  rendered_markdown text,
  transcription_session_id uuid,
  generator_model varchar(200),
  generator_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  approved_by_membership_id uuid,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT meeting_minutes_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT meeting_minutes_session_fk
    FOREIGN KEY (transcription_session_id, organization_id)
    REFERENCES transcription_sessions (id, organization_id)
    ON DELETE SET NULL (transcription_session_id),
  CONSTRAINT meeting_minutes_approver_fk
    FOREIGN KEY (approved_by_membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id)
    ON DELETE SET NULL (approved_by_membership_id),
  CONSTRAINT meeting_minutes_id_org_unique UNIQUE (id, organization_id),
  CONSTRAINT meeting_minutes_version_unique UNIQUE (meeting_id, version)
);

CREATE TABLE action_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  meeting_id uuid NOT NULL,
  minutes_id uuid,
  title varchar(500) NOT NULL,
  description text,
  assignee_membership_id uuid,
  assignee_name varchar(160),
  due_date date,
  priority varchar(10) NOT NULL DEFAULT 'normal'
    CHECK (priority IN ('low', 'normal', 'high')),
  status varchar(20) NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
  origin varchar(16) NOT NULL DEFAULT 'ai'
    CHECK (origin IN ('ai', 'manual')),
  source_quote text,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT action_items_meeting_fk
    FOREIGN KEY (meeting_id, organization_id)
    REFERENCES meetings (id, organization_id) ON DELETE CASCADE,
  CONSTRAINT action_items_minutes_fk
    FOREIGN KEY (minutes_id, organization_id)
    REFERENCES meeting_minutes (id, organization_id) ON DELETE SET NULL (minutes_id),
  CONSTRAINT action_items_assignee_fk
    FOREIGN KEY (assignee_membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id)
    ON DELETE SET NULL (assignee_membership_id)
);

CREATE INDEX action_items_assignee_status_idx
  ON action_items (organization_id, assignee_membership_id, status);
CREATE INDEX action_items_meeting_idx ON action_items (organization_id, meeting_id);

-- Organization vocabulary injected into STT (hotwords) and the minutes prompt:
-- staff names, project names, local/Kermani terms and their standard spelling.
CREATE TABLE organization_glossary_terms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  term varchar(200) NOT NULL,
  normalized varchar(200),
  note varchar(500),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT organization_glossary_terms_unique UNIQUE (organization_id, term)
);

-- ---------------------------------------------------------------------------
-- Calendar integration (اتصال به تقویم): per-user private ICS feed tokens.
-- Only the SHA-256 hash of the feed token is stored.
-- ---------------------------------------------------------------------------
CREATE TABLE calendar_feed_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL,
  membership_id uuid NOT NULL,
  token_hash char(64) NOT NULL UNIQUE,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT calendar_feed_tokens_membership_fk
    FOREIGN KEY (membership_id, organization_id)
    REFERENCES organization_memberships (id, organization_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Background jobs (AI minutes, re-transcription, retention cleanup, email)
-- Workers claim with: SELECT ... FOR UPDATE SKIP LOCKED.
-- ---------------------------------------------------------------------------
CREATE TABLE background_jobs (
  id bigserial PRIMARY KEY,
  organization_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
  kind varchar(64) NOT NULL,
  dedupe_key varchar(255),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status varchar(16) NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  run_after timestamptz NOT NULL DEFAULT now(),
  locked_at timestamptz,
  locked_by varchar(120),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX background_jobs_dedupe_unique
  ON background_jobs (kind, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX background_jobs_claim_idx
  ON background_jobs (kind, run_after) WHERE status = 'queued';

-- ---------------------------------------------------------------------------
-- Audit log
-- ---------------------------------------------------------------------------
CREATE TABLE audit_events (
  id bigserial PRIMARY KEY,
  organization_id uuid REFERENCES organizations(id) ON DELETE SET NULL,
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  actor_kind varchar(16) NOT NULL DEFAULT 'user'
    CHECK (actor_kind IN ('user', 'guest', 'system', 'service')),
  action varchar(120) NOT NULL,
  target_type varchar(64),
  target_id text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_events_org_time_idx ON audit_events (organization_id, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- Attendance report (ثبت حضور و غیاب): totals all join/leave intervals per participant
-- (reconnects add up; overlapping multi-device sessions are not de-duplicated yet).
-- ---------------------------------------------------------------------------
CREATE VIEW meeting_attendance_report AS
SELECT
  p.organization_id,
  p.meeting_id,
  p.id AS participant_id,
  p.participant_type,
  p.role,
  COALESCE(u.display_name, p.display_name) AS display_name,
  COALESCE(u.email, p.email) AS email,
  MIN(s.joined_at) AS first_joined_at,
  MAX(COALESCE(s.left_at, m.actual_ended_at)) AS last_left_at,
  COALESCE(SUM(EXTRACT(EPOCH FROM (COALESCE(s.left_at, m.actual_ended_at, now()) - s.joined_at))), 0)::bigint
    AS attended_seconds,
  COUNT(s.id) AS session_count,
  CASE WHEN COUNT(s.id) = 0 THEN 'absent' ELSE 'present' END AS attendance_status
FROM meeting_participants p
JOIN meetings m ON m.id = p.meeting_id AND m.organization_id = p.organization_id
LEFT JOIN organization_memberships om ON om.id = p.membership_id
LEFT JOIN users u ON u.id = om.user_id
LEFT JOIN attendance_sessions s
  ON s.participant_id = p.id AND s.organization_id = p.organization_id
GROUP BY p.organization_id, p.meeting_id, p.id, p.participant_type, p.role,
  u.display_name, p.display_name, u.email, p.email;
