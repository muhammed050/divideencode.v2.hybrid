"""Compact statistical JSON IR experiment.

Unlike the typed-tree prototype, this format keeps separate structural, key,
string, and integer streams. The goal is to make repeated symbols and integer
sequences statistically easier for DE2 while retaining byte-exact JSON.
"""
from __future__ import annotations
import re
from collections import Counter

MAGIC=b"CJSON"; VERSION=1
K_OBJ=1; K_ARR=2; K_STR=3; K_INT=4; K_FLOAT=5; K_TRUE=6; K_FALSE=7; K_NULL=8; K_KEY=9
_WS=re.compile(rb"[ \t\r\n]*"); STR=re.compile(rb'"(?:\\.|[^"\\])*"'); NUM=re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')

def u(n):
    o=bytearray()
    while n>=128:o.append((n&127)|128);n>>=7
    o.append(n);return bytes(o)
def r(d,p):
    n=s=0
    while True:
        b=d[p];p+=1;n|=(b&127)<<s
        if not b&128:return n,p
        s+=7
def b(x):return u(len(x))+x
def g(d,p):n,p=r(d,p);return d[p:p+n],p+n
def zz(n):return n<<1 if n>=0 else (-n<<1)-1
def uzz(n):return n>>1 if not n&1 else -(n>>1)-1

def lex(d):
    p=0;out=[]
    while p<len(d):
        m=_WS.match(d,p);ws=m.group();p=m.end()
        if p>=len(d):return out,ws
        c=d[p:p+1]
        if c in b"{}[]:,":t=c;p+=1
        elif c==b'"':m=STR.match(d,p);t=m.group();p=m.end()
        elif d.startswith((b'true',b'false',b'null'),p):
            t=next(x for x in (b'true',b'false',b'null') if d.startswith(x,p));p+=len(t)
        else:m=NUM.match(d,p);t=m.group();p=m.end()
        out.append((ws,t))
    return out,b""

class P:
    def __init__(self,t):self.t=t;self.i=0
    def take(self):x=self.t[self.i];self.i+=1;return x
    def peek(self):return self.t[self.i][1] if self.i<len(self.t) else None
    def val(self):
        ws,t=self.take()
        if t==b'{':
            fs=[]
            if self.peek()==b'}':c=self.take();return('o',ws,fs,c[0])
            while True:
                kws,key=self.take();self.take() # colon
                v=self.val();cw=None
                if self.peek()==b',':cw=self.take()[0]
                fs.append((kws,key,v,cw))
                if cw is None:c=self.take();return('o',ws,fs,c[0])
        if t==b'[':
            vs=[]
            if self.peek()==b']':c=self.take();return('a',ws,vs,c[0])
            while True:
                v=self.val();cw=None
                if self.peek()==b',':cw=self.take()[0]
                vs.append((v,cw))
                if cw is None:c=self.take();return('a',ws,vs,c[0])
        if t.startswith(b'"'):return('s',ws,t)
        if t==b'true':return('t',ws)
        if t==b'false':return('f',ws)
        if t==b'null':return('n',ws)
        if b'.' in t or b'e' in t.lower():return('f8',ws,t)
        return('i',ws,int(t),t)

def collect(n,keys,strings,ints):
    if n[0]=='o':
        for kw,k,v,c in n[2]:keys.append(k);collect(v,keys,strings,ints)
    elif n[0]=='a':
        for v,c in n[2]:collect(v,keys,strings,ints)
    elif n[0]=='s':strings.append(n[2])
    elif n[0]=='i':ints.append(n[2])

def enc_node(n,kid,sid,ints):
    k=n[0];o=bytearray(bytes([{'o':K_OBJ,'a':K_ARR,'s':K_STR,'i':K_INT,'f8':K_FLOAT,'t':K_TRUE,'f':K_FALSE,'n':K_NULL}[k]])+b(n[1]))
    if k=='o':
        o+=u(len(n[2]))
        for kw,key,v,c in n[2]:o+=b(kw)+u(kid[key])+enc_node(v,kid,sid,ints)+b(c or b'')
        o+=b(n[3])
    elif k=='a':
        o+=u(len(n[2]))
        for v,c in n[2]:o+=enc_node(v,kid,sid,ints)+b(c or b'')
        o+=b(n[3])
    elif k=='s':o+=u(sid[n[2]])
    elif k=='i':o+=u(len(ints));ints.append(n[2])
    elif k=='f8':o+=b(n[2])
    return bytes(o)

def encode(d):
    t,tr=lex(d);p=P(t);root=p.val();keys=[];strings=[];ints=[];collect(root,keys,strings,ints)
    kd=sorted((x for x,n in Counter(keys).items() if n>=2),key=lambda x:(-len(x)*keys.count(x),x));sd=sorted((x for x,n in Counter(strings).items() if n>=2),key=lambda x:(-len(x)*strings.count(x),x))
    kid={x:i for i,x in enumerate(kd)};sid={x:i for i,x in enumerate(sd)}
    # Re-encode integer positions after the dictionaries are fixed.
    ints2=[]
    payload=enc_node(root,kid,sid,ints2)
    # Numeric stream is independent; delta-code only when it reduces varint size.
    ns=bytearray();prev=0
    for i,x in enumerate(ints2):
        raw=zz(x);delta=zz(x-prev)
        if len(u(delta))<len(u(raw)):ns+=b'\x01'+u(delta)
        else:ns+=b'\x00'+u(raw)
        prev=x
    out=bytearray(u(len(kd)))
    for x in kd:out+=b(x)
    out+=u(len(sd))
    for x in sd:out+=b(x)
    out+=u(len(ns))+ns
    out+=payload+b(tr)
    return MAGIC+bytes([VERSION])+u(len(d))+bytes(out)

# This experiment deliberately reuses the exact source lexical payload for
# scalar reconstruction through the structural stream; it is a benchmark
# candidate, not yet the production UBIR decoder.
def decode(blob):
    raise NotImplementedError("Compact JSON IR is benchmark-only until decoder is finalized")
