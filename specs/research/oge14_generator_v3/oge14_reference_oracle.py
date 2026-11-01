"""Independent mathematical reference for OGE14 research.

Not production generator. No Telegram, network, randomness, or Russian text renderer.
Exact rational arithmetic. Two deliberately different solution paths.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Mapping, Any


def F(value: Any) -> Fraction:
    """Exact conversion; floats are forbidden (precision leak)."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("booleans/floats are not accepted")
    return Fraction(str(value))


def _natural(v: Any, name: str, *, zero: bool = False) -> int:
    value = F(v)
    if value.denominator != 1 or value < (0 if zero else 1):
        raise ValueError(f"{name} must be a valid nonnegative/positive integer")
    return int(value)


def _cycles(p: Mapping[str, Any]) -> int:
    period = _natural(p['period_minutes'], 'period_minutes')
    elapsed = _natural(p['elapsed_minutes'], 'elapsed_minutes', zero=True)
    if elapsed % period:
        raise ValueError('elapsed must be a whole number of periods')
    return elapsed // period


def solve_closed(family_id: str, p: Mapping[str, Any]) -> Fraction:
    """Closed-form equations; independent from brute-force sequence solver."""
    k = family_id.rsplit('-', 1)[-1]
    if k == 'A01':
        n = _natural(p['rows'], 'rows')
        target = _natural(p['target_index'], 'target_index')
        if not 1 <= target <= n: raise ValueError('target outside amphitheater')
        return F(p['a1'])+(target-1)*F(p['d'])
    if k == 'A02':
        known = p['known']
        i,j = sorted(int(q) for q in known)
        n = _natural(p['target_index'], 'target_index')
        if not 1 <= i < j <= n: raise ValueError('invalid known indices')
        delta = (F(known[str(j)])-F(known[str(i)]))/(j-i)
        return F(known[str(i)])+(n-i)*delta
    if k in ('A03','A04','A07','A08'):
        n = _natural(p['rows'] if k=='A03' else p['n'], 'n')
        first=F(p['a1'])
        delta=F(p['d']) if k in ('A03','A04','A08') else -F(p['decrease_each_second'])
        if k=='A07' and first+(n-1)*delta <= 0:
            raise ValueError('braking vehicle stops before n seconds')
        return n*(2*first+(n-1)*delta)/2
    if k == 'A05':
        t=_natural(p['t'],'t',zero=True)
        if t > _natural(p['minutes_total'],'minutes_total'): raise ValueError('time outside experiment')
        return F(p['T0'])-t*F(p['decrease_per_minute'])
    if k == 'A06':
        first=F(p['first_second_distance']); step=F(p['decrease_each_second'])
        if first<=0 or step<=0 or first/step != int(first/step):
            raise ValueError('total brake must stop at integer second')
        n=int(first/step)
        return n*(first+step)/2
    if k == 'A09':
        pair=F(p['first_plus_last']); total=F(p['S'])
        if pair<=0 or total<=0: raise ValueError('bad sum')
        n=2*total/pair
        if n.denominator!=1 or n<2: raise ValueError('noninteger number of days')
        return n
    if k == 'A10':
        n=_natural(p['n'],'n'); index=_natural(p['target_index'],'target_index')
        if n<=1 or index>n: raise ValueError('invalid n and target')
        first=F(p['a1'])
        delta=(2*F(p['sum'])/n-2*first)/(n-1)
        if delta<=0 or delta.denominator!=1: raise ValueError('implausible difference')
        return first+(index-1)*delta
    if k == 'A11':
        return F(p['rate'])*_natural(p['minutes'],'minutes')
    if k=='G01':
        return F(p['initial_mass_mg']) / 2**_cycles(p)
    if k=='G02':
        factor=_natural(p['factor'],'factor')
        if factor<=1: raise ValueError('factor must be >1')
        return F(p['initial_mass_mg'])*factor**_cycles(p)
    if k=='G03':
        start=F(p['initial_mass_mg'])
        return start-start/2**_cycles(p)
    if k=='G04':
        height=F(p['first_height_cm'])
        threshold=F(p['strict_threshold_cm'])
        factor=_natural(p['factor_decrease'],'factor_decrease')
        if height<=0 or threshold<=0 or factor<=1: raise ValueError('invalid bounce')
        for index in range(1,61):
            if height / factor**(index-1) < threshold:
                return Fraction(index)
        raise ValueError('threshold not met within reasonable bound')
    raise KeyError(f'unknown family {family_id}')


def solve_enumerated(family_id: str, p: Mapping[str, Any]) -> Fraction:
    """Iterative independent route; deliberately avoids progression sum formulas."""
    k=family_id.rsplit('-',1)[-1]
    if k=='A01':
        n=_natural(p['rows'],'rows'); target=_natural(p['target_index'],'target_index')
        if not 1<=target<=n: raise ValueError('target outside amphitheater')
        terms=[]; x=F(p['a1'])
        for _ in range(n): terms.append(x); x+=F(p['d'])
        return terms[target-1]
    if k=='A02':
        known=p['known']; i,j=sorted(int(q) for q in known)
        target=_natural(p['target_index'],'target_index')
        if not 1<=i<j<=target: raise ValueError('invalid indices')
        # Independent integer-step search, bounded to exam-like positive increments.
        candidates=[]
        for step in range(1,201):
            x=F(known[str(i)]); vals={i:x}
            for pos in range(i+1,target+1): x+=step; vals[pos]=x
            if vals.get(j)==F(known[str(j)]):candidates.append(vals[target])
        if len(candidates)!=1: raise ValueError('not unique positive difference')
        return candidates[0]
    if k in ('A03','A04','A07','A08'):
        n=_natural(p['rows'] if k=='A03' else p['n'],'n')
        x=F(p['a1']); delta=F(p['d']) if k in ('A03','A04','A08') else -F(p['decrease_each_second'])
        s=Fraction(0)
        for _ in range(n):
            if k=='A07' and x<=0: raise ValueError('nonpositive segment')
            s+=x; x+=delta
        return s
    if k=='A05':
        x=F(p['T0']); t=_natural(p['t'],'t',zero=True)
        if t>_natural(p['minutes_total'],'minutes_total'): raise ValueError('time')
        for _ in range(t): x-=F(p['decrease_per_minute'])
        return x
    if k=='A06':
        x=F(p['first_second_distance']); step=F(p['decrease_each_second'])
        if step<=0 or x<=0: raise ValueError('braking')
        s=Fraction(0)
        for _ in range(100):
            if x==0: return s
            if x<0: raise ValueError('would overshoot stopping')
            s+=x; x-=step
        raise ValueError('too many braking seconds')
    if k=='A09':
        S=F(p['S']); pair=F(p['first_plus_last'])
        candidates=[n for n in range(2,201) if Fraction(n)*pair/2==S]
        if len(candidates)!=1: raise ValueError('nonunique day count')
        return Fraction(candidates[0])
    if k=='A10':
        first=F(p['a1']); n=_natural(p['n'],'n'); target=_natural(p['target_index'],'target_index')
        if not 1<=target<=n: raise ValueError('index')
        found=[]
        for step in range(1,201):
            terms=[first+step*i for i in range(n)]
            if sum(terms,Fraction(0))==F(p['sum']): found.append(terms[target-1])
        if len(found)!=1: raise ValueError('difference not unique')
        return found[0]
    if k=='A11':
        return sum((F(p['rate']) for _ in range(_natural(p['minutes'],'minutes'))),Fraction(0))
    if k in ('G01','G02','G03'):
        cycles=_cycles(p); x=F(p['initial_mass_mg'])
        for _ in range(cycles):
            x=x*F(p['factor']) if k=='G02' else x/2
        return F(p['initial_mass_mg'])-x if k=='G03' else x
    if k=='G04':
        x=F(p['first_height_cm']); th=F(p['strict_threshold_cm'])
        factor=_natural(p['factor_decrease'],'factor_decrease')
        if x<=0 or th<=0 or factor<=1: raise ValueError('bounce')
        for k in range(1,61):
            if x<th:return Fraction(k)
            x/=factor
        raise ValueError('no solution')
    raise KeyError(f'unknown family {family_id}')


def decimal_string(x: Fraction, places: int=2) -> str:
    if x.denominator<=0: raise ValueError('denominator')
    value=x
    for n in range(places+1):
        if (value*10**n).denominator==1:
            numerator=(value*10**n).numerator
            if n==0:return str(numerator)
            sign='-' if numerator<0 else ''
            digits=str(abs(numerator)).zfill(n+1)
            return sign+digits[:-n]+','+digits[-n:]
    raise ValueError('answer is not a short terminating decimal')


def audit_case(family_id: str,p:Mapping[str,Any],expected:str)->None:
    exact=solve_closed(family_id,p)
    checked=solve_enumerated(family_id,p)
    if exact!=checked: raise AssertionError(f'Oracle mismatch for {family_id}: {exact} != {checked}')
    if decimal_string(exact)!=expected.replace('.',','):
        raise AssertionError(f'Regression mismatch for {family_id}: {decimal_string(exact)} != {expected}')
