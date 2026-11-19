from ..extensions import db
from ..models import Conversation, Message
from ..soul.catalog import get_soul
from ..avatar.actions import validate_action
from ..providers.mock_provider import MockProvider
from ..providers.openai_compatible import OpenAICompatibleProvider

def chat_reply(config, conversation_id, text, soul_id, mode):
    conversation = db.session.get(Conversation, conversation_id) if conversation_id else None
    if conversation is None:
        conversation = Conversation(soul_id=soul_id); db.session.add(conversation); db.session.flush()
    conversation.soul_id = soul_id
    history = [{'role':m.role,'content':m.content} for m in Message.query.filter_by(conversation_id=conversation.id).order_by(Message.id.asc()).all()]
    history.append({'role':'user','content':text})
    db.session.add(Message(conversation_id=conversation.id,role='user',content=text))
    soul = get_soul(soul_id)
    provider = OpenAICompatibleProvider(config) if config['AI_PROVIDER']=='openai_compatible' else MockProvider()
    raw = provider.generate(history,soul,mode)
    if isinstance(raw,str):
        import json
        try: raw=json.loads(raw)
        except json.JSONDecodeError: raw={'message':raw,'avatar':None}
    if not isinstance(raw,dict): raw={}
    answer = raw.get('message','I am here. Tell me more.')
    if not isinstance(answer,str): answer=str(answer)
    answer=answer.strip()[:12000] or 'I am listening.'
    avatar=validate_action(raw.get('avatar'),mode)
    db.session.add(Message(conversation_id=conversation.id,role='assistant',content=answer))
    db.session.commit()
    return {'conversation_id':conversation.id,'message':answer,'avatar':avatar,'soul':{'id':soul['id'],'name':soul['name']},'mode':mode}
