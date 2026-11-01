"""Reference smoke/regression tests, NOT a substitute for production text oracle/CI."""
from __future__ import annotations
import copy, json, random, unittest, string
from fractions import Fraction
from pathlib import Path
from oge14_reference_oracle import solve_closed, solve_enumerated, decimal_string, audit_case
from oge14_reference_renderer import render, audit_text, numeral_word

ROOT=Path(__file__).parent
CASES=json.loads((ROOT/'oge14_source_cases.json').read_text(encoding='utf-8'))['cases']
FAMILIES=json.loads((ROOT/'oge14_reference_structures.json').read_text(encoding='utf-8'))['families']


def synthetic_case(fid, rng):
    """Only mathematical stress fixtures; do not show as exam originals."""
    k=fid.rsplit('-',1)[-1]
    r=rng.randint
    if k=='A01':
        n=r(10,20);return dict(rows=n,a1=r(12,30),d=r(1,5),target_index=r(2,n))
    if k=='A02':
        n=r(10,20);i=r(2,6);j=r(i+1,n-1); a1=r(10,25);d=r(1,5)
        return dict(rows=n,known={str(i):a1+(i-1)*d,str(j):a1+(j-1)*d},target_index=n)
    if k=='A03':return dict(rows=r(8,18),a1=r(10,26),d=r(1,5))
    if k=='A04':return dict(n=r(3,8),a1=r(5,20),d=r(2,10))
    if k=='A05':
        total=r(6,15);return dict(minutes_total=total,t=r(1,total),T0=r(-20,35),decrease_per_minute=r(1,8))
    if k=='A06':
        step=r(2,8); n=r(3,8);return dict(first_second_distance=n*step,decrease_each_second=step)
    if k=='A07':
        n=r(3,8); step=r(2,7);return dict(n=n,a1=(n-1)*step+r(1,18),decrease_each_second=step)
    if k=='A08':return dict(a1=str(Fraction(r(1,12),10)),d=str(Fraction(r(2,9),10)),n=r(5,12))
    if k=='A09':
        n=r(3,12);a1=r(10,30);d=r(2,6);an=a1+(n-1)*d;return dict(S=n*(a1+an)//2,first_plus_last=a1+an)
    if k=='A10':
        n=r(7,20);a1=r(10,40);d=r(2,9)
        return dict(a1=a1,n=n,sum=n*(2*a1+(n-1)*d)//2,target_index=r(2,n))
    if k=='A11':return dict(rate=str(Fraction(r(2,25),10)),minutes=r(2,12))
    if k in ('G01','G03'):
        cycles=r(2,6);rem=r(1,20);period=r(5,15)
        return dict(initial_mass_mg=rem*2**cycles,period_minutes=period,elapsed_minutes=cycles*period)
    if k=='G02':
        cycles=r(2,4);factor=r(2,3);period=r(10,30)
        return dict(initial_mass_mg=r(2,10),factor=factor,period_minutes=period,elapsed_minutes=cycles*period)
    if k=='G04':
        q=r(2,4); index=r(2,5); tail=r(2,6)
        return dict(first_height_cm=tail*q**(index-1),factor_decrease=q,strict_threshold_cm=r(tail+1,tail*q))
    raise AssertionError(fid)


class SourceRegression(unittest.TestCase):
    def test_all_23_source_cases(self):
        self.assertEqual(len(CASES),23)
        self.assertEqual(len(FAMILIES),15)
        for case in CASES:
            with self.subTest(case_id=case['case_id']):
                audit_case(case['family_id'],case['source_parameters'],case['expected_answer'])

    def test_all_15_families_are_covered_by_references(self):
        coverage={v['family_id'] for v in CASES}
        self.assertEqual(coverage,{v['family_id'] for v in FAMILIES})

    def test_all_starts_disabled(self):
        self.assertTrue(all(x['implementation_status']=='disabled_pending_oracle_and_tests' for x in FAMILIES))

    def test_1600_constructive_stress_cases(self):
        rng=random.Random(20261101)
        for fam in FAMILIES:
            for index in range(107): # 15*107 = 1605 samples
                p=synthetic_case(fam['family_id'],rng)
                with self.subTest(family=fam['family_id'],index=index):
                    f=solve_closed(fam['family_id'],p)
                    b=solve_enumerated(fam['family_id'],p)
                    self.assertEqual(f,b)
                    self.assertLessEqual(abs(f),10000)
                    self.assertLessEqual(len(decimal_string(f,2)),10)

    def test_slot_templates_are_complete(self):
        patterns=json.loads((ROOT/'oge14_wording_patterns.json').read_text(encoding='utf-8'))['patterns']
        self.assertEqual(len(patterns),15)
        for item in patterns:
            with self.subTest(item['family_id']):
                slots={field for _,field,_,_ in string.Formatter().parse(item['template_ru']) if field is not None}
                supported=set(item['required_visible_slots'])|set(item.get('derived_display_slots',[]))
                self.assertTrue(slots <= supported, f"Unspecified template slots: {slots-supported}")
                self.assertTrue(set(item['required_visible_slots']) <= slots|set(item.get('derived_display_slots',[])))
                self.assertGreater(len(item['source_urls']),0)
                self.assertFalse(item.get('needs_images',True))

    def test_all_source_text_roundtrip(self):
        for case in CASES:
            with self.subTest(case_id=case['case_id']):
                text=render(case['family_id'],case['source_parameters'])
                audit_text(case['family_id'],case['source_parameters'],text)
                self.assertLess(len(text),900)

    def test_constructive_text_roundtrip(self):
        rng=random.Random(406645)
        for family in FAMILIES:
            for _ in range(50):
                p=synthetic_case(family['family_id'],rng)
                txt=render(family['family_id'],p)
                audit_text(family['family_id'],p,txt)

    def test_text_mutations_blocked(self):
        p=dict(initial_mass_mg=160,period_minutes=8,elapsed_minutes=40)
        s=render('OGE14-G03',p)
        audit_text('OGE14-G03',p,s)
        for corrupted in (s.replace('160 мг','260 мг'),s.replace('изотопа Б через','изотопа А через'),s.replace('8 минут','9 минут'),s.replace('половина массы','треть массы')):
            with self.subTest(text=corrupted):
                with self.assertRaises(ValueError):audit_text('OGE14-G03',p,corrupted)
        self.assertEqual(numeral_word(1),'место')
        self.assertEqual(numeral_word(2),'места')
        self.assertEqual(numeral_word(11),'мест')
        self.assertEqual(numeral_word(21),'место')

    def test_strict_bounce_boundary(self):
        fid='OGE14-G04'
        # Equal to third bounce height 40 => first strictly below 40 is fourth bounce.
        p=dict(first_height_cm=360,factor_decrease=3,strict_threshold_cm=40)
        self.assertEqual(solve_closed(fid,p),Fraction(4))
        self.assertEqual(solve_enumerated(fid,p),Fraction(4))
        p['strict_threshold_cm']=41
        self.assertEqual(solve_closed(fid,p),Fraction(3))

    def test_time_zero_and_units(self):
        for fid,p,answer in [
            ('OGE14-G01',dict(initial_mass_mg=320,period_minutes=8,elapsed_minutes=0),320),
            ('OGE14-G02',dict(initial_mass_mg=13,factor=3,period_minutes=30,elapsed_minutes=0),13),
            ('OGE14-G03',dict(initial_mass_mg=160,period_minutes=8,elapsed_minutes=0),0),
            ('OGE14-A05',dict(T0=-7,t=0,minutes_total=10,decrease_per_minute=6),-7),
        ]:
            self.assertEqual(solve_closed(fid,p),Fraction(answer))
            self.assertEqual(solve_enumerated(fid,p),Fraction(answer))

    def test_invalid_state_rejected(self):
        bad=[
            ('OGE14-G01',dict(initial_mass_mg=320,period_minutes=8,elapsed_minutes=39)),
            ('OGE14-A07',dict(a1=12,decrease_each_second=4,n=5)),
            ('OGE14-A06',dict(first_second_distance=23,decrease_each_second=8)),
            ('OGE14-A09',dict(S=151,first_plus_last=75)),
            ('OGE14-G04',dict(first_height_cm=360,factor_decrease=1,strict_threshold_cm=15)),
        ]
        for fid,p in bad:
            with self.subTest(fid=fid):
                with self.assertRaises(ValueError): solve_closed(fid,p)
                with self.assertRaises(ValueError): solve_enumerated(fid,p)

    def test_mutation_changes_answer_for_sensitive_fields(self):
        targets={
            'OGE14-G03': (dict(initial_mass_mg=160,period_minutes=8,elapsed_minutes=40),'elapsed_minutes',32),
            'OGE14-A05': (dict(T0=-7,t=4,minutes_total=10,decrease_per_minute=6),'t',3),
            'OGE14-A01': (dict(rows=14,a1=20,d=3,target_index=10),'target_index',9),
            'OGE14-G04': (dict(first_height_cm=360,factor_decrease=3,strict_threshold_cm=15),'strict_threshold_cm',41),
        }
        for fid,(p,k,v) in targets.items():
            old=solve_closed(fid,p); revised=copy.deepcopy(p);revised[k]=v
            self.assertNotEqual(old,solve_closed(fid,revised))

if __name__=='__main__': unittest.main()
