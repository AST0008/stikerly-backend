import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "stikerly")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

try:
    client.admin.command("ping")
    print(f"Connected to MongoDB | DB: {DB_NAME}")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    raise e

templates_collection = db["templates"]
