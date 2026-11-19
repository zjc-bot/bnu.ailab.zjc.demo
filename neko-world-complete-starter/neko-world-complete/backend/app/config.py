import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-only-change-me')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///neko_world.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = os.getenv('FLASK_DEBUG', '0').lower() in ('1','true','yes')
    AI_PROVIDER = os.getenv('AI_PROVIDER', 'mock').lower()
    AI_BASE_URL = os.getenv('AI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    AI_API_KEY = os.getenv('AI_API_KEY', '')
    AI_MODEL = os.getenv('AI_MODEL', '')
    AI_TEMPERATURE = float(os.getenv('AI_TEMPERATURE', '0.8'))
    AI_TIMEOUT_SECONDS = int(os.getenv('AI_TIMEOUT_SECONDS', '45'))
