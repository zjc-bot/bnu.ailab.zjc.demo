from datetime import datetime, timezone
from .extensions import db

def now(): return datetime.now(timezone.utc)
class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False, default='New conversation')
    soul_id = db.Column(db.String(40), nullable=False, default='gentle')
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    messages = db.relationship('Message', backref='conversation', cascade='all, delete-orphan', lazy=True)
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
class UserSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)
