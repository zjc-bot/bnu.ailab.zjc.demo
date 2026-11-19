from flask import Flask, send_from_directory
from pathlib import Path
from .config import Config
from .extensions import db
from .routes import api

def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    db.init_app(app)
    app.register_blueprint(api, url_prefix='/api')
    frontend = Path(__file__).resolve().parents[2] / 'frontend'
    @app.get('/')
    def index(): return send_from_directory(frontend, 'index.html')
    @app.get('/<path:filename>')
    def assets(filename): return send_from_directory(frontend, filename)
    with app.app_context(): db.create_all()
    return app
