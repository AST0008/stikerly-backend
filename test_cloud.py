import os
from dotenv import load_dotenv
load_dotenv()
import cloudinary
import cloudinary.uploader
print(cloudinary.config().cloud_name)
