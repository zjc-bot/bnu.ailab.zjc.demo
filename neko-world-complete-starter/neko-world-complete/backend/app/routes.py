from flask import Blueprint, current_app, jsonify, request
from .extensions import db
from .models import UserSetting
from .soul.catalog import SOULS
from .chat.service import chat_reply
api=Blueprint('api',__name__)
@api.get('/health')
def health(): return jsonify({'ok':True,'service':'neko-world'})
@api.get('/souls')
def souls(): return jsonify([{'id':s['id'],'name':s['name'],'description':s['description']} for s in SOULS.values()])
@api.get('/settings')
def settings():
    v={x.key:x.value for x in UserSetting.query.all()}
    return jsonify({'mode':v.get('mode','normal'),'soul_id':v.get('soul_id','gentle')})
@api.put('/settings')
def save_settings():
    data=request.get_json(silent=True) or {}; mode=data.get('mode','normal'); soul=data.get('soul_id','gentle')
    if mode not in ('normal','expressive') or soul not in SOULS: return jsonify({'error':'Invalid mode or soul_id'}),400
    for key,value in (('mode',mode),('soul_id',soul)):
        row=UserSetting.query.filter_by(key=key).first()
        if row is None: db.session.add(UserSetting(key=key,value=value))
        else: row.value=value
    db.session.commit(); return jsonify({'mode':mode,'soul_id':soul})
@api.post('/chat')
def chat():
    data=request.get_json(silent=True) or {}; text=data.get('message','')
    if not isinstance(text,str) or not text.strip(): return jsonify({'error':'message must be non-empty'}),400
    if len(text)>8000: return jsonify({'error':'message too long'}),413
    mode=data.get('mode','normal'); soul=data.get('soul_id','gentle')
    if mode not in ('normal','expressive') or soul not in SOULS: return jsonify({'error':'Invalid mode or soul_id'}),400
    try: return jsonify(chat_reply(current_app.config,data.get('conversation_id'),text.strip(),soul,mode))
    except Exception:
        db.session.rollback(); current_app.logger.exception('Chat request failed')
        return jsonify({'error':'Companion service temporarily unavailable. Check server logs.'}),503
