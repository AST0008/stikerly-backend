import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import templates_collection

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DB = os.path.join(BASE_DIR, "assets", "templates.json")


def migrate():
    with open(TEMPLATE_DB, "r") as f:
        templates = json.load(f)

    for template in templates:
        if not templates_collection.find_one({"id": template["id"]}):
            templates_collection.insert_one(template)
            print(f"Inserted:  {template['id']}")
        else:
            print(f"Skipped:   {template['id']} (already exists)")

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
