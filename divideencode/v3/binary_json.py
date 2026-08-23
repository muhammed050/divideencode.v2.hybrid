"""Typed Binary JSON V2 experiment.

JSON structure is encoded as typed binary nodes. Punctuation is reconstructed
from the tree; whitespace at grammar boundaries and original lexical spellings
are retained so decode(encode(x)) is byte-exact.
"""
from __future__ import annotations
import re
from collections import Counter
MAGIC=b"BJSON"; VERSION=1
T_OBJECT,T_ARRAY,T_STRING,T_INT,T_FLOAT,T_TRUE,T_FALSE,T_NULL,T_KEY_REF=range(1,10)
_WS=re.compile(rb"[ \t\r\n]*"); _STR=re.compile(rb'"(?:\\.|[^"\\])*"'); _NUM=re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')

def u(n):
    if n<0: raise ValueError("negative varint")
    o=bytearray()
    while n>=128:o.append((n&127)|128);n>>=7
    o.append(n);return bytes(o)
def r(d,p):
    n=0;s=0
    while p<len(d):
        b=d[p];p+=1;n|=(b&127)<<s
        if not b&128:return n,p
        s+=7
    raise ValueError("truncated varint")
def s(x):return u(len(x))+x
def g(d,p):
    n,p=r(d,p);e=p+n
    if e>len(d):raise ValueError("truncated bytes")
    return d[p:e],e
def zz(n):return n<<1 if n>=0 else ((-n<<1)-1)
def uzz(n):return n>>1 if not n&1 else -((n>>1)+1)

def _lex(d):
    p=0;o=[]
    while p<len(d):
        m=_WS.match(d,p);ws=m.group(0);p=m.end()
        if p>=len(d):return o,ws
        c=d[p:p+1]
        if c in b"{}[]:,":tok=c;p+=1
        elif c==b'"':
            m=_STR.match(d,p)
            if not m:raise ValueError("invalid JSON string")
            tok=m.group(0);p=m.end()
        elif d.startswith(b"true",p):tok=b"true";p+=4
        elif d.startswith(b"false",p):tok=b"false";p+=5
        elif d.startswith(b"null",p):tok=b"null";p+=4
        else:
            m=_NUM.match(d,p)
            if not m:raise ValueError("invalid JSON token")
            tok=m.group(0);p=m.end()
        o.append((ws,tok))
    return o,b""

class _Parser:
    def __init__(self,t):self.t=t;self.i=0
    def peek(self):return self.t[self.i][1] if self.i<len(self.t) else None
    def take(self):
        if self.i>=len(self.t):raise ValueError("unexpected EOF")
        x=self.t[self.i];self.i+=1;return x
    def value(self):
        ws,tok=self.take()
        if tok==b'{':
            fs=[]
            if self.peek()==b'}':c=self.take();return("obj",ws,fs,c[0])
            while True:
                kws,key=self.take()
                if not key.startswith(b'"') or self.peek()!=b':':raise ValueError("invalid object")
                cws,_=self.take();val=self.value();comma_ws=None
                if self.peek()==b',':comma_ws,_=self.take()
                fs.append((kws,key,cws,val,comma_ws))
                if comma_ws is None:
                    if self.peek()!=b'}':raise ValueError("missing object comma")
                    c=self.take();return("obj",ws,fs,c[0])
                if self.peek()==b'}':raise ValueError("trailing object comma")
        if tok==b'[':
            vs=[]
            if self.peek()==b']':c=self.take();return("arr",ws,vs,c[0])
            while True:
                val=self.value();comma_ws=None
                if self.peek()==b',':comma_ws,_=self.take()
                vs.append((val,comma_ws))
                if comma_ws is None:
                    if self.peek()!=b']':raise ValueError("missing array comma")
                    c=self.take();return("arr",ws,vs,c[0])
                if self.peek()==b']':raise ValueError("trailing array comma")
        if tok.startswith(b'"'):return("str",ws,tok)
        if tok==b"true":return("true",ws)
        if tok==b"false":return("false",ws)
        if tok==b"null":return("null",ws)
        if b'.' in tok or b'e' in tok.lower():return("float",ws,tok)
        return("int",ws,int(tok),tok)

def _collect_keys(n,o):
    if n[0]=="obj":
        for f in n[2]:o.append(f[1]);_collect_keys(f[3],o)
    elif n[0]=="arr":
        for v,_ in n[2]:_collect_keys(v,o)

def _enc_node(n,ids):
    k=n[0];o=bytearray()
    if k=="obj":
        o+=bytes([T_OBJECT])+s(n[1])+u(len(n[2]))
        for kws,key,cws,v,cw in n[2]:
            kid=ids.get(key)
            o+=bytes([T_KEY_REF])+s(kws)+u(kid+1 if kid is not None else 0)
            if kid is None:o+=s(key)
            o+=s(cws)+_enc_node(v,ids)+s(cw or b"")
        o+=s(n[3])
    elif k=="arr":
        o+=bytes([T_ARRAY])+s(n[1])+u(len(n[2]))
        for v,cw in n[2]:o+=_enc_node(v,ids)+s(cw or b"")
        o+=s(n[3])
    elif k=="str":o+=bytes([T_STRING])+s(n[1])+s(n[2])
    elif k=="int":o+=bytes([T_INT])+s(n[1])+u(zz(n[2]))
    elif k=="float":o+=bytes([T_FLOAT])+s(n[1])+s(n[2])
    elif k=="true":o+=bytes([T_TRUE])+s(n[1])
    elif k=="false":o+=bytes([T_FALSE])+s(n[1])
    elif k=="null":o+=bytes([T_NULL])+s(n[1])
    return bytes(o)

def encode(d):
    t,tr=_lex(d);p=_Parser(t);root=p.value()
    if p.i!=len(t):raise ValueError("trailing JSON tokens")
    keys=[];_collect_keys(root,keys);cnt=Counter(keys)
    dic=sorted((k for k,n in cnt.items() if n>=2),key=lambda x:(-cnt[x]*len(x),x));ids={k:i for i,k in enumerate(dic)}
    payload=bytearray(u(len(dic)))
    for k in dic:payload+=s(k)
    payload+=_enc_node(root,ids)+s(tr)
    return MAGIC+bytes([VERSION])+u(len(d))+bytes(payload)

def _dec_node(d,p,dic):
    tag=d[p];p+=1;ws,p=g(d,p);o=bytearray(ws)
    if tag==T_OBJECT:
        n,p=r(d,p);o+=b'{'
        for i in range(n):
            kt=d[p];p+=1
            if kt!=T_KEY_REF:raise ValueError("bad key tag")
            kws,p=g(d,p);kid,p=r(d,p)
            if kid==0:key,p=g(d,p)
            else:
                kid-=1
                if kid>=len(dic):raise ValueError("bad key reference")
                key=dic[kid]
            cws,p=g(d,p);v,p=_dec_node(d,p,dic);cw,p=g(d,p)
            o+=kws+key+cws+b':'+v
            if i+1<n:o+=cw+b','
            elif cw:o+=cw
        close,p=g(d,p);o+=close+b'}'
    elif tag==T_ARRAY:
        n,p=r(d,p);o+=b'['
        for i in range(n):
            v,p=_dec_node(d,p,dic);cw,p=g(d,p);o+=v
            if i+1<n:o+=cw+b','
            elif cw:o+=cw
        close,p=g(d,p);o+=close+b']'
    elif tag==T_STRING:x,p=g(d,p);o+=x
    elif tag==T_INT:z,p=r(d,p);o+=str(uzz(z)).encode()
    elif tag==T_FLOAT:x,p=g(d,p);o+=x
    elif tag==T_TRUE:o+=b'true'
    elif tag==T_FALSE:o+=b'false'
    elif tag==T_NULL:o+=b'null'
    else:raise ValueError("unknown binary JSON tag")
    return bytes(o),p

def decode(blob):
    if len(blob)<6 or blob[:5]!=MAGIC or blob[5]!=VERSION:raise ValueError("invalid BJSON")
    raw,p=r(blob,6);nd,p=r(blob,p);dic=[]
    for _ in range(nd):x,p=g(blob,p);dic.append(x)
    out,p=_dec_node(blob,p,dic);tr,p=g(blob,p);out+=tr
    if p!=len(blob) or len(out)!=raw:raise ValueError("BJSON length mismatch")
    return out
