-- ===================================================================
-- COMPLETE ECS FC DATABASE UPGRADE SCRIPT
-- Safe to run multiple times - all operations use IF NOT EXISTS/IF EXISTS checks
-- ===================================================================

-- ===================================================================
-- ECS FC MATCHES TABLE
-- ===================================================================

-- Create the main ECS FC matches table
CREATE TABLE IF NOT EXISTS ecs_fc_matches (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES team(id) ON DELETE CASCADE,
    opponent_name VARCHAR(255) NOT NULL,
    match_date DATE NOT NULL,
    match_time TIME NOT NULL,
    location VARCHAR(500) NOT NULL,
    field_name VARCHAR(255),
    is_home_match BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    
    -- Match status and results
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
    home_score INTEGER,
    away_score INTEGER,
    
    -- Metadata and tracking
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- RSVP related
    rsvp_deadline TIMESTAMP WITHOUT TIME ZONE,
    rsvp_reminder_sent BOOLEAN NOT NULL DEFAULT FALSE
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_ecs_fc_matches_team_id ON ecs_fc_matches(team_id);
CREATE INDEX IF NOT EXISTS idx_ecs_fc_matches_date ON ecs_fc_matches(match_date);
CREATE INDEX IF NOT EXISTS idx_ecs_fc_matches_status ON ecs_fc_matches(status);
CREATE INDEX IF NOT EXISTS idx_ecs_fc_matches_team_date ON ecs_fc_matches(team_id, match_date);

-- Add check constraints (safe if already exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'chk_ecs_fc_matches_status' 
        AND table_name = 'ecs_fc_matches'
    ) THEN
        ALTER TABLE ecs_fc_matches ADD CONSTRAINT chk_ecs_fc_matches_status 
        CHECK (status IN ('SCHEDULED', 'COMPLETED', 'CANCELLED'));
    END IF;
END $$;

-- ===================================================================
-- ECS FC AVAILABILITY TABLE
-- ===================================================================

-- Create the ECS FC availability table for RSVP functionality
CREATE TABLE IF NOT EXISTS ecs_fc_availability (
    id SERIAL PRIMARY KEY,
    ecs_fc_match_id INTEGER NOT NULL REFERENCES ecs_fc_matches(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES player(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    discord_id VARCHAR(50),
    
    -- RSVP response
    response VARCHAR(10),
    response_time TIMESTAMP WITHOUT TIME ZONE,
    
    -- Additional info
    notes TEXT,
    
    -- Tracking
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Unique constraint to prevent duplicate responses
    CONSTRAINT uq_ecs_fc_availability_match_player UNIQUE (ecs_fc_match_id, player_id)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_ecs_fc_availability_match_id ON ecs_fc_availability(ecs_fc_match_id);
CREATE INDEX IF NOT EXISTS idx_ecs_fc_availability_player_id ON ecs_fc_availability(player_id);
CREATE INDEX IF NOT EXISTS idx_ecs_fc_availability_response ON ecs_fc_availability(response);

-- Add check constraints (safe if already exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'chk_ecs_fc_availability_response' 
        AND table_name = 'ecs_fc_availability'
    ) THEN
        ALTER TABLE ecs_fc_availability ADD CONSTRAINT chk_ecs_fc_availability_response 
        CHECK (response IS NULL OR response IN ('yes', 'no', 'maybe'));
    END IF;
END $$;

-- ===================================================================
-- ECS FC SCHEDULE TEMPLATES TABLE
-- ===================================================================

-- Create the schedule templates table for reusable schedules
CREATE TABLE IF NOT EXISTS ecs_fc_schedule_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    team_id INTEGER NOT NULL REFERENCES team(id) ON DELETE CASCADE,
    description TEXT,
    
    -- Template data stored as JSON
    template_data JSONB NOT NULL,
    
    -- Metadata
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_ecs_fc_schedule_templates_team_id ON ecs_fc_schedule_templates(team_id);
CREATE INDEX IF NOT EXISTS idx_ecs_fc_schedule_templates_active ON ecs_fc_schedule_templates(is_active);

-- ===================================================================
-- EXISTING TABLE MODIFICATIONS (NON-BREAKING)
-- ===================================================================

-- Add match type column to existing matches table to distinguish ECS FC matches
ALTER TABLE matches ADD COLUMN IF NOT EXISTS match_type VARCHAR(20) DEFAULT 'LEAGUE';

-- Add external opponent support to existing matches table
ALTER TABLE matches ADD COLUMN IF NOT EXISTS external_opponent_name VARCHAR(255);
ALTER TABLE matches ADD COLUMN IF NOT EXISTS external_match BOOLEAN DEFAULT FALSE;

-- Add ECS FC match reference to existing availability table
ALTER TABLE availability ADD COLUMN IF NOT EXISTS ecs_fc_match_id INTEGER REFERENCES ecs_fc_matches(id);

-- Enhance scheduled_message table for ECS FC support (correct table name)
ALTER TABLE scheduled_message ADD COLUMN IF NOT EXISTS message_type VARCHAR(50) DEFAULT 'standard';
ALTER TABLE scheduled_message ADD COLUMN IF NOT EXISTS message_metadata JSONB;
ALTER TABLE scheduled_message ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id);
ALTER TABLE scheduled_message ADD COLUMN IF NOT EXISTS last_send_attempt TIMESTAMP;
ALTER TABLE scheduled_message ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP;
ALTER TABLE scheduled_message ADD COLUMN IF NOT EXISTS send_error VARCHAR(255);
ALTER TABLE scheduled_message ADD COLUMN IF NOT EXISTS task_name VARCHAR(255);

-- Make match_id nullable for ECS FC support (safe operation)
DO $$
BEGIN
    -- Check if the column has NOT NULL constraint
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'scheduled_message' 
        AND column_name = 'match_id' 
        AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE scheduled_message ALTER COLUMN match_id DROP NOT NULL;
    END IF;
END $$;

-- Add check constraint for match type (safe if already exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'chk_matches_match_type' 
        AND table_name = 'matches'
    ) THEN
        ALTER TABLE matches ADD CONSTRAINT chk_matches_match_type 
        CHECK (match_type IN ('LEAGUE', 'ECS_FC', 'FRIENDLY'));
    END IF;
END $$;

-- ===================================================================
-- FUNCTIONS AND TRIGGERS
-- ===================================================================

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for automatic timestamp updates (safe to create multiple times)
DROP TRIGGER IF EXISTS update_ecs_fc_matches_updated_at ON ecs_fc_matches;
CREATE TRIGGER update_ecs_fc_matches_updated_at 
    BEFORE UPDATE ON ecs_fc_matches 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_ecs_fc_availability_updated_at ON ecs_fc_availability;
CREATE TRIGGER update_ecs_fc_availability_updated_at 
    BEFORE UPDATE ON ecs_fc_availability 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_ecs_fc_schedule_templates_updated_at ON ecs_fc_schedule_templates;
CREATE TRIGGER update_ecs_fc_schedule_templates_updated_at 
    BEFORE UPDATE ON ecs_fc_schedule_templates 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- ===================================================================
-- OWNERSHIP AND PERMISSIONS
-- ===================================================================

-- Change ownership of ECS FC tables to ecs-admin
DO $$
BEGIN
    -- Only attempt to change ownership if the role exists
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ecs-admin') THEN
        -- ECS FC Tables
        ALTER TABLE ecs_fc_matches OWNER TO "ecs-admin";
        ALTER TABLE ecs_fc_availability OWNER TO "ecs-admin";
        ALTER TABLE ecs_fc_schedule_templates OWNER TO "ecs-admin";
        
        -- ECS FC Sequences
        ALTER SEQUENCE ecs_fc_matches_id_seq OWNER TO "ecs-admin";
        ALTER SEQUENCE ecs_fc_availability_id_seq OWNER TO "ecs-admin";
        ALTER SEQUENCE ecs_fc_schedule_templates_id_seq OWNER TO "ecs-admin";
        
        -- Enhanced scheduled_message table
        ALTER TABLE scheduled_message OWNER TO "ecs-admin";
        
        -- Grant necessary permissions
        GRANT ALL PRIVILEGES ON TABLE ecs_fc_matches TO "ecs-admin";
        GRANT ALL PRIVILEGES ON TABLE ecs_fc_availability TO "ecs-admin";
        GRANT ALL PRIVILEGES ON TABLE ecs_fc_schedule_templates TO "ecs-admin";
        GRANT ALL PRIVILEGES ON TABLE scheduled_message TO "ecs-admin";
        GRANT ALL PRIVILEGES ON SEQUENCE ecs_fc_matches_id_seq TO "ecs-admin";
        GRANT ALL PRIVILEGES ON SEQUENCE ecs_fc_availability_id_seq TO "ecs-admin";
        GRANT ALL PRIVILEGES ON SEQUENCE ecs_fc_schedule_templates_id_seq TO "ecs-admin";
        
        RAISE NOTICE 'Successfully set ownership to ecs-admin for all ECS FC tables and sequences';
    ELSE
        RAISE NOTICE 'Role ecs-admin does not exist, skipping ownership changes';
    END IF;
END $$;

-- ===================================================================
-- SUMMARY
-- ===================================================================

-- Display completion message
DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'ECS FC DATABASE UPGRADE COMPLETED SUCCESSFULLY';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Tables created/verified:';
    RAISE NOTICE '- ecs_fc_matches (with indexes and constraints)';
    RAISE NOTICE '- ecs_fc_availability (with indexes and constraints)';
    RAISE NOTICE '- ecs_fc_schedule_templates (with indexes)';
    RAISE NOTICE '';
    RAISE NOTICE 'Table modifications completed:';
    RAISE NOTICE '- matches table: added match_type, external fields';
    RAISE NOTICE '- availability table: added ecs_fc_match_id reference';
    RAISE NOTICE '- scheduled_message table: enhanced with ECS FC support';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions and triggers: created/updated';
    RAISE NOTICE 'Permissions: set to ecs-admin (if role exists)';
    RAISE NOTICE '';
    RAISE NOTICE 'The database is now ready for ECS FC functionality!';
    RAISE NOTICE '============================================================';
END $$;