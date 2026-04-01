-- One-time SQL to update existing theme presets with new Zinc color scheme
-- Run in pgAdmin4 against your production database
-- This updates the 3 system presets to use Zinc neutrals (no blue tint)

-- Default Purple (matches DEFAULT_COLORS in appearance.py)
UPDATE theme_presets
SET colors = '{
  "light": {
    "primary": "#7c3aed",
    "primary_light": "#8b5cf6",
    "primary_dark": "#6d28d9",
    "secondary": "#64748b",
    "accent": "#d97706",
    "success": "#059669",
    "warning": "#ea580c",
    "danger": "#dc2626",
    "info": "#2563eb",
    "text_heading": "#18181b",
    "text_body": "#3f3f46",
    "text_muted": "#71717a",
    "text_link": "#7c3aed",
    "bg_body": "#fafafa",
    "bg_card": "#ffffff",
    "bg_input": "#fafafa",
    "bg_sidebar": "#ffffff",
    "border": "#e4e4e7",
    "border_input": "#d4d4d8"
  },
  "dark": {
    "primary": "#a78bfa",
    "primary_light": "#c4b5fd",
    "primary_dark": "#8b5cf6",
    "secondary": "#a1a1aa",
    "accent": "#fbbf24",
    "success": "#34d399",
    "warning": "#fb923c",
    "danger": "#f87171",
    "info": "#60a5fa",
    "text_heading": "#fafafa",
    "text_body": "#d4d4d8",
    "text_muted": "#a1a1aa",
    "text_link": "#a78bfa",
    "bg_body": "#18181b",
    "bg_card": "#27272a",
    "bg_input": "#3f3f46",
    "bg_sidebar": "#18181b",
    "border": "#3f3f46",
    "border_input": "#52525b"
  }
}'::jsonb
WHERE name = 'Default Purple' AND is_system = true;

-- Ocean Blue
UPDATE theme_presets
SET colors = '{
  "light": {
    "primary": "#0EA5E9",
    "primary_light": "#38BDF8",
    "primary_dark": "#0284C7",
    "secondary": "#64748B",
    "accent": "#F97316",
    "success": "#22C55E",
    "warning": "#EAB308",
    "danger": "#EF4444",
    "info": "#06B6D4",
    "text_heading": "#0F172A",
    "text_body": "#475569",
    "text_muted": "#94A3B8",
    "text_link": "#0EA5E9",
    "bg_body": "#F8FAFC",
    "bg_card": "#FFFFFF",
    "bg_input": "#F8FAFC",
    "bg_sidebar": "#FFFFFF",
    "border": "#E2E8F0",
    "border_input": "#CBD5E1"
  },
  "dark": {
    "primary": "#38BDF8",
    "primary_light": "#7DD3FC",
    "primary_dark": "#0EA5E9",
    "secondary": "#94A3B8",
    "accent": "#FB923C",
    "success": "#4ADE80",
    "warning": "#FACC15",
    "danger": "#F87171",
    "info": "#22D3EE",
    "text_heading": "#F1F5F9",
    "text_body": "#CBD5E1",
    "text_muted": "#94A3B8",
    "text_link": "#38BDF8",
    "bg_body": "#18181B",
    "bg_card": "#27272A",
    "bg_input": "#3F3F46",
    "bg_sidebar": "#18181B",
    "border": "#3F3F46",
    "border_input": "#52525B"
  }
}'::jsonb
WHERE name = 'Ocean Blue' AND is_system = true;

-- Forest Green
UPDATE theme_presets
SET colors = '{
  "light": {
    "primary": "#059669",
    "primary_light": "#10B981",
    "primary_dark": "#047857",
    "secondary": "#6B7280",
    "accent": "#D97706",
    "success": "#22C55E",
    "warning": "#EA580C",
    "danger": "#DC2626",
    "info": "#0891B2",
    "text_heading": "#111827",
    "text_body": "#4B5563",
    "text_muted": "#9CA3AF",
    "text_link": "#059669",
    "bg_body": "#F9FAFB",
    "bg_card": "#FFFFFF",
    "bg_input": "#F9FAFB",
    "bg_sidebar": "#FFFFFF",
    "border": "#E5E7EB",
    "border_input": "#D1D5DB"
  },
  "dark": {
    "primary": "#34D399",
    "primary_light": "#6EE7B7",
    "primary_dark": "#10B981",
    "secondary": "#9CA3AF",
    "accent": "#FBBF24",
    "success": "#4ADE80",
    "warning": "#FB923C",
    "danger": "#F87171",
    "info": "#22D3EE",
    "text_heading": "#F9FAFB",
    "text_body": "#D1D5DB",
    "text_muted": "#9CA3AF",
    "text_link": "#34D399",
    "bg_body": "#18181B",
    "bg_card": "#27272A",
    "bg_input": "#3F3F46",
    "bg_sidebar": "#18181B",
    "border": "#3F3F46",
    "border_input": "#52525B"
  }
}'::jsonb
WHERE name = 'Forest Green' AND is_system = true;
