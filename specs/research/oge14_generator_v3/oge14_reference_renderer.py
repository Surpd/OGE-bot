"""Reference template renderer + text-slot audit, not production Telegram integration.

Reuses the fixed story/target templates in oge14_wording_patterns.json. The text
is a short independent paraphrase of real task designs, not a verbatim corpus.
"""
from __future__ import annotations
import json, re, string
from fractions import Fraction
from pathlib import Path
from typing import Any,Mapping

PATTERNS={x['family_id']:x for x in json.loads((Path(__file__).parent/'oge14_wording_patterns.json').read_text(encoding='utf-8'))['patterns']}


def numeral_word(n:int,one:str='место',few:str='места',many:str='мест')->str:
    if 11<=abs(n)%100<=14:return many
    last=abs(n)%10
    return one if last==1 else few if 2<=last<=4 else many


def decimal_display(value:Any)->str:
    # Reject floats instead of silently rounding them.
    if isinstance(value,float) or isinstance(value,bool):raise ValueError('decimal must be string/integer/Fraction')
    fraction=Fraction(str(value))
    for places in range(0,3):
        count=fraction*(10**places)
        if count.denominator==1:
            number=count.numerator
            if places==0:return str(number)
            body=str(abs(number)).zfill(places+1)
            return ('-' if number<0 else '')+body[:-places]+','+body[-places:]
    raise ValueError('not an exact one/two-decimal number')


def display_slots(family_id:str, p:Mapping[str,Any])->dict[str,str]:
    f=family_id.split('-')[-1]
    d={str(key):decimal_display(v) for key,v in p.items() if key not in ('known','mode')}
    if f in ('A01','A03'):
        d['a1_seats_word']=numeral_word(int(p['a1']))
        d['d_seats_word']=numeral_word(int(p['d']))
    if f=='A02':
        known=p['known']
        i,j=sorted(int(k) for k in known.keys())
        d.update(known_i=str(i),known_j=str(j),known_ai=decimal_display(known[str(i)]),known_aj=decimal_display(known[str(j)]),
                 known_ai_seats_word=numeral_word(int(known[str(i)])),known_aj_seats_word=numeral_word(int(known[str(j)])))
    if f=='A08':
        d['a1_display']=decimal_display(p['a1'])
        d['d_display']=decimal_display(p['d'])
    if f=='A11':d['rate_display']=decimal_display(p['rate'])
    return d


def render(family_id:str,p:Mapping[str,Any])->str:
    slots=display_slots(family_id,p)
    return PATTERNS[family_id]['template_ru'].format_map(slots)


def parse_slots(family_id:str,text:str)->dict[str,str]:
    """Full anchored parse; catches mutations in fixed words/question/units."""
    template=PATTERNS[family_id]['template_ru']
    components=[]
    for literal, field, _, _ in string.Formatter().parse(template):
        components.append(re.escape(literal))
        if field is not None:
            if field.endswith('_seats_word'):
                components.append(f'(?P<{field}>место|места|мест)')
            else:
                components.append(f'(?P<{field}>-?\\d+(?:,\\d{{1,2}})?)')
    m=re.fullmatch(''.join(components),text)
    if not m:raise ValueError('visible text does not conform to reference template')
    return m.groupdict()


def audit_text(family_id:str,p:Mapping[str,Any],text:str)->None:
    got=parse_slots(family_id,text)
    expected=display_slots(family_id,p)
    for field, visible in got.items():
        if field not in expected or visible!=expected[field]:
            raise ValueError(f'visible slot mismatch {field}: {visible!r} != {expected.get(field)!r}')
    if not got:raise ValueError('empty audit')
