class MockProvider:
    def generate(self, messages, soul, mode):
        text = messages[-1]['content'].lower()
        if any(x in text for x in ('love','miss you','喜欢','爱你','想你')):
            return {'message':'Hehe… you are making me blush. I am happy you are here! 💗','avatar':{'expression':'shy','gesture':'look_away','effect':'floating_hearts','duration_ms':2200}}
        if any(x in text for x in ('hello','hi','你好','嗨')):
            return {'message':'Hello! Welcome back. Mochi is right here~','avatar':{'expression':'happy','gesture':'wave','effect':'sparkles','duration_ms':1800}}
        return {'message':'I am listening! Tell me a little more. I can chat here and react when there is a moment worth expressing.','avatar':{'expression':'curious','gesture':'tilt_head','effect':'none','duration_ms':1600}}
