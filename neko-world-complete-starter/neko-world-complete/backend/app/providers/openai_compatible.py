import json, requests
class OpenAICompatibleProvider:
    def __init__(self, config):
        if not config['AI_API_KEY'] or not config['AI_MODEL']:
            raise RuntimeError('AI_API_KEY and AI_MODEL are required.')
        self.url = config['AI_BASE_URL'] + '/chat/completions'
        self.key, self.model = config['AI_API_KEY'], config['AI_MODEL']
        self.temperature, self.timeout = config['AI_TEMPERATURE'], config['AI_TIMEOUT_SECONDS']
    def generate(self, messages, soul, mode):
        system = soul['system_prompt'] + '''\nReturn ONLY JSON: {"message":"...","avatar":null or {"expression":"neutral|happy|shy|sad|surprised|curious|sleepy|pout","gesture":"none|wave|nod|tilt_head|look_away|heart_gesture","effect":"none|floating_hearts|sparkles|sweat_drop","duration_ms":1400}}. Never output code or frame-by-frame animation instructions. '''
        system += 'In normal mode, only react to meaningful moments. ' if mode == 'normal' else 'Use contextual avatar reactions more freely. '
        payload = [{'role':'system','content':system}] + messages[-16:]
        r = requests.post(self.url, headers={'Authorization':'Bearer '+self.key}, json={
            'model':self.model,'messages':payload,'temperature':self.temperature,
            'response_format':{'type':'json_object'}}, timeout=self.timeout)
        r.raise_for_status()
        content = r.json()['choices'][0]['message']['content']
        try: return json.loads(content)
        except (json.JSONDecodeError,TypeError): return {'message':str(content),'avatar':None}
