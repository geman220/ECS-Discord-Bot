-- Add ECS FC specific permissions and role
-- This script adds the ECS FC Coach role and necessary permissions

-- Add new permissions for ECS FC (only if they don't exist)
INSERT INTO permissions (name, description) 
SELECT 'view_ecs_fc', 'Permission to view ECS FC'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = 'view_ecs_fc');

INSERT INTO permissions (name, description) 
SELECT 'edit_ecs_fc', 'Permission to edit ECS FC'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = 'edit_ecs_fc');

INSERT INTO permissions (name, description) 
SELECT 'manage_ecs_fc_schedule', 'Permission to manage ECS FC schedule'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = 'manage_ecs_fc_schedule');

INSERT INTO permissions (name, description) 
SELECT 'view_ecs_fc_rsvps', 'Permission to view ECS FC RSVPs'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = 'view_ecs_fc_rsvps');

INSERT INTO permissions (name, description) 
SELECT 'send_ecs_fc_notifications', 'Permission to send ECS FC notifications'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = 'send_ecs_fc_notifications');

-- Add ECS FC Coach role (only if it doesn't exist)
INSERT INTO roles (name, description) 
SELECT 'ECS FC Coach', 'Coach for ECS FC teams'
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'ECS FC Coach');

-- Grant permissions to ECS FC Coach role
INSERT INTO role_permissions (role_id, permission_id) 
SELECT DISTINCT r.id, p.id 
FROM roles r, permissions p 
WHERE r.name = 'ECS FC Coach' 
AND p.name IN (
    'view_ecs_fc',
    'edit_ecs_fc', 
    'manage_ecs_fc_schedule',
    'view_ecs_fc_rsvps',
    'send_ecs_fc_notifications',
    'view_team_record',
    'view_player_goals_assists',
    'view_player_cards',
    'view_match_page',
    'view_rsvps',
    'upload_kit',
    'view_player_contact_info',
    'view_player_admin_notes',
    'view_discord_info',
    'view_all_player_profiles',
    'edit_player_admin_notes',
    'report_match',
    'upload_team_kit',
    'upload_team_photo'
)
AND NOT EXISTS (
    SELECT 1 FROM role_permissions rp 
    WHERE rp.role_id = r.id AND rp.permission_id = p.id
);

-- Grant Global Admin and Pub League Admin access to ECS FC permissions as well
INSERT INTO role_permissions (role_id, permission_id)
SELECT DISTINCT r.id, p.id 
FROM roles r, permissions p 
WHERE r.name IN ('Global Admin', 'Pub League Admin')
AND p.name IN (
    'view_ecs_fc',
    'edit_ecs_fc',
    'manage_ecs_fc_schedule', 
    'view_ecs_fc_rsvps',
    'send_ecs_fc_notifications'
)
AND NOT EXISTS (
    SELECT 1 FROM role_permissions rp 
    WHERE rp.role_id = r.id AND rp.permission_id = p.id
);