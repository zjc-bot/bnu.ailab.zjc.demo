EXPRESSIONS = {'neutral','happy','shy','sad','surprised','curious','sleepy','pout'}
GESTURES = {'none','wave','nod','tilt_head','look_away','heart_gesture'}
EFFECTS = {'none','floating_hearts','sparkles','sweat_drop'}
def validate_action(raw, mode='normal'):
    if not isinstance(raw, dict): return None
    a = {'expression':raw.get('expression','neutral'), 'gesture':raw.get('gesture','none'), 'effect':raw.get('effect','none')}
    if a['expression'] not in EXPRESSIONS: a['expression'] = 'neutral'
    if a['gesture'] not in GESTURES: a['gesture'] = 'none'
    if a['effect'] not in EFFECTS: a['effect'] = 'none'
    try: duration = int(raw.get('duration_ms',1400))
    except (TypeError,ValueError): duration = 1400
    a['duration_ms'] = max(500,min(duration,5000))
    if a['expression']=='neutral' and a['gesture']=='none' and a['effect']=='none': return None
    return a
