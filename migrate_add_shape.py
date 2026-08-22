#!/usr/bin/env python3
"""
Direct database migration script - run this to add shape column to windows table.
Usage: python migrate_add_shape.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db

def migrate():
    app = create_app()
    with app.app_context():
        try:
            # Execute the migration
            db.session.execute("""
                ALTER TABLE windows 
                ADD COLUMN shape VARCHAR(50) NOT NULL DEFAULT 'rectangular' 
                AFTER height_mm
            """)
            db.session.commit()
            print("✓ Successfully added 'shape' column to windows table")
            print("✓ Default value set to 'rectangular'")
        except Exception as e:
            db.session.rollback()
            print(f"✗ Migration failed: {e}")
            sys.exit(1)

if __name__ == '__main__':
    migrate()
