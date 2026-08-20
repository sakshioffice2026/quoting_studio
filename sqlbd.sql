-- 1. Create database
CREATE DATABASE quoting_studio CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE quoting_studio;

-- 2. Tenants (company workspaces)
CREATE TABLE tenants (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(120) NOT NULL,
    slug          VARCHAR(80)  NOT NULL UNIQUE,
    contact_email VARCHAR(200) NOT NULL,
    logo_path     VARCHAR(500),
    brand_colour  VARCHAR(7)   NOT NULL DEFAULT '#C97B3D',
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenants_slug (slug)
) ENGINE=InnoDB;

-- 3. Users
CREATE TABLE users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id     INT          NOT NULL,
    email         VARCHAR(200) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    full_name     VARCHAR(150) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'member',
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login    DATETIME,
    INDEX idx_users_tenant (tenant_id),
    INDEX idx_users_email  (email),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 4. Projects
CREATE TABLE projects (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id     INT          NOT NULL,
    created_by    INT          NOT NULL,
    customer_name VARCHAR(200) NOT NULL,
    address       VARCHAR(500),
    notes         TEXT,
    status        VARCHAR(20)  NOT NULL DEFAULT 'draft',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_projects_tenant (tenant_id),
    INDEX idx_projects_status (status),
    FOREIGN KEY (tenant_id)  REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB;

-- 5. Windows
CREATE TABLE windows (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    project_id        INT          NOT NULL,
    tenant_id         INT          NOT NULL,
    label             VARCHAR(200) NOT NULL DEFAULT 'Window',
    width_mm          INT          NOT NULL DEFAULT 1200,
    height_mm         INT          NOT NULL DEFAULT 1400,
    material          VARCHAR(50)  NOT NULL DEFAULT 'Aluminium',
    frame_colour_hex  VARCHAR(7)   NOT NULL DEFAULT '#2B2F33',
    frame_colour_name VARCHAR(80)  NOT NULL DEFAULT 'Anthracite',
    sequence_order    INT          NOT NULL DEFAULT 0,
    INDEX idx_windows_project (project_id),
    INDEX idx_windows_tenant  (tenant_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id)  REFERENCES tenants(id)
) ENGINE=InnoDB;

-- 6. Panes
CREATE TABLE panes (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    window_id    INT          NOT NULL,
    cell_key     VARCHAR(40)  NOT NULL,
    x_norm       FLOAT        NOT NULL DEFAULT 0.0,
    y_norm       FLOAT        NOT NULL DEFAULT 0.0,
    w_norm       FLOAT        NOT NULL DEFAULT 1.0,
    h_norm       FLOAT        NOT NULL DEFAULT 1.0,
    opener_type  VARCHAR(80)  NOT NULL DEFAULT 'Fixed light',
    glazing_type VARCHAR(80)  NOT NULL DEFAULT 'Double, Low-E',
    INDEX idx_panes_window (window_id),
    FOREIGN KEY (window_id) REFERENCES windows(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 7. Visualisations
CREATE TABLE visualisations (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    window_id     INT          NOT NULL,
    photo_path    VARCHAR(500),
    corner_tl_x   FLOAT,
    corner_tl_y   FLOAT,
    corner_tr_x   FLOAT,
    corner_tr_y   FLOAT,
    corner_bl_x   FLOAT,
    corner_bl_y   FLOAT,
    corner_br_x   FLOAT,
    corner_br_y   FLOAT,
    opacity       FLOAT        DEFAULT 0.92,
    brightness    FLOAT        DEFAULT 1.0,
    rendered_path VARCHAR(500),
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_vis_window (window_id),
    FOREIGN KEY (window_id) REFERENCES windows(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 8. Quotes
CREATE TABLE quotes (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    project_id   INT            NOT NULL,
    tenant_id    INT            NOT NULL,
    quote_number VARCHAR(40)    NOT NULL UNIQUE,
    issued_date  DATE           NOT NULL,
    subtotal     DECIMAL(10,2),
    vat_rate     FLOAT          DEFAULT 0.20,
    total        DECIMAL(10,2),
    pdf_path     VARCHAR(500),
    sent_at      DATETIME,
    created_at   DATETIME       DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_quotes_project (project_id),
    INDEX idx_quotes_tenant  (tenant_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id)  REFERENCES tenants(id)
) ENGINE=InnoDB;

-- 9. Pricing rules — per material
CREATE TABLE pricing_rules (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id            INT            NOT NULL,
    material             VARCHAR(50)    NOT NULL,
    frame_cost_per_metre DECIMAL(8,2)   NOT NULL DEFAULT 3.20,
    glass_cost_per_m2    DECIMAL(8,2)   NOT NULL DEFAULT 95.00,
    fitting_fixed        DECIMAL(8,2)   NOT NULL DEFAULT 140.00,
    is_active            TINYINT(1)     DEFAULT 1,
    INDEX idx_pricing_tenant (tenant_id),
    UNIQUE KEY uq_pricing_tenant_material (tenant_id, material),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 10. Pricing rules — per opener type
CREATE TABLE opener_pricing_rules (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id     INT            NOT NULL,
    opener_type   VARCHAR(80)    NOT NULL,
    hardware_cost DECIMAL(8,2)   NOT NULL DEFAULT 0.00,
    is_active     TINYINT(1)     DEFAULT 1,
    INDEX idx_opener_tenant (tenant_id),
    UNIQUE KEY uq_opener_tenant_type (tenant_id, opener_type),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 11. Pricing rules — per glazing type
CREATE TABLE glazing_pricing_rules (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id       INT            NOT NULL,
    glazing_type    VARCHAR(80)    NOT NULL,
    cost_multiplier FLOAT          NOT NULL DEFAULT 0.0,
    is_active       TINYINT(1)     DEFAULT 1,
    INDEX idx_glazing_tenant (tenant_id),
    UNIQUE KEY uq_glazing_tenant_type (tenant_id, glazing_type),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE exception_logs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level       VARCHAR(10)  NOT NULL,
    module      VARCHAR(100),
    func_name   VARCHAR(100),
    line_no     INT,
    message     TEXT         NOT NULL,
    exc_type    VARCHAR(200),
    exc_message TEXT,
    traceback   TEXT,
    url         VARCHAR(500),
    method      VARCHAR(10),
    user_id     INT,
    tenant_id   INT,
    ip_address  VARCHAR(45),
    INDEX idx_exlog_created  (created_at),
    INDEX idx_exlog_level    (level),
    INDEX idx_exlog_tenant   (tenant_id),
    INDEX idx_exlog_user     (user_id)
) ENGINE=InnoDB;

USE quoting_studio;

CREATE TABLE cad_profiles (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id           INT            NOT NULL,
    name                VARCHAR(120)   NOT NULL,
    drawing_ref         VARCHAR(80),
    material            VARCHAR(50)    NOT NULL DEFAULT 'Aluminium',
    bar_width_mm        FLOAT          NOT NULL DEFAULT 40.0,
    wall_thickness_mm   FLOAT          NOT NULL DEFAULT 4.0,
    depth_mm            FLOAT          NOT NULL DEFAULT 52.0,
    glass_rebate_mm     FLOAT          NOT NULL DEFAULT 20.0,
    weather_seal_mm     FLOAT          NOT NULL DEFAULT 2.0,
    source_file         VARCHAR(500),
    is_active           TINYINT(1)     DEFAULT 1,
    is_default          TINYINT(1)     DEFAULT 0,
    created_at          DATETIME       DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cad_tenant (tenant_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB;

USE quoting_studio;

-- Product catalog for the drawing engine workflow
CREATE TABLE IF NOT EXISTS product_series (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id   INT           NOT NULL,
    name        VARCHAR(120)  NOT NULL,
    description VARCHAR(400),
    thumbnail   VARCHAR(500),
    material    VARCHAR(50)   DEFAULT 'Aluminium',
    is_active   TINYINT(1)    DEFAULT 1,
    created_at  DATETIME      DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ps_tenant (tenant_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS window_styles (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    series_id        INT           NOT NULL,
    name             VARCHAR(120)  NOT NULL,
    panels           INT           DEFAULT 1,
    image            VARCHAR(500),
    default_template TEXT,
    sort_order       INT           DEFAULT 0,
    INDEX idx_ws_series (series_id),
    FOREIGN KEY (series_id) REFERENCES product_series(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Add design_json + style_id to windows if not present
-- (safe to run — will error harmlessly if columns already exist)
ALTER TABLE windows ADD COLUMN design_json TEXT NULL;
ALTER TABLE windows ADD COLUMN style_id INT NULL;

SHOW TABLES LIKE 'product_series';
SHOW TABLES LIKE 'window_styles';
-- Verify
USE quoting_studio;

-- Add design_json column to windows (safe to run even if it already exists)
ALTER TABLE windows ADD COLUMN design_json TEXT NULL;
ALTER TABLE windows ADD COLUMN style_id INT NULL;
USE quoting_studio;

USE quoting_studio;
ALTER TABLE projects ADD COLUMN facade_json TEXT NULL;
SELECT 'facade_json column added' AS status;

SELECT 'columns added' AS status;
SHOW TABLES LIKE 'cad_profiles';
-- 12. Verify all tables created
SHOW TABLES;
USE quoting_studio;

-- Run each statement one at a time.
-- If you get "Duplicate column name" on any line, just skip it — column already exists.

USE quoting_studio;

ALTER TABLE windows  ADD COLUMN design_json      TEXT NULL;
ALTER TABLE windows  ADD COLUMN style_id         INT  NULL;
ALTER TABLE quotes   ADD COLUMN revision         INT  NOT NULL DEFAULT 1;
ALTER TABLE quotes   ADD COLUMN parent_quote_id  INT  NULL;
ALTER TABLE projects ADD COLUMN facade_json      TEXT NULL;
ALTER TABLE quotes   ADD INDEX  idx_quotes_parent (parent_quote_id);

-- Profile library migration: adds new columns to cad_profiles
-- Run once. Skip any lines that say "Duplicate column name".
 
ALTER TABLE cad_profiles ADD COLUMN code VARCHAR(30) NOT NULL DEFAULT '';
ALTER TABLE cad_profiles ADD COLUMN category VARCHAR(40) NOT NULL DEFAULT 'Frame';
ALTER TABLE cad_profiles ADD COLUMN rebate_w_mm FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE cad_profiles ADD COLUMN rebate_d_mm FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE cad_profiles ADD COLUMN geometry_json LONGTEXT NULL;
ALTER TABLE cad_profiles ADD COLUMN svg_path LONGTEXT NULL;
ALTER TABLE cad_profiles ADD COLUMN vertex_count INT NULL;
ALTER TABLE cad_profiles ADD COLUMN is_builtin TINYINT(1) NOT NULL DEFAULT 1;

-- Glass Unit Library migration
-- Creates glass_units table. Safe to run multiple times (will error if table exists — ignore).
 
CREATE TABLE IF NOT EXISTS glass_units (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id    INT NOT NULL,
    code         VARCHAR(30) NOT NULL DEFAULT '',
    name         VARCHAR(120) NOT NULL,
    build_up     VARCHAR(60) NOT NULL DEFAULT '',
    thickness_mm FLOAT NOT NULL DEFAULT 24.0,
    u_value      FLOAT NULL,
    g_value      FLOAT NULL,
    description  VARCHAR(300) NULL,
    is_builtin   TINYINT(1) NOT NULL DEFAULT 1,
    is_active    TINYINT(1) NOT NULL DEFAULT 1,
    sort_order   INT NOT NULL DEFAULT 0,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_glass_tenant (tenant_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);
 
-- Fix: quote_number was globally UNIQUE, but numbers are generated per-tenant.
-- Two tenants generating a quote in the same month both get QS-YYYYMM-001,
-- which violates the global unique constraint on the second tenant.
-- Change to a composite unique (tenant_id, quote_number).
--
-- Run these in order. The DROP name may differ on your DB — check first with:
--   SHOW INDEX FROM quotes;
-- and drop whatever unique index covers quote_number alone.

-- 1. Drop the old global unique index (MySQL usually names it 'quote_number')
ALTER TABLE quotes DROP INDEX quote_number;

-- 2. Add the composite per-tenant unique constraint
ALTER TABLE quotes ADD CONSTRAINT uq_quote_tenant_number UNIQUE (tenant_id, quote_number);

SELECT 'quotes: quote_number now unique per tenant' AS status;
SELECT 'glass_units table ready' AS status;
SELECT 'Done' AS status;

-- Issue #1 (glass-library codes not priced) + Issue #3 (solid panels priced as glass)
-- Two new columns. MySQL does not support IF NOT EXISTS on ADD COLUMN —
-- if a column already exists you'll get "Duplicate column"; that's safe to ignore.

-- 1. Per-unit supply rate (£/m²) so pricing can look up glazing by code
ALTER TABLE glass_units ADD COLUMN price_per_m2 DECIMAL(10,2) NULL;

-- 2. Pane infill type so solid door panels carry no glass cost
ALTER TABLE panes ADD COLUMN infill VARCHAR(10) NOT NULL DEFAULT 'glass';
SET SQL_SAFE_UPDATES = 0;

-- 3. Backfill built-in glass unit prices (UK trade rates) for existing rows.
--    Safe to re-run; only updates rows that currently have NULL price.
UPDATE glass_units SET price_per_m2 = 42.00  WHERE code = 'SG-4'  AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 68.00  WHERE code = 'DG-24' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 82.00  WHERE code = 'DG-28' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 95.00  WHERE code = 'DG-32' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 108.00 WHERE code = 'DG-36' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 135.00 WHERE code = 'TG-40' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 152.00 WHERE code = 'TG-44' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 178.00 WHERE code = 'TG-48' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 55.00  WHERE code = 'OB-6'  AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 128.00 WHERE code = 'AC-44' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 115.00 WHERE code = 'SC-28' AND price_per_m2 IS NULL;
UPDATE glass_units SET price_per_m2 = 165.00 WHERE code = 'SF-32' AND price_per_m2 IS NULL;

SET SQL_SAFE_UPDATES = 1;
-- ============================================================
-- Migration: add member-role columns to cad_profiles
-- Run manually (MySQL ALTER has no IF NOT EXISTS on ADD COLUMN).
-- If a column already exists, MySQL errors 1060 — safe to ignore
-- for the column that already exists; run the remaining lines.
-- ============================================================

ALTER TABLE cad_profiles
  ADD COLUMN role VARCHAR(30) NULL;

ALTER TABLE cad_profiles
  ADD COLUMN is_role_default TINYINT(1) NOT NULL DEFAULT 0;

CREATE INDEX ix_cad_profiles_role ON cad_profiles (role);

-- Back-fill role from the existing category so nothing is left NULL.
UPDATE cad_profiles SET role = 'outer_frame'  WHERE role IS NULL AND category = 'Frame';
UPDATE cad_profiles SET role = 'cill'         WHERE role IS NULL AND category = 'Sill';
UPDATE cad_profiles SET role = 'sash'         WHERE role IS NULL AND category = 'Sash';
UPDATE cad_profiles SET role = 'mullion'      WHERE role IS NULL AND category = 'Mullion';
UPDATE cad_profiles SET role = 'transom'      WHERE role IS NULL AND category = 'Transom';
UPDATE cad_profiles SET role = 'glazing_bead' WHERE role IS NULL AND category = 'GlazingBead';
UPDATE cad_profiles SET role = 'outer_frame'  WHERE role IS NULL;  -- catch-all

-- ============================================================
-- Migration: ProfileSystem
-- Creates the profile_systems table and links windows to a system.
-- Run line-by-line in MySQL Workbench / CLI.
-- Each ALTER TABLE may error 1060 (column exists) — safe to skip.
-- ============================================================

CREATE TABLE IF NOT EXISTS profile_systems (
  id                  INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
  tenant_id           INT          NOT NULL,
  name                VARCHAR(120) NOT NULL,
  material            VARCHAR(50)  NOT NULL DEFAULT 'Aluminium',
  is_default          TINYINT(1)   NOT NULL DEFAULT 0,
  is_active           TINYINT(1)   NOT NULL DEFAULT 1,
  notes               TEXT,

  -- outer frame (window + door)
  head_id             INT          NULL,
  cill_id             INT          NULL,
  jamb_id             INT          NULL,

  -- door-specific
  threshold_id        INT          NULL,
  door_leaf_id        INT          NULL,
  meeting_stile_id    INT          NULL,

  -- internal dividers
  mullion_id          INT          NULL,
  transom_id          INT          NULL,

  -- sash (opening leaf)
  sash_top_id         INT          NULL,
  sash_bottom_id      INT          NULL,
  sash_side_id        INT          NULL,

  -- glazing
  glazing_bead_id     INT          NULL,

  -- joint + geometry rules
  frame_corner_joint  VARCHAR(20)  NOT NULL DEFAULT 'mitre_45',
  sash_corner_joint   VARCHAR(20)  NOT NULL DEFAULT 'mitre_45',
  internal_joint      VARCHAR(20)  NOT NULL DEFAULT 'butt',
  sash_clearance_mm   FLOAT        NOT NULL DEFAULT 2.0,

  FOREIGN KEY (tenant_id)        REFERENCES tenants(id)       ON DELETE CASCADE,
  FOREIGN KEY (head_id)          REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (cill_id)          REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (jamb_id)          REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (threshold_id)     REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (door_leaf_id)     REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (meeting_stile_id) REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (mullion_id)       REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (transom_id)       REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (sash_top_id)      REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (sash_bottom_id)   REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (sash_side_id)     REFERENCES cad_profiles(id)  ON DELETE SET NULL,
  FOREIGN KEY (glazing_bead_id)  REFERENCES cad_profiles(id)  ON DELETE SET NULL,

  INDEX ix_profile_systems_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Link each Window to a ProfileSystem (optional — NULL = use role defaults)
ALTER TABLE windows
  ADD COLUMN profile_system_id INT NULL,
  ADD FOREIGN KEY (profile_system_id) REFERENCES profile_systems(id) ON DELETE SET NULL;
  
ALTER TABLE cad_profiles
  ADD COLUMN role            VARCHAR(30) NULL,
  ADD COLUMN is_role_default TINYINT(1)  NOT NULL DEFAULT 0;